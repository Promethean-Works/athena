"""NFS shares: detection, the exports file, and the /api/shares/nfs API."""

import os
from pathlib import Path

import pytest
from conftest import make_app, signed_in
from fake_probe import FakeProbe
from fastapi.testclient import TestClient

from athena.db import Database
from athena.db.models import FileLocation, NfsShare
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


def test_macos_as_root_is_ready_with_nfsd() -> None:
    c = caps(FakeProbe(os="darwin", binaries={"nfsd": "/sbin/nfsd"}, root=True))["shares.nfs"]
    assert (c.status, c.provider) == ("ready", "nfsd")


def test_macos_not_root_needs_privilege() -> None:
    probe = FakeProbe(os="darwin", binaries={"nfsd": "/sbin/nfsd"})
    assert caps(probe)["shares.nfs"].status == "needs_privilege"


def test_windows_is_unsupported() -> None:
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


# ---------------------------------------------------------------- macOS


def _macos_share(path: str, clients: str, read_only: bool = False) -> NfsShare:
    return NfsShare(location_id=1, path=path, clients=clients, read_only=read_only)


def test_macos_block_has_a_line_per_host_list_and_network() -> None:
    real = os.path.realpath
    block = nfs.render_macos_block(
        [
            _macos_share("/Volumes/My Disk", "10.0.0.5,nas.local,192.168.1.0/24,[fd00::]/64", True),
        ]
    )
    path = real("/Volumes/My Disk").replace(" ", "\\ ")
    assert block == (
        nfs.BEGIN
        + f"{path} -ro 10.0.0.5 nas.local\n"
        + f"{path} -ro -network 192.168.1.0 -mask 255.255.255.0\n"
        + f"{path} -ro -network fd00:: -mask ffff:ffff:ffff:ffff::\n"
        + nfs.END
    )


def test_merge_block_keeps_the_admins_own_lines() -> None:
    mine = "/Users/me/own -network 10.0.0.0 -mask 255.0.0.0\n"
    block = nfs.render_macos_block([_macos_share("/tmp/a", "10.0.0.1")])
    once = nfs.merge_block(mine, block)
    assert once.startswith(mine) and nfs.BEGIN in once
    again = nfs.merge_block(once, nfs.render_macos_block([_macos_share("/tmp/b", "10.0.0.2")]))
    assert again.count(nfs.BEGIN) == 1 and "/tmp/a" not in again and again.startswith(mine)
    assert nfs.merge_block(again, "") == mine
    assert nfs.merge_block(None, "") == ""


def test_macos_flavor_merges_into_existing_exports_and_rolls_back(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    exports.write_text("/keep -ro 10.9.9.9\n", encoding="utf-8")
    db, loc_id = _seed(tmp_path)
    for session in db.session():
        entry = nfs.create_share(
            session, loc_id, ["10.0.0.1"], flavor=nfs.MACOS, exports=exports, reload=_noop
        )
        text = exports.read_text(encoding="utf-8")
        assert text.startswith("/keep -ro 10.9.9.9\n") and nfs.BEGIN in text
        nfs.remove_share(session, entry.id, flavor=nfs.MACOS, exports=exports, reload=_noop)
    assert exports.read_text(encoding="utf-8") == "/keep -ro 10.9.9.9\n"


def test_macos_refuses_quotes_in_the_path(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    db, _ = _seed(tmp_path)
    for session in db.session():
        quoted = tmp_path / "it's"
        quoted.mkdir()
        loc = FileLocation(name="Quoted", path=str(quoted))
        session.add(loc)
        session.commit()
        session.refresh(loc)
        with pytest.raises(BadPath):
            nfs.create_share(
                session, loc.id, ["10.0.0.1"], flavor=nfs.MACOS, exports=exports, reload=_noop
            )
