import contextlib
import sys
from pathlib import Path

import pytest
from conftest import make_app, signed_in
from fake_probe import FakeProbe
from fastapi.testclient import TestClient
from test_apps import wait

from athena.packages.base import CmdResult
from athena.packages.linux import Apt
from athena.platform.detect import detect
from athena.platform.probe import RunResult
from athena.platform.store import CapabilityStore

FIX = Path(__file__).parent / "fixtures" / "packages"


def linux_store(root: bool = True, **binaries: str) -> CapabilityStore:
    bins = {"apt-get": "/usr/bin/apt-get", "flatpak": "/usr/bin/flatpak", **binaries}
    commands = {
        ("/usr/bin/apt-get", "--version"): RunResult(0, "apt 3.0.3 (arm64)\n"),
        ("/usr/bin/flatpak", "--version"): RunResult(0, "Flatpak 1.16.6\n"),
    }
    probe = FakeProbe(os="linux", root=root, binaries=bins, commands=commands)
    return CapabilityStore(detector=lambda: detect(probe))


async def apt_runner(argv, env):
    if argv[0] == "apt-cache":
        return CmdResult(0, (FIX / "apt/search.txt").read_text(), "")
    if argv[0] == "dpkg-query":
        return CmdResult(0, "ii \tgojq\t0.12.17-1\tpure Go jq\n", "")
    if argv[0] == "apt-get":
        return CmdResult(0, (FIX / "apt/upgrade-simulate.txt").read_text(), "")
    return CmdResult(127, "", f"{argv[0]}: not found")


@pytest.fixture
def client_for(tmp_path: Path):
    """A signed-in client factory. The client runs inside `with`, so jobs keep one event
    loop for the whole test."""
    with contextlib.ExitStack() as stack:

        def factory(store: CapabilityStore, runner=apt_runner) -> TestClient:
            app = make_app(tmp_path, store=store)
            app.state.package_runner = runner
            return signed_in(stack.enter_context(TestClient(app)))

        yield factory


def test_packages_need_a_session(client_for, tmp_path: Path) -> None:
    client = TestClient(make_app(tmp_path, store=linux_store()))
    assert client.get("/api/packages").status_code == 401
    assert client.post("/api/packages/apt/install", json={"name": "jq"}).status_code == 401


def test_lists_only_managers_on_this_host(client_for, tmp_path: Path) -> None:
    client = client_for(linux_store())
    managers = {m["id"]: m for m in client.get("/api/packages").json()}
    assert set(managers) == {"apt", "flatpak"}  # snap, brew… aren't installed
    assert managers["apt"]["status"] == "ready" and managers["apt"]["can_refresh"] is True
    assert managers["apt"]["detail"] == "apt 3.0.3 (arm64)"


def test_needs_privilege_is_listed_but_not_usable(client_for, tmp_path: Path) -> None:
    client = client_for(linux_store(root=False))
    apt = next(m for m in client.get("/api/packages").json() if m["id"] == "apt")
    assert (apt["status"], apt["available"]) == ("needs_privilege", False)
    res = client.get("/api/packages/apt/installed")
    assert res.status_code == 409
    assert "root" in res.json()["detail"]
    # Flatpak doesn't need root.
    assert client.get("/api/packages/flatpak/installed").status_code in (200, 502)


def test_unknown_or_missing_manager_is_404(client_for, tmp_path: Path) -> None:
    client = client_for(linux_store())
    assert client.get("/api/packages/snap/installed").status_code == 404
    assert client.get("/api/packages/nope/installed").status_code == 404
    assert client.get("/api/packages/APT/installed").status_code == 422


def test_search_marks_installed(client_for, tmp_path: Path) -> None:
    client = client_for(linux_store())
    res = client.get("/api/packages/apt/search", params={"q": "jq"})
    assert res.status_code == 200, res.text
    by = {p["name"]: p for p in res.json()}
    assert by["gojq"]["installed"] is True
    assert by["fq"]["installed"] is False


def test_search_rejects_option_like_queries(client_for, tmp_path: Path) -> None:
    client = client_for(linux_store())
    for q in ["--help", "", "-x"]:
        assert client.get("/api/packages/apt/search", params={"q": q}).status_code == 422


def test_installed_and_upgradable(client_for, tmp_path: Path) -> None:
    client = client_for(linux_store())
    assert client.get("/api/packages/apt/installed").json()[0]["name"] == "gojq"
    ups = {u["name"]: u for u in client.get("/api/packages/apt/upgradable").json()}
    assert ups["apt"]["latest"] == "3.0.4"


def test_tool_failure_is_502_with_its_message(client_for, tmp_path: Path) -> None:
    async def locked(argv, env):
        return CmdResult(100, "", "E: Could not get lock /var/lib/dpkg/lock-frontend\n")

    client = client_for(linux_store(), runner=locked)
    res = client.get("/api/packages/apt/installed")
    assert res.status_code == 502
    assert "lock-frontend" in res.json()["detail"]


def fake_command(output: str, seconds: float = 0) -> list[str]:
    code = f"import time; time.sleep({seconds}); print({output!r})"
    return [sys.executable, "-c", code]


def test_install_runs_a_job_and_is_audited(
    client_for, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = {}

    def install_argv(self, name, source=None):
        seen["argv"] = (name, source)
        return fake_command(f"Setting up {name}")

    monkeypatch.setattr(Apt, "install_argv", install_argv)
    client = client_for(linux_store())
    res = client.post("/api/packages/apt/install", json={"name": "jq"})
    assert res.status_code == 202, res.text
    job = wait(client, res.json()["id"])
    assert job["status"] == "succeeded"
    assert "Setting up jq" in job["lines"]
    assert seen["argv"] == ("jq", None)
    rows = client.app.state.db.engine.connect().exec_driver_sql(
        "SELECT action, target FROM audit_log"
    )
    assert ("package.install", "apt:jq") in list(rows)


def test_failed_command_fails_the_job(
    client_for, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        Apt, "uninstall_argv", lambda self, name: [sys.executable, "-c", "raise SystemExit(100)"]
    )
    client = client_for(linux_store())
    job = wait(client, client.post("/api/packages/apt/uninstall", json={"name": "jq"}).json()["id"])
    assert job["status"] == "failed"
    assert "exit code 100" in job["error"]


def test_one_job_per_manager(client_for, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Apt, "install_argv", lambda self, n, s=None: fake_command("slow", 2))
    client = client_for(linux_store())
    first = client.post("/api/packages/apt/install", json={"name": "jq"})
    assert first.status_code == 202
    second = client.post("/api/packages/apt/install", json={"name": "curl"})
    assert second.status_code == 409
    assert "busy" in second.json()["detail"]
    wait(client, first.json()["id"])


def test_bad_names_are_rejected(client_for, tmp_path: Path) -> None:
    client = client_for(linux_store())
    for name in ["-y", "--purge", "a b", "x;id", ""]:
        res = client.post("/api/packages/apt/install", json={"name": name})
        assert res.status_code == 422, name


def test_pacman_cannot_upgrade_one(client_for, tmp_path: Path) -> None:
    store = linux_store(pacman="/usr/bin/pacman")
    client = client_for(store)
    res = client.post("/api/packages/pacman/upgrade", json={"name": "bash"})
    assert res.status_code == 400
    assert "everything" in res.json()["detail"]


def test_refresh_only_where_supported(
    client_for, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Apt, "refresh_argv", lambda self: fake_command("Hit:1 deb.debian.org"))
    client = client_for(linux_store(pacman="/usr/bin/pacman"))
    res = client.post("/api/packages/apt/refresh")
    assert res.status_code == 202
    assert wait(client, res.json()["id"])["status"] == "succeeded"
    assert client.post("/api/packages/pacman/refresh").status_code == 400


# ---------------------------------------------------------------- details, icons, logos


async def info_runner(argv, env):
    if argv[:2] == ["apt-cache", "show"]:
        return CmdResult(0, (FIX / "info/apt.txt").read_text(), "")
    if argv[:2] == ["flatpak", "remote-info"]:
        return CmdResult(0, (FIX / "info/flatpak.txt").read_text(), "")
    if argv[0] == "flatpak":
        return CmdResult(0, "", "")
    return await apt_runner(argv, env)


def test_info_returns_details_and_current_installed_state(client_for) -> None:
    client = client_for(linux_store(), info_runner)
    res = client.get("/api/packages/apt/info", params={"name": "gojq"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["version"] == "1.7.1-6+deb13u4" and body["has_icon"] is False
    assert body["installed"] is True  # dpkg-query lists gojq
    assert "icon_url" not in body  # the browser never sees the store's URL


def test_info_failure_is_502(client_for) -> None:
    async def failing(argv, env):
        return CmdResult(100, "", "E: No packages found")

    client = client_for(linux_store(), failing)
    res = client.get("/api/packages/apt/info", params={"name": "nope-zzz"})
    assert res.status_code == 502 and "No packages found" in res.json()["detail"]


def test_info_rejects_option_like_names(client_for) -> None:
    client = client_for(linux_store(), info_runner)
    assert client.get("/api/packages/apt/info", params={"name": "-rf"}).status_code == 422
    assert client.get("/api/packages/apt/icon", params={"name": "--x"}).status_code == 422


def test_icon_comes_from_the_stores_url_through_the_server(
    client_for, monkeypatch: pytest.MonkeyPatch
) -> None:
    from athena.packages import http

    asked: list[tuple[str, tuple[str, ...]]] = []

    async def fake_json(url, headers=None):
        return {"name": "Icons", "icon": "https://dl.flathub.org/media/x/icon.png"}

    async def fake_image(url, hosts):
        asked.append((url, hosts))
        return b"\x89PNG", "image/png"

    monkeypatch.setattr(http, "fetch_json", fake_json)
    monkeypatch.setattr(http, "fetch_image", fake_image)
    client = client_for(linux_store(), info_runner)
    params = {"name": "org.example.IconApp", "source": "flathub"}
    assert client.get("/api/packages/flatpak/info", params=params).json()["has_icon"] is True
    res = client.get("/api/packages/flatpak/icon", params=params)
    assert res.status_code == 200 and res.content == b"\x89PNG"
    assert res.headers["content-type"] == "image/png"
    assert asked == [("https://dl.flathub.org/media/x/icon.png", ("flathub.org", "flatpak.org"))]


def test_no_icon_is_404(client_for) -> None:
    client = client_for(linux_store(), info_runner)
    res = client.get("/api/packages/apt/icon", params={"name": "gojq"})
    assert res.status_code == 404


def test_manager_logo(client_for, monkeypatch: pytest.MonkeyPatch) -> None:
    from athena.packages import http

    asked = []

    async def fake_image(url, hosts):
        asked.append((url, hosts))
        return b"ico", "image/x-icon"

    monkeypatch.setattr(http, "fetch_image", fake_image)
    client = client_for(linux_store())
    managers = {m["id"]: m for m in client.get("/api/packages").json()}
    assert managers["apt"]["has_logo"] is True
    res = client.get("/api/packages/apt/logo")
    assert res.status_code == 200 and res.content == b"ico"
    assert asked == [("https://www.debian.org/favicon.ico", ("debian.org",))]
    assert client.get("/api/packages/snap/logo").status_code == 404  # not on this host


# ------------------------------------------------ changes with the computer's password


def macports_store(root: bool = False) -> CapabilityStore:
    probe = FakeProbe(
        os="darwin",
        root=root,
        paths={"/opt/local/bin/port"},
        commands={("/opt/local/bin/port", "version"): RunResult(0, "Version: 2.12.7\n")},
    )
    return CapabilityStore(detector=lambda: detect(probe))


async def port_runner(argv, env):
    if argv[:3] == ["port", "-q", "search"]:
        return CmdResult(0, (FIX / "macports/search.txt").read_text(), "")
    if argv[:2] == ["port", "-q"]:
        return CmdResult(0, (FIX / "macports/installed.txt").read_text(), "")
    return CmdResult(127, "", "not found")


def test_password_manager_reads_freely_and_changes_need_the_password(
    client_for, monkeypatch: pytest.MonkeyPatch
) -> None:
    from athena.api import packages as api

    runs = []

    async def fake_run(job, argv, what, env=None, stdin=None):
        runs.append((argv, stdin))

    monkeypatch.setattr(api, "run_or_fail", fake_run)
    client = client_for(macports_store(), port_runner)
    listed = {m["id"]: m for m in client.get("/api/packages").json()}
    assert listed["macports"]["elevation"] == "password" and not listed["macports"]["available"]
    assert client.get("/api/packages/macports/search", params={"q": "jq"}).status_code == 200
    assert client.get("/api/packages/macports/installed").status_code == 200

    res = client.post("/api/packages/macports/install", json={"name": "jq"})
    assert res.status_code == 403 and "password" in res.json()["detail"]
    assert runs == []

    res = client.post("/api/packages/macports/install", json={"name": "jq", "password": "hunter2"})
    assert res.status_code == 202, res.text
    job = wait(client, res.json()["id"])
    assert job["status"] == "succeeded"
    argv, stdin = runs[0]
    assert argv[1:5] == ["-S", "-k", "-p", ""] and argv[-3:] == ["-N", "install", "jq"]
    assert stdin == "hunter2\n"
    assert "hunter2" not in str(job)
    rows = list(client.app.state.db.engine.connect().exec_driver_sql("SELECT * FROM audit_log"))
    assert not any("hunter2" in str(r) for r in rows)


def test_root_needs_no_password(client_for, monkeypatch: pytest.MonkeyPatch) -> None:
    from athena.api import packages as api

    runs = []

    async def fake_run(job, argv, what, env=None, stdin=None):
        runs.append((argv, stdin))

    monkeypatch.setattr(api, "run_or_fail", fake_run)
    client = client_for(macports_store(root=True), port_runner)
    res = client.post(
        "/api/packages/macports/uninstall", json={"name": "jq", "password": "ignored"}
    )
    assert res.status_code == 202, res.text
    wait(client, res.json()["id"])
    assert runs[0][0][-3:] == ["-N", "uninstall", "jq"] and runs[0][1] is None
