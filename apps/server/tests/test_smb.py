"""SMB shares: detection, the Samba service, and the /api/shares/smb API."""

from pathlib import Path

import pytest
from conftest import make_app, signed_in
from fake_probe import FakeProbe
from fastapi.testclient import TestClient

from athena.db import Database
from athena.db.models import FileLocation
from athena.files import smb
from athena.files.paths import BadPath, NotFound
from athena.platform.detect import detect

SHARE_NAME = "photos"


# ---------------------------------------------------------------- detection


def caps(probe: FakeProbe) -> dict[str, object]:
    return {c.id: c for c in detect(probe).capabilities}


def test_linux_samba_installed_is_ready() -> None:
    c = caps(FakeProbe(binaries={"smbd": "/usr/sbin/smbd"}))["shares.smb"]
    assert (c.status, c.provider, c.available) == ("ready", "samba", True)


def test_linux_without_samba_is_missing_with_setup() -> None:
    c = caps(FakeProbe())["shares.smb"]
    assert (c.status, c.actions, c.available) == ("missing", ["setup"], False)
    assert "apt install samba" in c.detail


def test_macos_and_windows_are_unsupported() -> None:
    assert caps(FakeProbe(os="darwin"))["shares.smb"].status == "unsupported"
    assert caps(FakeProbe(os="windows"))["shares.smb"].status == "unsupported"


# ---------------------------------------------------------------- service


def _seed(tmp_path: Path) -> tuple[Database, int]:
    """A fresh migrated database with one location; returns the db and its id."""
    db = Database(tmp_path / "athena.db")
    db.migrate()
    for session in db.session():
        media = tmp_path / "media"
        media.mkdir()
        loc = FileLocation(name="Media", path=str(media))
        session.add(loc)
        session.commit()
        session.refresh(loc)
        return db, loc.id
    raise AssertionError("no session")


def _linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("athena.files.smb._on_linux", lambda: True)
    monkeypatch.setattr("athena.files.smb._reload_smbd", lambda: None)


def test_create_list_and_remove_smb_share(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _linux(monkeypatch)
    conf = tmp_path / "smb.conf"
    db, loc_id = _seed(tmp_path)

    for session in db.session():
        entry = smb.create_share(session, loc_id, SHARE_NAME, conf=conf)
        assert entry.name == SHARE_NAME
        assert entry.read_only is False and entry.guest_ok is False

        text = conf.read_text(encoding="utf-8")
        assert f"[{SHARE_NAME}]" in text
        assert f"   path = {entry.path}" in text
        assert "   read only = no" in text
        assert "   guest ok = no" in text

        shares = smb.list_shares(session)
        assert [s.name for s in shares] == [SHARE_NAME]
        assert shares[0].location_name == "Media"

        smb.remove_share(session, entry.id, conf=conf)

    assert f"[{SHARE_NAME}]" not in conf.read_text()
    for session in db.session():
        assert smb.list_shares(session) == []


def test_create_share_honors_read_only_and_guest_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _linux(monkeypatch)
    conf = tmp_path / "smb.conf"
    db, loc_id = _seed(tmp_path)

    for session in db.session():
        smb.create_share(session, loc_id, "ro", read_only=True, guest_ok=True, conf=conf)

    text = conf.read_text(encoding="utf-8")
    assert "   read only = yes" in text
    assert "   guest ok = yes" in text


def test_duplicate_share_name_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _linux(monkeypatch)
    conf = tmp_path / "smb.conf"
    db, loc_id = _seed(tmp_path)

    for session in db.session():
        smb.create_share(session, loc_id, SHARE_NAME, conf=conf)
        with pytest.raises(Exception) as exc:
            smb.create_share(session, loc_id, SHARE_NAME, conf=conf)
        assert "already exists" in str(exc.value)


def test_remove_unknown_share_is_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _linux(monkeypatch)
    db, _ = _seed(tmp_path)

    for session in db.session():
        with pytest.raises(Exception) as exc:
            smb.remove_share(session, 12345)
        assert isinstance(exc.value, NotFound)


def test_invalid_share_name_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _linux(monkeypatch)
    conf = tmp_path / "smb.conf"
    db, loc_id = _seed(tmp_path)

    for session in db.session():
        with pytest.raises(BadPath):
            smb.create_share(session, loc_id, "-bad name", conf=conf)


# ---------------------------------------------------------------- API


def test_api_list_and_create_on_unsupported_os(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On this machine (macOS) SMB share creation isn't wired, so it's 501."""
    # Pretend we're not on Linux: _on_linux() reads sys.platform (the real host),
    # which would be Linux on CI and would try to write /etc/samba/smb.conf.
    monkeypatch.setattr("athena.files.smb._on_linux", lambda: False)
    with TestClient(make_app(tmp_path)) as client:
        signed_in(client)
        (tmp_path / "media").mkdir()
        res = client.post(
            "/api/files/locations",
            json={"name": "Media", "path": str(tmp_path / "media")},
        )
        assert res.status_code == 201, res.text
        location = res.json()["id"]

        assert client.get("/api/shares/smb").json() == []

        res = client.post(
            "/api/shares/smb",
            json={"location": location, "name": SHARE_NAME},
        )
        assert res.status_code == 501, res.text

        res = client.delete("/api/shares/smb/1")
        assert res.status_code == 404, res.text
