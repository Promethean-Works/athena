"""Installing package managers: the catalog per OS, password rules, the downloads and the
installer steps (with the network and the real installers faked)."""

import asyncio
import hashlib
from pathlib import Path

import httpx2
import pytest
from fake_probe import FakeProbe
from fastapi.testclient import TestClient

from athena.jobs import Job
from athena.packages import bootstrap, http
from athena.packages.base import PackageError
from athena.platform.capabilities import Capability
from athena.platform.probe import RunResult


def offered(probe: FakeProbe, caps: dict[str, Capability] | None = None) -> dict:
    return {i.id: i for i in bootstrap.installable(probe, caps or {})}


def mac(root: bool = False, tools: bool = True) -> FakeProbe:
    return FakeProbe(
        os="darwin",
        root=root,
        binaries={"git": "/usr/bin/git", "sudo": "/usr/bin/sudo"},
        commands={("xcode-select", "-p"): RunResult(0 if tools else 2, "/Library/Developer\n")},
    )


def test_each_os_offers_its_own_managers() -> None:
    assert set(offered(mac())) == {"brew", "macports"}
    linux = offered(FakeProbe(os="linux", binaries={"git": "g", "curl": "c", "sudo": "s"}))
    assert set(linux) == {"brew", "flatpak"}
    win = FakeProbe(os="windows", binaries={"powershell": "p"})
    assert set(offered(win)) == {"scoop", "choco"}


def test_managers_already_here_are_not_offered() -> None:
    here = {"packages.brew": Capability(id="packages.brew", label="Homebrew", status="ready")}
    assert set(offered(mac(), here)) == {"macports"}
    gone = {"packages.brew": Capability(id="packages.brew", label="Homebrew", status="missing")}
    assert "brew" in offered(mac(), gone)


def test_requirements_say_what_is_missing() -> None:
    out = offered(mac(tools=False))
    tools = next(r for r in out["macports"].requirements if "command line" in r.label)
    assert not tools.met and "xcode-select" in (tools.hint or "")
    assert not out["macports"].ready and out["macports"].needs_password
    # Homebrew refuses to run as root, so a root Athena can't install it.
    brew = offered(mac(root=True))["brew"]
    assert not brew.ready and not brew.needs_password
    # Scoop refuses an elevated session; Chocolatey needs one.
    win = FakeProbe(os="windows", binaries={"powershell": "p"}, root=True)
    assert not offered(win)["scoop"].ready and offered(win)["choco"].ready


def test_flatpak_needs_a_system_manager() -> None:
    linux = FakeProbe(os="linux", binaries={"sudo": "s"}, root=True)
    assert not offered(linux)["flatpak"].ready
    caps = {"packages.apt": Capability(id="packages.apt", label="APT", status="ready")}
    assert offered(linux, caps)["flatpak"].ready


def test_password_rules() -> None:
    macports = bootstrap.INSTALLERS["macports"]
    brew = bootstrap.INSTALLERS["brew"]
    scoop = bootstrap.INSTALLERS["scoop"]
    with pytest.raises(PackageError, match="password"):
        bootstrap.password_for(mac(), macports, None)
    assert bootstrap.password_for(mac(), macports, "pw") == "pw"
    assert bootstrap.password_for(mac(root=True), macports, "pw") is None  # root needs none
    with pytest.raises(PackageError):
        bootstrap.password_for(mac(), brew, "")
    assert bootstrap.password_for(FakeProbe(os="windows"), scoop, "pw") is None


# ---------------------------------------------------------------- downloads


def _mock(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    real = httpx2.AsyncClient
    monkeypatch.setattr(
        http.httpx2,
        "AsyncClient",
        lambda **kw: real(transport=httpx2.MockTransport(handler), **kw),
    )


def test_download_checks_hosts_redirects_and_checksum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = b"#!/bin/sh\necho hi\n"

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/go":
            return httpx2.Response(302, headers={"location": "https://cdn.vendor.example/file"})
        if request.url.path == "/away":
            return httpx2.Response(302, headers={"location": "https://evil.example/file"})
        return httpx2.Response(200, content=body)

    _mock(monkeypatch, handler)
    hosts = ("vendor.example",)
    dest = tmp_path / "f"
    sha = hashlib.sha256(body).hexdigest()
    assert asyncio.run(http.download("https://vendor.example/go", dest, hosts, sha)) == sha
    assert dest.read_bytes() == body
    for url in (
        "https://vendor.example/away",
        "http://vendor.example/x",
        "https://other.example/x",
    ):
        with pytest.raises(PackageError):
            asyncio.run(http.download(url, tmp_path / "g", hosts))
    with pytest.raises(PackageError, match="checksum"):
        asyncio.run(http.download("https://vendor.example/x", tmp_path / "h", hosts, "0" * 64))
    assert not (tmp_path / "h").exists()  # a file that fails its checksum is deleted


# ---------------------------------------------------------------- the installers


class Recorder:
    """Stands in for `run_or_fail` and `Job.run_command`: records what would run."""

    def __init__(self) -> None:
        self.runs: list[tuple[list[str], str | None]] = []

    async def run_or_fail(self, job, argv, what, env=None, stdin=None) -> None:
        self.runs.append((argv, stdin))


def test_macports_picks_the_pkg_for_this_macos_and_checks_its_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sha = "ab" * 32
    release = {
        "tag_name": "v9.9.9",
        "assets": [
            {
                "name": "MacPorts-9.9.9-14-Sonoma.pkg",
                "browser_download_url": "https://github.com/a",
            },
            {
                "name": "MacPorts-9.9.9-27-GoldenGate.pkg",
                "browser_download_url": "https://github.com/b",
                "digest": f"sha256:{sha}",
            },
        ],
    }
    seen = {}

    async def fake_json(url, headers=None):
        return release

    async def fake_download(url, dest, hosts, sha256=None):
        seen.update(url=url, sha=sha256, name=dest.name)
        return sha

    rec = Recorder()
    monkeypatch.setattr(http, "fetch_json", fake_json)
    monkeypatch.setattr(http, "download", fake_download)
    monkeypatch.setattr(bootstrap, "run_or_fail", rec.run_or_fail)
    monkeypatch.setattr(bootstrap.platform, "mac_ver", lambda: ("27.2.1", ("", "", ""), ""))

    ctx = bootstrap.Context(Job("t"), mac(), {}, "secret")
    asyncio.run(bootstrap._install_macports(ctx))
    assert seen == {
        "url": "https://github.com/b",
        "sha": sha,
        "name": "MacPorts-9.9.9-27-GoldenGate.pkg",
    }
    argv, stdin = rec.runs[0]
    assert argv[1:6] == ["-S", "-k", "-p", "", "/usr/sbin/installer"]
    assert argv[-2:] == ["-target", "/"] and stdin == "secret\n"
    assert "secret" not in " ".join(ctx.job.lines)

    monkeypatch.setattr(bootstrap.platform, "mac_ver", lambda: ("99.0", ("", "", ""), ""))
    with pytest.raises(PackageError, match="no installer for macOS 99"):
        asyncio.run(bootstrap._install_macports(ctx))


def test_flatpak_uses_the_distros_manager_then_adds_flathub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = Recorder()
    monkeypatch.setattr(bootstrap, "run_or_fail", rec.run_or_fail)
    caps = {"packages.dnf": Capability(id="packages.dnf", label="DNF", status="ready")}
    asyncio.run(bootstrap._install_flatpak(bootstrap.Context(Job("t"), FakeProbe(), caps, None)))
    assert rec.runs[0][0][-3:] == ["install", "-y", "flatpak"] or "flatpak" in rec.runs[0][0]
    assert rec.runs[1][0][1:4] == ["remote-add", "--if-not-exists", "flathub"]
    with pytest.raises(PackageError):
        asyncio.run(bootstrap._install_flatpak(bootstrap.Context(Job("t"), FakeProbe(), {}, None)))


def test_installer_refuses_when_a_requirement_is_not_met() -> None:
    inst = bootstrap.INSTALLERS["macports"]

    async def refresh():
        raise AssertionError("must not run")

    with pytest.raises(PackageError, match="Xcode"):
        asyncio.run(bootstrap.run_installer(Job("t"), inst, mac(tools=False), {}, "pw", refresh))


# ---------------------------------------------------------------- the API


def _client(tmp_path: Path, stack, probe: FakeProbe) -> TestClient:
    from conftest import make_app, signed_in
    from test_packages_api import linux_store

    app = make_app(tmp_path, store=linux_store())
    app.state.package_probe = probe
    return signed_in(stack.enter_context(TestClient(app)))


def test_installable_endpoints(tmp_path: Path) -> None:
    import contextlib

    with contextlib.ExitStack() as stack:
        client = _client(tmp_path, stack, mac())
        listing = {i["id"]: i for i in client.get("/api/packages/installable").json()}
        assert set(listing) == {"brew", "macports"}
        assert listing["macports"]["needs_password"] is True
        assert client.get("/api/packages/installable/nope/logo").status_code == 404
        assert client.post("/api/packages/installable/nope/install", json={}).status_code == 404
        # No password: refused before anything runs.
        res = client.post("/api/packages/installable/macports/install", json={})
        assert res.status_code == 403 and "password" in res.json()["detail"]
        client.cookies.clear()
        assert client.get("/api/packages/installable").status_code == 401


def test_installing_a_manager_runs_a_job_redetects_and_is_audited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import contextlib
    import dataclasses

    from test_apps import wait

    ran = []

    async def fake_run(ctx):
        ran.append(ctx.password)
        await ctx.job.log("installing…")

    inst = dataclasses.replace(bootstrap.INSTALLERS["macports"], run=fake_run)
    monkeypatch.setitem(bootstrap.INSTALLERS, "macports", inst)
    with contextlib.ExitStack() as stack:
        client = _client(tmp_path, stack, mac())
        refreshed = []
        store = client.app.state.capabilities
        real_refresh = store.refresh

        async def refresh():
            refreshed.append(True)
            return await real_refresh()

        monkeypatch.setattr(store, "refresh", refresh)
        res = client.post("/api/packages/installable/macports/install", json={"password": "pw"})
        assert res.status_code == 202, res.text
        job = wait(client, res.json()["id"])
        assert job["status"] == "succeeded" and "installing…" in job["lines"]
        assert ran == ["pw"] and refreshed == [True]
        assert "pw" not in str(job)
        rows = client.app.state.db.engine.connect().exec_driver_sql(
            "SELECT action, target FROM audit_log"
        )
        assert ("package.bootstrap", "macports") in list(rows)


def test_a_manager_whose_requirements_are_unmet_is_not_installed(tmp_path: Path) -> None:
    import contextlib

    with contextlib.ExitStack() as stack:
        client = _client(tmp_path, stack, mac(tools=False))
        res = client.post("/api/packages/installable/macports/install", json={"password": "pw"})
        assert res.status_code == 409 and "Xcode" in res.json()["detail"]
