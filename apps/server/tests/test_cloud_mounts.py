"""Cloud folders mounted for sharing: detection, the mount lifecycle and /api/cloud/mounts."""

import asyncio
import functools
from pathlib import Path
from typing import Any

import pytest
from conftest import signed_in
from fake_probe import FakeProbe
from fastapi.testclient import TestClient
from sqlmodel import select

from athena.cloud import mounts
from athena.cloud.rclone import Rclone, RcloneError
from athena.config import Settings
from athena.db import Database
from athena.db.models import FileLocation, RemoteMount, SmbShare
from athena.main import create_app
from athena.platform.detect import detect
from athena.platform.store import CapabilityStore


def sync(fn):
    """Run an async test to completion (there's no async plugin)."""

    @functools.wraps(fn)
    def run(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    return run


def cap(probe: FakeProbe):
    return next(c for c in detect(probe).capabilities if c.id == "cloud.mount")


# ---------------------------------------------------------------- detection


def test_no_rclone_is_missing() -> None:
    assert cap(FakeProbe(os="linux")).status == "missing"


def test_linux_needs_fuse() -> None:
    rclone = {"rclone": "/usr/bin/rclone"}
    assert cap(FakeProbe(os="linux", binaries=rclone)).status == "missing"
    ready = cap(FakeProbe(os="linux", binaries={**rclone, "fusermount3": "/bin/fusermount3"}))
    assert (ready.status, ready.provider) == ("ready", "fuse")


def test_macos_homebrew_rclone_cannot_mount() -> None:
    probe = FakeProbe(os="darwin", binaries={"rclone": "/opt/homebrew/bin/rclone"})
    c = cap(probe)
    assert c.status == "unsupported" and "rclone.org/downloads" in (c.detail or "")


def test_macos_official_rclone_needs_macfuse_or_fuse_t() -> None:
    binaries = {"rclone": "/usr/local/bin/rclone"}
    assert cap(FakeProbe(os="darwin", binaries=binaries)).status == "missing"
    probe = FakeProbe(os="darwin", binaries=binaries, paths={"/Library/Filesystems/fuse-t.fs"})
    assert cap(probe).status == "ready"


def test_windows_needs_winfsp() -> None:
    binaries = {"rclone": "C:/rclone.exe"}
    assert cap(FakeProbe(os="windows", binaries=binaries)).status == "missing"
    probe = FakeProbe(os="windows", binaries=binaries, paths={"C:/Program Files/WinFsp"})
    assert cap(probe).provider == "winfsp"


# ---------------------------------------------------------------- lifecycle


class FakeMountRclone(Rclone):
    def __init__(self, data_dir: Path) -> None:
        super().__init__(data_dir, binary=lambda: None)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.mounted: set[str] = set()
        self.fail_mount = False

    async def call(self, method: str, params: dict[str, Any] | None = None, timeout=0) -> Any:
        params = params or {}
        self.calls.append((method, params))
        if method == "mount/mount":
            if self.fail_mount:
                raise RcloneError(500, "FUSE isn't available")
            self.mounted.add(params["mountPoint"])
        elif method == "mount/unmount":
            self.mounted.discard(params["mountPoint"])
        elif method == "mount/listmounts":
            return {"mountPoints": [{"MountPoint": m} for m in self.mounted]}
        return {}


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "athena.db")
    database.migrate()
    return database


@sync
async def test_ensure_mounts_once_and_hides_a_location(tmp_path: Path, db: Database) -> None:
    rclone = FakeMountRclone(tmp_path)
    for session in db.session():
        first = await mounts.ensure(session, rclone, tmp_path, "box", "Photos", read_only=True)
        again = await mounts.ensure(session, rclone, tmp_path, "box", "Photos", read_only=True)
        assert again.id == first.id
        mount_calls = [c for c in rclone.calls if c[0] == "mount/mount"]
        assert len(mount_calls) == 1
        args = mount_calls[0][1]
        assert args["fs"] == "box:Photos"
        assert args["vfsOpt"]["ReadOnly"] is True
        assert Path(first.mount_point).is_dir()
        loc = session.get(FileLocation, first.location_id)
        assert loc is not None and loc.path == str(Path(first.mount_point).resolve())
        assert first.location_id in mounts.hidden_location_ids(session)


@sync
async def test_failed_mount_leaves_nothing_behind(tmp_path: Path, db: Database) -> None:
    rclone = FakeMountRclone(tmp_path)
    rclone.fail_mount = True
    for session in db.session():
        with pytest.raises(mounts.MountFailed):
            await mounts.ensure(session, rclone, tmp_path, "box", "", read_only=True)
        assert mounts.list_mounts(session) == []
        assert session.exec(select(FileLocation)).all() == []
        assert not (tmp_path / "mounts" / "1").exists()


@sync
async def test_release_unmounts_only_when_no_share_is_left(tmp_path: Path, db: Database) -> None:
    rclone = FakeMountRclone(tmp_path)
    for session in db.session():
        mount = await mounts.ensure(session, rclone, tmp_path, "box", "", read_only=True)
        point = mount.mount_point
        location_id = mount.location_id
        share = SmbShare(location_id=location_id, name="box", path=point)
        session.add(share)
        session.commit()
        await mounts.release_if_unused(session, rclone, location_id)
        assert point in rclone.mounted  # a share still uses it

        session.delete(share)
        session.commit()
        await mounts.release_if_unused(session, rclone, location_id)
        assert point not in rclone.mounted
        assert mounts.list_mounts(session) == []
        assert session.get(FileLocation, location_id) is None


@sync
async def test_restore_mounts_saved_folders_again(tmp_path: Path, db: Database) -> None:
    rclone = FakeMountRclone(tmp_path)
    for session in db.session():
        mount = await mounts.ensure(session, rclone, tmp_path, "box", "", read_only=False)
        rclone.mounted.clear()  # a restart drops the mount
        await mounts.restore(session, rclone)
        assert mount.mount_point in rclone.mounted
        assert any(c[1].get("vfsOpt", {}).get("ReadOnly") is False for c in rclone.calls)


# ---------------------------------------------------------------- API


def _app(tmp_path: Path, rclone: Rclone, ready: bool):
    binaries = {"rclone": "/usr/bin/rclone"}
    if ready:
        binaries["fusermount3"] = "/bin/fusermount3"
    probe = FakeProbe(os="linux", binaries=binaries)
    store = CapabilityStore(detector=lambda: detect(probe))
    settings = Settings(data_dir=tmp_path / "data", web_dir=tmp_path / "no-web")
    return create_app(settings, capability_store=store, rclone=rclone)


def test_api_mount_list_and_unmount(tmp_path: Path) -> None:
    rclone = FakeMountRclone(tmp_path)
    with TestClient(_app(tmp_path, rclone, ready=True)) as client:
        signed_in(client)
        res = client.post("/api/cloud/mounts", json={"remote": "box", "path": "Docs"})
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["read_only"] is True and body["path"] == "Docs"
        assert [m["id"] for m in client.get("/api/cloud/mounts").json()] == [body["id"]]
        # the mount point is not offered as a folder in the file manager
        names = [loc["name"] for loc in client.get("/api/files/locations").json()]
        assert not any(n.startswith("Cloud:") for n in names)

        assert client.post("/api/cloud/mounts", json={"remote": "../x"}).status_code == 400
        assert client.delete(f"/api/cloud/mounts/{body['id']}").status_code == 204
        assert client.get("/api/cloud/mounts").json() == []
        assert client.delete("/api/cloud/mounts/99").status_code == 404


def test_api_says_why_it_cannot_mount(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, FakeMountRclone(tmp_path), ready=False)) as client:
        signed_in(client)
        res = client.post("/api/cloud/mounts", json={"remote": "box"})
        assert res.status_code == 501 and "FUSE" in res.json()["detail"]


def test_models_and_migrations_agree_for_remote_mounts(db: Database) -> None:
    assert RemoteMount.__tablename__ == "remote_mounts"
