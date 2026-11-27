"""Optional parts of a store app (Compose profiles): metadata rules, install, switching."""

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from test_apps import api, wait  # noqa: F401  (api is a fixture)

import athena.api.apps as apps_api
from athena.catalog.model import InvalidCatalogAppError, parse_app
from athena.catalog.requirements import unmet_requirements
from athena.platform.capabilities import Capability, CapabilityManifest

COMPOSE = """\
x-athena:
  title: P
  description: d
  category: utilities
  web_port: WEB_PORT
  env:
    - {key: WEB_PORT, label: Port, type: port, default: "8080"}
  profiles:
    - id: browser
      label: Browser
      description: A real browser
      env: {BROWSER_URL: "http://browser:9222"}
    - id: sandbox
      label: Sandbox
      default: true
      requires: [docker-socket]
services:
  app:
    image: app:1
    ports: ["${WEB_PORT}:80"]
    environment:
      BROWSER_URL: ${BROWSER_URL:-}
  browser:
    image: browser:1
    profiles: [browser]
  sandboxd:
    image: sandboxd:1
    profiles: [sandbox]
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
"""


def build(text: str = COMPOSE):
    return parse_app("p", "builtin", [("compose.yaml", text, yaml.safe_load(text))])


def manifest(os_: str = "linux", containers: str = "ready") -> CapabilityManifest:
    return CapabilityManifest(
        os=os_,  # type: ignore[arg-type]
        os_version="1",
        arch="arm64",
        detected_at=datetime.now(UTC),
        capabilities=[Capability(id="containers", label="Containers", status=containers)],  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------- metadata rules


def test_profiles_split_core_and_optional_images_and_find_docker_access() -> None:
    app = build()
    variant = app.variants[0]
    assert variant.core_images == ["app:1"]
    assert variant.images == ["app:1", "browser:1", "sandboxd:1"]
    assert variant.profiles_used == ["browser", "sandbox"]
    assert variant.docker_access is False
    assert variant.docker_access_profiles == ["sandbox"]
    assert app.core_images == ["app:1"]


def test_core_docker_socket_is_flagged() -> None:
    text = COMPOSE.replace(
        '    ports: ["${WEB_PORT}:80"]\n',
        '    ports: ["${WEB_PORT}:80"]\n'
        '    volumes: ["/var/run/docker.sock:/var/run/docker.sock:ro"]\n',
    )
    assert build(text).variants[0].docker_access is True


def test_service_profile_must_be_declared() -> None:
    text = COMPOSE.replace("    profiles: [browser]\n", "    profiles: [browser, gpu]\n")
    with pytest.raises(InvalidCatalogAppError, match="doesn't list"):
        build(text)


def test_unknown_requirement_is_refused() -> None:
    text = COMPOSE.replace("requires: [docker-socket]", "requires: [warp-drive]")
    with pytest.raises(InvalidCatalogAppError, match="unknown"):
        build(text)


def test_declared_profile_must_be_used() -> None:
    text = COMPOSE.replace("    profiles: [sandbox]\n", "")
    with pytest.raises(InvalidCatalogAppError, match="aren't used"):
        build(text)


def test_profile_env_keys_count_as_declared_variables() -> None:
    # BROWSER_URL is only declared under the browser profile's env.
    assert "BROWSER_URL" in build().compose


def test_requirements_follow_the_host() -> None:
    assert unmet_requirements(["docker-socket"], manifest()) == []
    assert unmet_requirements(["docker-socket"], manifest(containers="missing"))
    assert unmet_requirements(["same-path-mounts"], manifest("darwin")) == []
    assert "Windows" in unmet_requirements(["same-path-mounts"], manifest("windows"))[0]


# ---------------------------------------------------------------- install and switching


@pytest.fixture
def profiled(api: TestClient, monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    api.app.state.catalogs._apps[("builtin", "p")] = build()
    calls: list[list[str]] = []

    def fake(runtime, name, path, *args):
        calls.append(list(args))
        return [sys.executable, "-c", f"print('compose {args[0]}')"]

    monkeypatch.setattr(apps_api, "compose", fake)
    api.calls = calls  # type: ignore[attr-defined]
    return api


def test_detail_lists_profiles_and_docker_access(profiled: TestClient) -> None:
    detail = profiled.get("/api/store/apps/builtin/p").json()
    by_id = {p["id"]: p for p in detail["profiles"]}
    assert detail["docker_access"] is False
    assert by_id["browser"]["enabled"] is False
    assert by_id["sandbox"]["enabled"] is True  # on by default; the test host has Docker
    assert by_id["sandbox"]["docker_access"] is True
    assert by_id["browser"]["docker_access"] is False


def test_install_defaults_write_compose_profiles(profiled: TestClient, tmp_path: Path) -> None:
    res = profiled.post("/api/store/apps/builtin/p/install", json={"name": "p1"})
    assert res.status_code == 202, res.text
    assert wait(profiled, res.json()["id"])["status"] == "succeeded"
    env = (tmp_path / "data" / "apps" / "p1" / ".env").read_text()
    assert "COMPOSE_PROFILES='sandbox'" in env
    assert "BROWSER_URL" not in env


def test_install_choosing_profiles_writes_their_env(profiled: TestClient, tmp_path: Path) -> None:
    res = profiled.post(
        "/api/store/apps/builtin/p/install", json={"name": "p2", "profiles": ["browser"]}
    )
    assert res.status_code == 202, res.text
    wait(profiled, res.json()["id"])
    env = (tmp_path / "data" / "apps" / "p2" / ".env").read_text()
    assert "COMPOSE_PROFILES='browser'" in env
    assert "BROWSER_URL='http://browser:9222'" in env


def test_install_rejects_unknown_profile(profiled: TestClient) -> None:
    res = profiled.post("/api/store/apps/builtin/p/install", json={"name": "p3", "profiles": ["x"]})
    assert res.status_code == 422
    assert "no such option" in res.json()["detail"]["errors"]["profiles"]


def test_install_rejects_profile_the_host_cant_run(
    profiled: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "athena.catalog.profiles.profile_problem",
        lambda profile, manifest, plat: "needs the Docker socket" if profile.requires else None,
    )
    res = profiled.post(
        "/api/store/apps/builtin/p/install", json={"name": "p4", "profiles": ["sandbox"]}
    )
    assert res.status_code == 422
    assert "Docker socket" in res.json()["detail"]["errors"]["profiles"]
    # The default (sandbox on) is dropped for a host that can't run it, not an error.
    ok = profiled.post("/api/store/apps/builtin/p/install", json={"name": "p5"})
    assert ok.status_code == 202


def test_switching_profiles_rewrites_env_and_removes_dropped_services(
    profiled: TestClient, tmp_path: Path
) -> None:
    wait(
        profiled,
        profiled.post("/api/store/apps/builtin/p/install", json={"name": "sw"}).json()["id"],
    )
    profiled.calls.clear()  # type: ignore[attr-defined]

    res = profiled.put("/api/apps/sw/profiles", json={"profiles": ["browser"]})
    assert res.status_code == 202, res.text
    assert wait(profiled, res.json()["id"])["status"] == "succeeded"
    env = (tmp_path / "data" / "apps" / "sw" / ".env").read_text()
    assert "COMPOSE_PROFILES='browser'" in env
    assert "BROWSER_URL='http://browser:9222'" in env
    assert "WEB_PORT=" in env  # the install-form values survive
    # sandbox was on and is now off: its service is stopped and removed explicitly.
    assert ["rm", "--stop", "--force", "sandboxd"] in profiled.calls  # type: ignore[attr-defined]

    detail = profiled.get("/api/apps/sw").json()
    assert {p["id"]: p["enabled"] for p in detail["profiles"]} == {
        "browser": True,
        "sandbox": False,
    }

    # Switching everything off clears the keys the profiles set.
    wait(profiled, profiled.put("/api/apps/sw/profiles", json={"profiles": []}).json()["id"])
    env = (tmp_path / "data" / "apps" / "sw" / ".env").read_text()
    assert "COMPOSE_PROFILES=''" in env
    assert "BROWSER_URL" not in env


def test_switching_needs_a_store_app_with_profiles(api: TestClient) -> None:  # noqa: F811
    wait(
        api,
        api.post(
            "/api/apps",
            json={"name": "plain", "compose": "services:\n  a:\n    image: x:1\n"},
        ).json()["id"],
    )
    res = api.put("/api/apps/plain/profiles", json={"profiles": []})
    assert res.status_code == 409
