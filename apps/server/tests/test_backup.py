"""Backup destinations (docs/specs/backup.md, part 2a): restic, passwords, the routes."""

import asyncio
import bz2
import io
import logging
import os
import shutil
import sys
import zipfile
from collections.abc import Sequence
from pathlib import Path

import httpx2
import pytest
from conftest import make_app, signed_in
from fastapi.testclient import TestClient

from athena.backup import repository, restic
from athena.backup.repository import DestinationError
from athena.backup.restic import Repository, Restic, ResticError, Result
from athena.backup.service import ResticProvider
from athena.crypto import SecretBox
from athena.db.models import BackupDestination, BackupPlan
from athena.downloads import DownloadError, extract_single
from athena.settings_file import SettingsFile, SettingsFileError

PASSWORD = "correct horse battery staple"


# ---------------------------------------------------------------- fakes


class FakeRestic(Restic):
    """A restic that answers from a script instead of running a program."""

    def __init__(self, results: Sequence[Result] = ()) -> None:
        super().__init__(Path("restic"))
        self.results = list(results)
        self.calls: list[tuple[str, ...]] = []
        self.repos: list[Repository] = []

    async def run(  # type: ignore[override]
        self, repo: Repository, *args: str, timeout: float = 0, stdin: bytes | None = None
    ) -> Result:
        self.calls.append(args)
        self.repos.append(repo)
        return self.results.pop(0) if self.results else Result(0, "", "")


class FakeProvider(ResticProvider):
    def __init__(self, tool: Restic) -> None:
        super().__init__(Path("unused"))
        self.tool = tool

    async def get(self, log_line=None) -> Restic:  # type: ignore[no-untyped-def,override]
        return self.tool


def ok(out: str = "") -> Result:
    return Result(0, out, "")


def client_for(tmp_path: Path, tool: Restic | None = None) -> TestClient:
    app = make_app(tmp_path, backup_allowed_roots=[tmp_path])
    app.state.restic = FakeProvider(tool or FakeRestic())
    return signed_in(TestClient(app))


def folder(tmp_path: Path, name: str = "backups") -> str:
    return str(tmp_path / name)


# ---------------------------------------------------------------- downloads


def test_every_checksum_is_for_the_pinned_version() -> None:
    assert all(f"_{restic.VERSION}_" in name for name in restic.CHECKSUMS)
    assert all(len(sha) == 64 for sha in restic.CHECKSUMS.values())


@pytest.mark.parametrize(
    ("system", "machine", "asset"),
    [
        ("Linux", "x86_64", "restic_{v}_linux_amd64.bz2"),
        ("Linux", "aarch64", "restic_{v}_linux_arm64.bz2"),
        ("Linux", "armv7l", "restic_{v}_linux_arm.bz2"),
        ("Darwin", "arm64", "restic_{v}_darwin_arm64.bz2"),
        ("Windows", "AMD64", "restic_{v}_windows_amd64.zip"),
    ],
)
def test_asset_for(system: str, machine: str, asset: str) -> None:
    assert restic.asset_for(system, machine) == asset.format(v=restic.VERSION)


def test_asset_for_unsupported_cpu() -> None:
    with pytest.raises(DownloadError):
        restic.asset_for("Linux", "riscv64")
    with pytest.raises(DownloadError):
        restic.asset_for("Windows", "arm64")


def test_extract_single_from_bz2_and_zip() -> None:
    assert extract_single(bz2.compress(b"program"), "restic_1_linux_amd64.bz2") == b"program"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("restic_1_windows_amd64.exe", b"exe")
    assert extract_single(buf.getvalue(), "restic_1_windows_amd64.zip") == b"exe"


def test_extract_single_refuses_a_zip_with_no_or_many_programs() -> None:
    for names in ([], ["a.exe", "b.exe"], ["readme.txt"]):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for n in names:
                zf.writestr(n, b"x")
        with pytest.raises(DownloadError):
            extract_single(buf.getvalue(), "x.zip")


def test_extract_single_refuses_garbage_and_decompression_bombs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(DownloadError):
        extract_single(b"not bzip2", "x.bz2")
    monkeypatch.setattr("athena.downloads.MAX_ARCHIVE_BYTES", 1000)
    with pytest.raises(DownloadError, match="larger than expected"):
        extract_single(bz2.compress(b"\0" * 100_000), "x.bz2")


def _serving(monkeypatch: pytest.MonkeyPatch, payload: bytes, sha: str | None = None):
    asset = restic.asset_for("Linux", "x86_64")
    monkeypatch.setattr(restic.platform, "system", lambda: "Linux")
    monkeypatch.setattr(restic.platform, "machine", lambda: "x86_64")
    archive = bz2.compress(payload)
    import hashlib

    monkeypatch.setitem(restic.CHECKSUMS, asset, sha or hashlib.sha256(archive).hexdigest())
    hits: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        hits.append(str(request.url))
        return httpx2.Response(200, content=archive)

    return httpx2.MockTransport(handler), hits


def test_ensure_restic_installs_once_and_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport, hits = _serving(monkeypatch, b"#!/bin/sh\necho restic\n")
    binary = asyncio.run(restic.ensure_restic(tmp_path, transport=transport))
    assert binary.read_bytes().startswith(b"#!/bin/sh")
    assert hits == [
        f"https://github.com/restic/restic/releases/download/v{restic.VERSION}/"
        f"{restic.asset_for('Linux', 'x86_64')}"
    ]
    asyncio.run(restic.ensure_restic(tmp_path, transport=transport))
    assert len(hits) == 1  # the second call found a verified binary


def test_ensure_restic_downloads_again_when_the_binary_was_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport, hits = _serving(monkeypatch, b"good")
    binary = asyncio.run(restic.ensure_restic(tmp_path, transport=transport))
    binary.write_bytes(b"tampered")
    asyncio.run(restic.ensure_restic(tmp_path, transport=transport))
    assert binary.read_bytes() == b"good"
    assert len(hits) == 2


def test_ensure_restic_refuses_a_download_with_the_wrong_checksum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport, _ = _serving(monkeypatch, b"evil", sha="0" * 64)
    with pytest.raises(DownloadError, match="checksum"):
        asyncio.run(restic.ensure_restic(tmp_path, transport=transport))
    assert not restic.binary_path(tmp_path).exists()


# ---------------------------------------------------------------- the runner


class Spawned:
    args: tuple = ()
    env: dict[str, str] = {}  # noqa: RUF012
    kwargs: dict = {}  # noqa: RUF012


def test_the_password_goes_through_the_environment_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = Spawned()

    class FakeProc:
        returncode = 0

        async def communicate(self, data: bytes | None = None) -> tuple[bytes, bytes]:
            return b"out", b""

        async def wait(self) -> int:
            return 0

    async def spawn(*args: str, **kwargs):  # type: ignore[no-untyped-def]
        seen.args, seen.env, seen.kwargs = args, kwargs["env"], kwargs
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setenv("RESTIC_PASSWORD", "inherited-from-the-host")
    repo = Repository(str(tmp_path / "repo"), PASSWORD)
    result = asyncio.run(Restic(tmp_path / "restic").run(repo, "snapshots", "--json"))
    assert result == Result(0, "out", "")
    assert all(PASSWORD not in str(a) for a in seen.args)
    assert str(tmp_path / "repo") not in seen.args  # the location is in the environment too
    assert seen.env["RESTIC_PASSWORD"] == PASSWORD  # not the inherited one
    assert seen.env["RESTIC_REPOSITORY"] == str(tmp_path / "repo")
    assert seen.kwargs["stdin"] == asyncio.subprocess.DEVNULL
    assert PASSWORD not in repr(repo)


def test_a_failed_command_raises_with_restics_last_line() -> None:
    tool = FakeRestic([Result(1, "", "first\nFatal: unable to open repository\n")])
    with pytest.raises(ResticError, match="unable to open repository") as info:
        asyncio.run(tool.run_ok(Repository("x", PASSWORD), "snapshots"))
    assert info.value.code == 1


# ---------------------------------------------------------------- init or open


def test_init_or_open_creates_a_missing_repository() -> None:
    tool = FakeRestic([Result(restic.EXIT_NO_REPOSITORY, "", "no repo"), ok()])
    assert asyncio.run(repository.init_or_open(tool, Repository("x", PASSWORD))) is True
    assert tool.calls == [("cat", "config"), ("init",)]


def test_init_or_open_opens_an_existing_repository_without_touching_it() -> None:
    tool = FakeRestic([ok()])
    assert asyncio.run(repository.init_or_open(tool, Repository("x", PASSWORD))) is False
    assert tool.calls == [("cat", "config")]


def test_init_or_open_never_reinitialises_over_a_wrong_password() -> None:
    tool = FakeRestic([Result(restic.EXIT_WRONG_PASSWORD, "", "wrong password")])
    with pytest.raises(ResticError, match="doesn't open"):
        asyncio.run(repository.init_or_open(tool, Repository("x", PASSWORD)))
    assert tool.calls == [("cat", "config")]


def test_init_or_open_reports_other_failures() -> None:
    tool = FakeRestic([Result(1, "", "Fatal: permission denied")])
    with pytest.raises(ResticError, match="permission denied"):
        asyncio.run(repository.init_or_open(tool, Repository("x", PASSWORD)))


# ---------------------------------------------------------------- paths


def test_check_local_path_accepts_a_folder_outside_the_data_dir(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    target = tmp_path / "usb" / "backups"
    assert repository.check_local_path(str(target), data, [tmp_path]) == target.resolve()


@pytest.mark.parametrize("raw", ["", "   ", "backups", "./backups", "../x", "a\x00b"])
def test_check_local_path_wants_a_full_path(tmp_path: Path, raw: str) -> None:
    with pytest.raises(DestinationError):
        repository.check_local_path(raw, tmp_path, [tmp_path])


def test_check_local_path_refuses_the_data_dir_and_anything_in_it(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    for inside in (data, data / "backups", data / "apps" / "x"):
        with pytest.raises(DestinationError, match="inside Athena's data folder"):
            repository.check_local_path(str(inside), data, [tmp_path])


def test_check_local_path_follows_symlinks_into_the_data_dir(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    link = tmp_path / "shortcut"
    try:
        link.symlink_to(data, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks need privileges on this host")
    with pytest.raises(DestinationError, match="inside Athena's data folder"):
        repository.check_local_path(str(link / "b"), data, [tmp_path])


def test_check_local_path_refuses_a_file_and_a_disk_root(tmp_path: Path) -> None:
    a_file = tmp_path / "file"
    a_file.write_text("x", encoding="utf-8")
    with pytest.raises(DestinationError, match="is a file"):
        repository.check_local_path(str(a_file), tmp_path / "data", [tmp_path])
    with pytest.raises(DestinationError, match="root"):
        repository.check_local_path(
            Path(tmp_path.anchor).as_posix(), tmp_path / "data", [Path(tmp_path.anchor)]
        )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX system folders")
def test_check_local_path_refuses_system_folders(tmp_path: Path) -> None:
    for system in ("/etc", "/usr/local/backups", "/proc/x", "/dev"):
        with pytest.raises(DestinationError, match="system folder"):
            repository.check_local_path(system, tmp_path, [Path(tmp_path.anchor)])


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root can write anywhere")
def test_check_writable_explains_a_read_only_folder(tmp_path: Path) -> None:
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        with pytest.raises(DestinationError, match="can't write"):
            repository.check_writable(ro / "sub", [tmp_path])
    finally:
        ro.chmod(0o700)


def test_check_writable_creates_the_folder_and_leaves_nothing_behind(tmp_path: Path) -> None:
    target = tmp_path / "new" / "deep"
    repository.check_writable(target, [tmp_path])
    assert target.is_dir()
    assert list(target.iterdir()) == []


# ---------------------------------------------------------------- password and kit


def test_generated_passwords_are_strong_and_different() -> None:
    a, b = repository.generate_password(), repository.generate_password()
    assert a != b
    assert len(a) >= 40


def test_a_short_password_is_refused() -> None:
    with pytest.raises(DestinationError, match="at least"):
        repository.check_password("short")
    assert repository.check_password(PASSWORD) == PASSWORD


def test_the_recovery_kit_holds_what_a_dead_host_needs() -> None:
    kit = repository.recovery_kit("USB disk", "/mnt/usb/athena", PASSWORD)
    for needed in ("USB disk", "/mnt/usb/athena", PASSWORD, restic.VERSION, "restic restore"):
        assert needed in kit
    assert repository.kit_filename("USB disk / main") == "athena-recovery-kit-USB-disk---main.txt"


def test_delete_repository_refuses_a_folder_that_is_not_one(tmp_path: Path) -> None:
    (tmp_path / "photos").mkdir()
    (tmp_path / "photos" / "a.jpg").write_bytes(b"x")
    with pytest.raises(DestinationError, match="doesn't look like"):
        repository.delete_repository(tmp_path / "photos")
    assert (tmp_path / "photos" / "a.jpg").exists()


# ---------------------------------------------------------------- settings section


def test_backup_section_defaults_and_validation(tmp_path: Path) -> None:
    sf = SettingsFile(tmp_path)
    section = sf.load().backup
    assert section.paused is False
    assert (section.prune_interval_days, section.check_interval_days) == (7, 30)
    assert section.default_retention.keeps_something()
    sf.path.write_text('{"backup": {"paused": true}}', encoding="utf-8")
    assert SettingsFile(tmp_path).load().backup.paused is True


@pytest.mark.parametrize(
    "bad",
    ['{"backup": {"pause": true}}', '{"backup": {"prune_interval_days": 0}}'],
)
def test_an_invalid_backup_section_refuses_startup(tmp_path: Path, bad: str) -> None:
    (tmp_path / "athena.json").write_text(bad, encoding="utf-8")
    with pytest.raises(SettingsFileError):
        SettingsFile(tmp_path).load()


def test_retention_with_every_count_at_zero_keeps_nothing() -> None:
    from athena.backup.settings import Retention

    assert not Retention(keep_last=0, keep_daily=0, keep_weekly=0, keep_monthly=0).keeps_something()


# ---------------------------------------------------------------- routes


def kit_of(c: TestClient, path: str, name: str = "USB", password: str | None = None) -> dict:
    body: dict = {"name": name, "path": path}
    if password is not None:
        body["password"] = password
    res = c.post("/api/backup/destinations/recovery-kit", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def create(c: TestClient, path: str, name: str = "USB", password: str = PASSWORD, saved=True):  # type: ignore[no-untyped-def]
    return c.post(
        "/api/backup/destinations",
        json={"name": name, "path": path, "password": password, "recovery_kit_saved": saved},
    )


def test_the_backup_capability_is_reported(tmp_path: Path) -> None:
    caps = client_for(tmp_path).get("/api/system/capabilities").json()["capabilities"]
    backup = next(c for c in caps if c["id"] == "backup")
    assert backup["status"] == "ready"
    assert restic.VERSION in backup["detail"]


def test_recovery_kit_generates_a_password_and_creates_nothing(tmp_path: Path) -> None:
    tool = FakeRestic()
    c = client_for(tmp_path, tool)
    kit = kit_of(c, folder(tmp_path))
    assert len(kit["password"]) >= 40
    assert kit["password"] in kit["kit"]
    assert kit["location"] == str((tmp_path / "backups").resolve())
    assert kit["filename"].endswith(".txt")
    assert c.get("/api/backup/destinations").json() == []
    assert tool.calls == []  # nothing was run against a repository


def test_recovery_kit_uses_the_admins_own_password(tmp_path: Path) -> None:
    assert kit_of(client_for(tmp_path), folder(tmp_path), password=PASSWORD)["password"] == PASSWORD


def test_recovery_kit_rejects_a_short_password_and_a_bad_folder(tmp_path: Path) -> None:
    c = client_for(tmp_path)
    short = c.post(
        "/api/backup/destinations/recovery-kit",
        json={"name": "x", "path": folder(tmp_path), "password": "short"},
    )
    assert short.status_code == 400
    assert "at least" in short.json()["detail"]
    relative = c.post(
        "/api/backup/destinations/recovery-kit", json={"name": "x", "path": "relative/dir"}
    )
    assert relative.status_code == 400


def test_create_needs_the_kit_to_be_saved_first(tmp_path: Path) -> None:
    tool = FakeRestic()
    c = client_for(tmp_path, tool)
    res = create(c, folder(tmp_path), saved=False)
    assert res.status_code == 400
    assert "recovery kit" in res.json()["detail"]
    assert tool.calls == []
    assert not (tmp_path / "backups").exists()


def test_create_makes_a_repository_and_keeps_the_password_encrypted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    tool = FakeRestic([Result(restic.EXIT_NO_REPOSITORY, "", ""), ok()])
    c = client_for(tmp_path, tool)
    res = create(c, folder(tmp_path))
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "USB"
    assert body["kind"] == "local"
    assert body["location"] == str((tmp_path / "backups").resolve())
    assert "password" not in body
    assert tool.calls == [("cat", "config"), ("init",)]
    assert tool.repos[0].password == PASSWORD
    # Stored encrypted, and it decrypts with the data dir's key.
    with c.app.state.db.engine.connect() as conn:  # type: ignore[attr-defined]
        stored = conn.exec_driver_sql("SELECT password FROM backup_destinations").scalar()
    assert stored != PASSWORD
    assert PASSWORD not in stored
    assert SecretBox(tmp_path / "data").decrypt(stored) == PASSWORD
    assert PASSWORD not in caplog.text
    actions = [r["action"] for r in c.get("/api/audit").json()]
    assert "backup.destination.create" in actions


def test_create_opens_an_existing_repository(tmp_path: Path) -> None:
    c = client_for(tmp_path, FakeRestic([ok()]))
    assert create(c, folder(tmp_path)).status_code == 201
    entry = next(r for r in c.get("/api/audit").json() if r["action"].startswith("backup."))
    assert entry["target"] == "USB"


def test_create_with_a_wrong_password_for_an_existing_repository_fails(tmp_path: Path) -> None:
    tool = FakeRestic([Result(restic.EXIT_WRONG_PASSWORD, "", "")])
    c = client_for(tmp_path, tool)
    res = create(c, folder(tmp_path))
    assert res.status_code == 400
    assert "doesn't open" in res.json()["detail"]
    assert c.get("/api/backup/destinations").json() == []
    assert tool.calls == [("cat", "config")]  # it never tried to init over it


def test_create_reports_a_failed_restic_download(tmp_path: Path) -> None:
    app = make_app(tmp_path, backup_allowed_roots=[tmp_path])

    class Failing(ResticProvider):
        async def get(self, log_line=None):  # type: ignore[no-untyped-def,override]
            raise DownloadError("Couldn't download restic: offline")

    app.state.restic = Failing(tmp_path)
    c = signed_in(TestClient(app))
    res = create(c, folder(tmp_path))
    assert res.status_code == 502
    assert "offline" in res.json()["detail"]


def test_create_rejects_duplicates(tmp_path: Path) -> None:
    c = client_for(tmp_path, FakeRestic([ok(), ok(), ok()]))
    assert create(c, folder(tmp_path, "a")).status_code == 201
    assert create(c, folder(tmp_path, "b")).status_code == 409  # same name
    assert create(c, folder(tmp_path, "a"), name="Other").status_code == 409  # same folder
    assert create(c, folder(tmp_path, "b"), name="Other").status_code == 201


def test_create_refuses_the_data_dir(tmp_path: Path) -> None:
    c = client_for(tmp_path)
    res = create(c, str(tmp_path / "data" / "backups"))
    assert res.status_code == 400
    assert "data folder" in res.json()["detail"]


def test_the_list_never_returns_a_password(tmp_path: Path) -> None:
    c = client_for(tmp_path, FakeRestic([ok()]))
    create(c, folder(tmp_path))
    text = c.get("/api/backup/destinations").text
    assert PASSWORD not in text
    assert "password" not in text


def test_delete_forgets_the_destination_and_keeps_the_backups(tmp_path: Path) -> None:
    c = client_for(tmp_path, FakeRestic([ok()]))
    dest = create(c, folder(tmp_path)).json()
    repo = Path(dest["location"])
    (repo / "config").write_text("x", encoding="utf-8")
    assert c.delete(f"/api/backup/destinations/{dest['id']}").status_code == 204
    assert c.get("/api/backup/destinations").json() == []
    assert (repo / "config").exists()


def test_delete_can_remove_the_backups_too(tmp_path: Path) -> None:
    c = client_for(tmp_path, FakeRestic([ok()]))
    dest = create(c, folder(tmp_path)).json()
    repo = Path(dest["location"])
    (repo / "keys").mkdir()
    (repo / "data").mkdir()
    (repo / "config").write_text("x", encoding="utf-8")
    res = c.delete(f"/api/backup/destinations/{dest['id']}", params={"delete_backups": True})
    assert res.status_code == 204
    assert not repo.exists()


def test_delete_with_backups_keeps_a_folder_that_is_not_a_repository(tmp_path: Path) -> None:
    c = client_for(tmp_path, FakeRestic([ok()]))
    dest = create(c, folder(tmp_path)).json()
    (Path(dest["location"]) / "holiday.jpg").write_bytes(b"x")
    res = c.delete(f"/api/backup/destinations/{dest['id']}", params={"delete_backups": True})
    assert res.status_code == 400
    assert (Path(dest["location"]) / "holiday.jpg").exists()
    assert len(c.get("/api/backup/destinations").json()) == 1  # still known to Athena


def test_delete_is_refused_while_a_plan_uses_it(tmp_path: Path) -> None:
    c = client_for(tmp_path, FakeRestic([ok()]))
    dest = create(c, folder(tmp_path)).json()
    with c.app.state.db.engine.begin() as conn:  # type: ignore[attr-defined]
        conn.exec_driver_sql(
            "INSERT INTO backup_plans (id, name, destination_id, items, retention, enabled,"
            " created_at) VALUES ('p1', 'Nightly', ?, '{}', '{}', 1, '2026-11-21')",
            (dest["id"],),
        )
    res = c.delete(f"/api/backup/destinations/{dest['id']}")
    assert res.status_code == 409
    assert "Nightly" in res.json()["detail"]
    assert BackupPlan.__tablename__ == "backup_plans"


def test_delete_unknown_destination(tmp_path: Path) -> None:
    assert client_for(tmp_path).delete("/api/backup/destinations/nope").status_code == 404


def test_every_route_is_admin_only_and_needs_a_session(tmp_path: Path) -> None:
    c = client_for(tmp_path, FakeRestic([ok()]))
    dest = create(c, folder(tmp_path)).json()
    with c.app.state.db.engine.begin() as conn:  # type: ignore[attr-defined]
        conn.exec_driver_sql("UPDATE users SET is_admin = 0")
    assert c.get("/api/backup/destinations").status_code == 403
    assert c.post("/api/backup/destinations/recovery-kit", json={}).status_code in (403, 422)
    assert create(c, folder(tmp_path, "x"), name="X").status_code == 403
    assert c.delete(f"/api/backup/destinations/{dest['id']}").status_code == 403
    anonymous = TestClient(make_app(tmp_path / "other"))
    assert anonymous.get("/api/backup/destinations").status_code == 401
    assert BackupDestination.__tablename__ == "backup_destinations"


# ---------------------------------------------------------------- a real restic


def _real_restic() -> Path | None:
    """A restic for these tests only: Athena itself never uses one from PATH."""
    found = os.environ.get("ATHENA_TEST_RESTIC") or shutil.which("restic")
    return Path(found) if found else None


needs_restic = pytest.mark.skipif(_real_restic() is None, reason="restic isn't installed")


@needs_restic
def test_real_restic_creates_then_opens_a_repository(tmp_path: Path) -> None:
    real = _real_restic()
    assert real is not None
    tool = Restic(real, cache_dir=tmp_path / "cache")
    repo = Repository(str(tmp_path / "repo"), PASSWORD)
    assert asyncio.run(repository.init_or_open(tool, repo)) is True
    assert repository.looks_like_repository(tmp_path / "repo")
    assert asyncio.run(repository.init_or_open(tool, repo)) is False
    with pytest.raises(ResticError, match="doesn't open"):
        asyncio.run(
            repository.init_or_open(tool, Repository(str(tmp_path / "repo"), "another password!"))
        )


@needs_restic
def test_real_restic_through_the_routes(tmp_path: Path) -> None:
    real = _real_restic()
    assert real is not None
    app = make_app(tmp_path)
    app.state.restic = ResticProvider(tmp_path / "data", binary=real)
    c = signed_in(TestClient(app))
    dest = create(c, folder(tmp_path)).json()
    repo = Path(dest["location"])
    assert repository.looks_like_repository(repo)
    # Creating it again elsewhere with the same folder opens, not recreates: 409 by location.
    assert create(c, folder(tmp_path), name="Again").status_code == 409
    assert (
        c.delete(
            f"/api/backup/destinations/{dest['id']}", params={"delete_backups": True}
        ).status_code
        == 204
    )
    assert not repo.exists()
