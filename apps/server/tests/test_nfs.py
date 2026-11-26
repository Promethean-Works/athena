"""NFS shares: detection, the exports file, and the /api/shares/nfs API."""

from pathlib import Path

import pytest
from conftest import make_app, signed_in
from fake_probe import FakeProbe
from fastapi.testclient import TestClient

from athena.db import Database
from athena.db.models import FileLocation
from athena.files import nfs
from athena.files.netshare import ShareReloadFailed
from athena.files.paths import BadPath, NotFound
from athena.platform.detect import detect

# ---------------------------------------------------------------- detection


def caps(probe: FakeProbe) -> dict[str, object]:
    return {c.id: c for c in detect(probe).capabilities}


def test_linux_with_exportfs_as_root_is_ready() -> None:
    c = caps(FakeProbe(binaries={"exportfs": "/usr/sbin/exportfs"}, root=True))["shares.nfs"]
    assert (c.status, c.available) == ("ready", True)


def test_linux_not_root_needs_privilege() -> None:
    c = caps(FakeProbe(binaries={"exportfs": "/usr/sbin/exportfs"}))["shares.nfs"]
    assert (c.status, c.available) == ("needs_privilege", False)


def test_linux_without_nfs_server_is_missing_with_setup() -> None:
    c = caps(FakeProbe())["shares.nfs"]
    assert (c.status, c.actions) == ("missing", ["setup"])
    assert "nfs-kernel-server" in c.detail


def test_macos_and_windows_are_unsupported() -> None:
    assert caps(FakeProbe(os="darwin"))["shares.nfs"].status == "unsupported"
    windows = caps(FakeProbe(os="windows"))["shares.nfs"]
    assert windows.status == "unsupported" and "Windows Server" in windows.detail


# ---------------------------------------------------------------- clients


def test_clients_are_validated_and_normalised() -> None:
    assert nfs.clean_clients(
        ["192.168.1.7", "10.0.0.5/24", "NAS.local", "fd00::1", "fd00::/64"]
    ) == [
        "192.168.1.7",
        "10.0.0.0/24",
        "nas.local",
        "[fd00::1]",
        "[fd00::]/64",
    ]


@pytest.mark.parametrize("bad", [[], [" "], ["*"], ["a b"], ["host(rw)"], ["x" * 300], ["-bad"]])
def test_bad_clients_are_refused(bad: list[str]) -> None:
    with pytest.raises(BadPath):
        nfs.clean_clients(bad)


# ---------------------------------------------------------------- service


def _seed(tmp_path: Path, folder: str = "media") -> tuple[Database, int]:
    db = Database(tmp_path / "athena.db")
    db.migrate()
    for session in db.session():
        media = tmp_path / folder
        media.mkdir()
        loc = FileLocation(name="Media", path=str(media))
        session.add(loc)
        session.commit()
        session.refresh(loc)
        return db, loc.id
    raise AssertionError("no session")


def _noop() -> None:
    return None


def test_create_list_and_remove_nfs_share(tmp_path: Path) -> None:
    exports = tmp_path / "exports.d" / "athena.exports"
    db, loc_id = _seed(tmp_path)

    for session in db.session():
        entry = nfs.create_share(session, loc_id, ["192.168.1.0/24"], exports=exports, reload=_noop)
        text = exports.read_text(encoding="utf-8")
        assert f"{entry.path} 192.168.1.0/24(rw,sync,no_subtree_check)\n" in text
        assert [s.id for s in nfs.list_shares(session)] == [entry.id]

        nfs.remove_share(session, entry.id, exports=exports, reload=_noop)
        assert nfs.list_shares(session) == []
    assert exports.read_text(encoding="utf-8") == nfs.HEADER


def test_read_only_and_several_clients(tmp_path: Path) -> None:
    exports = tmp_path / "athena.exports"
    db, loc_id = _seed(tmp_path)
    for session in db.session():
        nfs.create_share(
            session,
            loc_id,
            ["10.0.0.1", "nas.local"],
            read_only=True,
            exports=exports,
            reload=_noop,
        )
    line = exports.read_text(encoding="utf-8").splitlines()[1]
    assert line.endswith("10.0.0.1(ro,sync,no_subtree_check) nas.local(ro,sync,no_subtree_check)")


def test_spaces_in_the_path_are_escaped(tmp_path: Path) -> None:
    exports = tmp_path / "athena.exports"
    db, loc_id = _seed(tmp_path, "my media")
    for session in db.session():
        nfs.create_share(session, loc_id, ["10.0.0.1"], exports=exports, reload=_noop)
    line = exports.read_text(encoding="utf-8").splitlines()[1]
    assert "my\\040media 10.0.0.1(" in line


def test_same_location_twice_is_refused(tmp_path: Path) -> None:
    exports = tmp_path / "athena.exports"
    db, loc_id = _seed(tmp_path)
    for session in db.session():
        nfs.create_share(session, loc_id, ["10.0.0.1"], exports=exports, reload=_noop)
        with pytest.raises(nfs.AlreadyExported):
            nfs.create_share(session, loc_id, ["10.0.0.2"], exports=exports, reload=_noop)


def test_remove_unknown_share_is_not_found(tmp_path: Path) -> None:
    db, _ = _seed(tmp_path)
    for session in db.session():
        with pytest.raises(NotFound):
            nfs.remove_share(session, 999, exports=tmp_path / "x", reload=_noop)


def test_failed_reload_rolls_back_file_and_table(tmp_path: Path) -> None:
    def refuse() -> None:
        raise ShareReloadFailed("Couldn't reload the NFS exports: nope")

    exports = tmp_path / "athena.exports"
    db, loc_id = _seed(tmp_path)
    for session in db.session():
        with pytest.raises(ShareReloadFailed):
            nfs.create_share(session, loc_id, ["10.0.0.1"], exports=exports, reload=refuse)
        assert nfs.list_shares(session) == []
    assert not exports.exists()


# ---------------------------------------------------------------- API


def test_api_on_unsupported_host(tmp_path: Path) -> None:
    """The test app is a fake macOS host: listing works, writing is 501."""
    with TestClient(make_app(tmp_path)) as client:
        signed_in(client)
        (tmp_path / "media").mkdir()
        res = client.post(
            "/api/files/locations", json={"name": "Media", "path": str(tmp_path / "media")}
        )
        location = res.json()["id"]

        assert client.get("/api/shares/nfs").json() == []
        res = client.post("/api/shares/nfs", json={"location": location, "clients": ["10.0.0.1"]})
        assert res.status_code == 501, res.text
        assert client.delete("/api/shares/nfs/1").status_code == 404
