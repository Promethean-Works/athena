"""The setup wizard: step state, network setting, runtime options/plans and Kiri detection."""

import asyncio
from pathlib import Path

import pytest
from conftest import make_app, signed_in
from fake_probe import FakeProbe
from fastapi.testclient import TestClient

from athena.containers import installers
from athena.containers.installers import FILE, options_for, plan_install, run_plan, with_privilege
from athena.platform.detect import detect, detect_containers_darwin, detect_containers_linux
from athena.platform.probe import RunResult
from athena.platform.store import CapabilityStore

# ---------------------------------------------------------------- plans


def test_docker_engine_uses_the_distro_package_and_starts_the_service() -> None:
    plan = plan_install("docker-engine", "linux", "x86_64", {"apt"})
    assert plan is not None and plan.needs_root
    assert plan.steps == [
        ["apt-get", "install", "-y", "docker.io"],
        ["systemctl", "enable", "--now", "docker"],
    ]
    alpine = plan_install("docker-engine", "linux", "x86_64", {"apk"})
    assert alpine is not None
    assert alpine.steps[1:] == [
        ["rc-update", "add", "docker", "default"],
        ["service", "docker", "start"],
    ]


def test_no_package_manager_means_no_plan_but_manual_steps() -> None:
    assert plan_install("docker-engine", "linux", "x86_64", set()) is None
    docker = next(o for o in options_for("linux", "x86_64", set(), None) if o.id == "docker-engine")
    assert not docker.can_install and docker.manual


def test_kiri_downloads_the_pinned_file_for_the_arch() -> None:
    deb = plan_install("kiri", "linux", "aarch64", {"apt"})
    assert deb is not None and deb.download is not None
    assert deb.download.filename == f"kiri_{installers.KIRI_VERSION}_arm64.deb"
    assert deb.download.url.startswith("https://github.com/libracoder/kiri/releases/download/")
    assert deb.steps == [["apt-get", "install", "-y", FILE]]
    rpm = plan_install("kiri", "linux", "x86_64", {"dnf"})
    assert rpm is not None and rpm.download is not None
    assert rpm.download.filename.endswith(".x86_64.rpm")
    assert plan_install("kiri", "linux", "x86_64", {"pacman"}) is None
    msi = plan_install("kiri", "windows", "AMD64", set())
    assert msi is not None and msi.steps == [["msiexec", "/i", FILE, "/qn"]]
    brew = plan_install("kiri", "darwin", "arm64", {"brew"})
    assert brew is not None and brew.steps[0] == [
        "brew",
        "install",
        "--cask",
        "libracoder/kiri/kiri",
    ]


def test_options_list_only_what_the_os_supports_detected_first() -> None:
    mac = [o.id for o in options_for("darwin", "arm64", {"brew"}, "kiri")]
    assert mac == ["kiri", "colima", "podman"]
    win = [o.id for o in options_for("windows", "x86_64", {"winget"}, None)]
    assert win == ["wsl-docker", "podman", "rancher-desktop", "kiri"]
    linux = {o.id: o for o in options_for("linux", "x86_64", {"apt"}, None)}
    assert set(linux) == {"docker-engine", "podman", "kiri", "ferrocrate"}
    assert linux["ferrocrate"].tag == "experimental" and not linux["ferrocrate"].can_install
    assert linux["kiri"].tag == "new" and linux["docker-engine"].recommended


def test_non_root_cli_prefixes_sudo_only_for_root_plans() -> None:
    plan = plan_install("docker-engine", "linux", "x86_64", {"apt"})
    assert plan is not None
    assert with_privilege(plan, False).steps[0][:2] == ["sudo", "apt-get"]
    assert with_privilege(plan, True) is plan
    brew = plan_install("colima", "darwin", "arm64", {"brew"})
    assert brew is not None and with_privilege(brew, False) is brew


def test_run_plan_checks_the_download_and_substitutes_the_path(monkeypatch) -> None:
    plan = plan_install("kiri", "linux", "x86_64", {"apt"})
    assert plan is not None
    ran: list[list[str]] = []

    async def fake_fetch(url, sha256, **kw):
        assert sha256 == plan.download.sha256
        return b"deb"

    async def step(argv: list[str]) -> None:
        ran.append(argv)

    async def say(_: str) -> None:
        return None

    monkeypatch.setattr(installers, "fetch_verified", fake_fetch)
    asyncio.run(run_plan(plan, step, say))
    assert ran[0][:3] == ["apt-get", "install", "-y"]
    assert ran[0][3].endswith(plan.download.filename)


def test_run_plan_stops_on_a_bad_download(monkeypatch) -> None:
    plan = plan_install("kiri", "linux", "x86_64", {"apt"})
    assert plan is not None

    async def bad_fetch(url, sha256, **kw):
        raise installers.DownloadError("checksum mismatch")

    async def nothing(_) -> None:
        raise AssertionError("must not run")

    monkeypatch.setattr(installers, "fetch_verified", bad_fetch)
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        asyncio.run(run_plan(plan, nothing, nothing))


# ---------------------------------------------------------------- detection

KIRI_CONTEXT = ["docker", "context", "inspect", "kiri", "--format", "{{.Endpoints.docker.Host}}"]


def test_kiri_is_found_through_its_docker_context() -> None:
    endpoint = "unix:///home/me/.kiri/docker.sock"
    probe = FakeProbe(
        os="linux",
        binaries={"kiri": "/usr/bin/kiri"},
        commands={tuple(KIRI_CONTEXT): RunResult(0, endpoint + "\n")},
        engines={endpoint: "28.0.0"},
    )
    cap = detect_containers_linux(probe)
    assert (cap.status, cap.provider, cap.endpoint) == ("ready", "kiri", endpoint)


def test_kiri_installed_but_stopped_offers_start() -> None:
    probe = FakeProbe(os="darwin", binaries={"kiri": "/opt/homebrew/bin/kiri"})
    cap = detect_containers_darwin(probe)
    assert (cap.status, cap.provider, cap.actions) == ("stopped", "kiri", ["start"])


def test_ferrocrate_is_found_by_its_socket() -> None:
    probe = FakeProbe(
        os="linux",
        binaries={"ferro-cli": "/usr/local/bin/ferro-cli"},
        engines={"unix:///var/run/ferrocrate.sock": "1.0"},
    )
    assert detect_containers_linux(probe).provider == "ferrocrate"


# ---------------------------------------------------------------- API


def client_for(tmp_path: Path, os_name: str = "linux") -> TestClient:
    probe = FakeProbe(os=os_name)  # pyright: ignore[reportArgumentType]
    store = CapabilityStore(detector=lambda: detect(probe))
    return TestClient(make_app(tmp_path, store=store))


def test_state_follows_the_real_settings(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        signed_in(client)
        state = client.get("/api/onboarding").json()
        done = {s["id"]: s["done"] for s in state["steps"]}
        assert not state["completed"]
        assert done["account"] and not done["runtime"]
        assert done["locations"]  # Home and App data are added on the first start
        assert not done["language"]
        client.put(
            "/api/settings/appearance",
            json={"mode": "dark", "language": "pt-BR"},
        ).raise_for_status()
        done = {s["id"]: s["done"] for s in client.get("/api/onboarding").json()["steps"]}
        assert done["language"]


def test_network_saves_to_the_settings_file_and_asks_for_a_restart(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        signed_in(client)
        res = client.put("/api/onboarding/network", json={"host": "127.0.0.1", "port": 8500})
        assert res.status_code == 200, res.text
        assert res.json()["restart_required"] is True
        text = (tmp_path / "data" / "athena.json").read_text(encoding="utf-8")
        assert '"port": 8500' in text and '"host": "127.0.0.1"' in text
        again = client.put("/api/onboarding/network", json={"host": "127.0.0.1", "port": 8500})
        assert again.json()["restart_required"] is False


def test_network_rejects_other_addresses_and_bad_ports(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        signed_in(client)
        assert (
            client.put("/api/onboarding/network", json={"host": "evil", "port": 80}).status_code
            == 422
        )
        assert (
            client.put("/api/onboarding/network", json={"host": "0.0.0.0", "port": 0}).status_code
            == 422
        )


def test_complete_and_reset(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        signed_in(client)
        assert client.post("/api/onboarding/complete").status_code == 204
        assert client.get("/api/onboarding").json()["completed"] is True
        assert client.post("/api/onboarding/reset").status_code == 204
        assert client.get("/api/onboarding").json()["completed"] is False


def test_onboarding_needs_a_session(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        assert client.get("/api/onboarding").status_code == 401
        assert client.get("/api/containers/runtime/options").status_code == 401


def test_runtime_options_and_install_refusal(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        signed_in(client)
        options = client.get("/api/containers/runtime/options").json()
        assert {o["id"] for o in options} == {"docker-engine", "podman", "kiri", "ferrocrate"}
        assert not any(o["can_install"] for o in options)  # the fake host has no package manager
        res = client.post("/api/containers/runtime/install", json={"id": "docker-engine"})
        assert res.status_code == 409
        bad = client.post("/api/containers/runtime/install", json={"id": "x; rm -rf /"})
        assert bad.status_code == 422


# ---------------------------------------------------------------- CLI

CLI_PASSWORD = "a long enough password"


@pytest.fixture
def ready_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI sees a host whose engine already works (nothing is installed in tests)."""
    probe = FakeProbe(
        os="linux",
        binaries={"kiri": "/usr/bin/kiri"},
        commands={tuple(KIRI_CONTEXT): RunResult(0, "unix:///k.sock\n")},
        engines={"unix:///k.sock": "28.0"},
    )
    monkeypatch.setattr("athena.platform.detect.detect", lambda: detect(probe))


def onboard(monkeypatch: pytest.MonkeyPatch, data_dir: Path, *args: str, stdin: str = "") -> int:
    import io

    from athena.cli import main

    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return main(["onboard", "--data-dir", str(data_dir), *args])


def test_onboard_yes_sets_everything_from_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ready_runtime, capsys
) -> None:
    import json

    from sqlmodel import Session, select

    from athena.db import Database, User
    from athena.db.models import FileLocation

    data = tmp_path / "data"
    media = tmp_path / "media"
    media.mkdir()
    code = onboard(
        monkeypatch,
        data,
        "--yes",
        "--password-stdin",
        "--username",
        "boss",
        "--language",
        "pt-BR",
        "--location",
        f"Media={media}",
        "--host",
        "127.0.0.1",
        "--port",
        "8600",
        stdin=CLI_PASSWORD + "\n",
    )
    assert code == 0, capsys.readouterr()
    config = json.loads((data / "athena.json").read_text(encoding="utf-8"))
    assert config["server"]["port"] == 8600 and config["server"]["host"] == "127.0.0.1"
    assert config["onboarding"]["completed_at"]
    database = Database(data / "athena.db")
    with Session(database.engine) as db:
        user = db.exec(select(User)).one()
        assert user.username == "boss" and json.loads(user.appearance)["language"] == "pt-BR"
        assert [loc.name for loc in db.exec(select(FileLocation))] == ["Media"]
    database.engine.dispose()


def test_onboard_runs_again_and_reset_reopens_the_wizard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ready_runtime
) -> None:
    import json

    data = tmp_path / "data"
    args = ("--yes", "--password-stdin", "--port", "8600")
    assert onboard(monkeypatch, data, *args, stdin=CLI_PASSWORD + "\n") == 0
    assert onboard(monkeypatch, data, "--yes", "--port", "8601") == 0  # account exists: no password
    config = json.loads((data / "athena.json").read_text(encoding="utf-8"))
    assert config["server"]["port"] == 8601
    assert onboard(monkeypatch, data, "--reset") == 0
    config = json.loads((data / "athena.json").read_text(encoding="utf-8"))
    assert config["onboarding"]["completed_at"] is None


def test_onboard_prompts_for_each_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ready_runtime
) -> None:
    import json

    answers = iter(["owner", "en", "", "n", "8700"])  # user, language, no folders, local only, port
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": CLI_PASSWORD)
    data = tmp_path / "data"
    from athena.cli import main

    assert main(["onboard", "--data-dir", str(data)]) == 0
    config = json.loads((data / "athena.json").read_text(encoding="utf-8"))
    assert (config["server"]["host"], config["server"]["port"]) == ("127.0.0.1", 8700)


def test_onboard_refuses_bad_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ready_runtime, capsys
) -> None:
    data = tmp_path / "data"
    assert onboard(monkeypatch, data, "--yes") == 1  # --yes can't invent a password
    assert "password-stdin" in capsys.readouterr().err
    short = onboard(monkeypatch, data, "--yes", "--password-stdin", stdin="short\n")
    assert short == 1
    ok = ("--yes", "--password-stdin")
    assert onboard(monkeypatch, data, *ok, "--language", "klingon!!", stdin=CLI_PASSWORD) == 1
    assert onboard(monkeypatch, data, "--yes", "--location", "nope") == 1
    assert onboard(monkeypatch, data, "--yes", "--location", f"X={tmp_path}/missing") == 1
    assert onboard(monkeypatch, data, "--yes", "--port", "70000") == 1
