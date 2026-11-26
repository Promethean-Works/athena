"""SMB shares: detection, the Samba service, and the /api/shares/smb API."""

import subprocess
import sys
from pathlib import Path

import pytest
from conftest import make_app, signed_in
from fake_probe import FakeProbe
from fastapi.testclient import TestClient

from athena.db import Database
from athena.db.models import FileLocation
from athena.files import smb
from athena.files.netshare import ShareReloadFailed
from athena.files.paths import BadPath, NotFound
from athena.platform.detect import detect
from athena.platform.probe import Probe

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


def test_macos_as_root_is_ready_with_sharing() -> None:
    c = caps(FakeProbe(os="darwin", binaries={"sharing": "/usr/sbin/sharing"}, root=True))
    assert (c["shares.smb"].status, c["shares.smb"].provider) == ("ready", "sharing")


def test_macos_not_root_needs_privilege() -> None:
    probe = FakeProbe(os="darwin", binaries={"sharing": "/usr/sbin/sharing"})
    assert caps(probe)["shares.smb"].status == "needs_privilege"


def test_windows_as_admin_is_ready_with_smbshare() -> None:
    probe = FakeProbe(os="windows", binaries={"powershell": "C:/ps.exe"}, root=True)
    c = caps(probe)["shares.smb"]
    assert (c.status, c.provider) == ("ready", "smbshare")


def test_windows_not_admin_needs_privilege() -> None:
    probe = FakeProbe(os="windows", binaries={"powershell": "C:/ps.exe"})
    assert caps(probe)["shares.smb"].status == "needs_privilege"


def test_hosts_without_the_tools_are_unsupported() -> None:
    assert caps(FakeProbe(os="windows"))["shares.smb"].status == "unsupported"
    assert caps(FakeProbe(os="darwin"))["shares.smb"].status == "unsupported"  # no `sharing`


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


def test_api_list_and_create_on_unsupported_os(tmp_path: Path) -> None:
    """On this machine (macOS) SMB share creation isn't wired, so it's 501."""
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


def test_failed_reload_rolls_the_config_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse() -> None:
        raise ShareReloadFailed("Couldn't reload Samba: bad config")

    monkeypatch.setattr("athena.files.smb._reload_smbd", refuse)
    conf = tmp_path / "smb.conf"
    conf.write_text("[global]\n", encoding="utf-8")
    db, loc_id = _seed(tmp_path)

    for session in db.session():
        with pytest.raises(ShareReloadFailed):
            smb.create_share(session, loc_id, SHARE_NAME, conf=conf)
        assert smb.list_shares(session) == []
    assert conf.read_text(encoding="utf-8") == "[global]\n"


def test_macos_uses_sharing_to_add_and_remove(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "athena.files.netshare.run_command", lambda argv, action: calls.append(argv)
    )
    db, loc_id = _seed(tmp_path)

    for session in db.session():
        entry = smb.create_share(
            session, loc_id, SHARE_NAME, read_only=True, guest_ok=False, provider="sharing"
        )
        assert calls[-1] == [
            "sharing", "-a", entry.path, "-n", SHARE_NAME, "-S", SHARE_NAME,
            "-s", "001", "-g", "000", "-R", "1",
        ]  # fmt: skip
        smb.remove_share(session, entry.id, provider="sharing")
        assert calls[-1] == ["sharing", "-r", SHARE_NAME]
        assert smb.list_shares(session) == []


def test_macos_failure_is_not_tracked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(argv: list[str], action: str, env: dict[str, str] | None = None) -> None:
        raise ShareReloadFailed(f"Couldn't {action}: nope")

    monkeypatch.setattr("athena.files.netshare.run_command", refuse)
    db, loc_id = _seed(tmp_path)
    for session in db.session():
        with pytest.raises(ShareReloadFailed):
            smb.create_share(session, loc_id, SHARE_NAME, provider="sharing")
        assert smb.list_shares(session) == []


def test_windows_uses_new_smbshare_with_name_and_path_in_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], dict[str, str] | None]] = []
    monkeypatch.setattr(
        "athena.files.netshare.run_command",
        lambda argv, action, env=None: calls.append((argv, env)),
    )
    db, loc_id = _seed(tmp_path)

    for session in db.session():
        entry = smb.create_share(session, loc_id, SHARE_NAME, read_only=True, provider="smbshare")
        argv, env = calls[-1]
        assert argv[:4] == ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"]
        assert "New-SmbShare" in argv[4] and "-ReadAccess Everyone" in argv[4]
        assert entry.path not in argv[4] and SHARE_NAME not in argv[4]
        assert env == {"ATHENA_SHARE_NAME": SHARE_NAME, "ATHENA_SHARE_PATH": entry.path}

        smb.remove_share(session, entry.id, provider="smbshare")
        argv, env = calls[-1]
        assert "Remove-SmbShare" in argv[4] and env == {"ATHENA_SHARE_NAME": SHARE_NAME}
        assert smb.list_shares(session) == []


def test_windows_read_write_gets_full_access_and_guests_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "athena.files.netshare.run_command", lambda argv, action, env=None: calls.append(argv)
    )
    db, loc_id = _seed(tmp_path)
    for session in db.session():
        with pytest.raises(BadPath):
            smb.create_share(session, loc_id, "g", guest_ok=True, provider="smbshare")
        assert calls == []
        smb.create_share(session, loc_id, "rw", provider="smbshare")
        assert "-FullAccess Everyone" in calls[-1][4]


def _is_windows_admin() -> bool:
    return sys.platform == "win32" and Probe().is_admin()


@pytest.mark.skipif(not _is_windows_admin(), reason="needs Windows and an administrator")
def test_real_windows_share_round_trip(tmp_path: Path) -> None:
    """Create, see and remove a real SMB share (CI's Windows runner is an administrator)."""
    name = "athena-test-share"
    db, loc_id = _seed(tmp_path)

    def listed() -> str:
        script = "Get-SmbShare | Select-Object -ExpandProperty Name"
        out = subprocess.run(
            [*smb.POWERSHELL, script], capture_output=True, text=True, timeout=30, check=True
        )
        return out.stdout

    for session in db.session():
        entry = smb.create_share(session, loc_id, name, read_only=True, provider="smbshare")
        try:
            assert name in listed().split()
        finally:
            smb.remove_share(session, entry.id, provider="smbshare")
    assert name not in listed().split()
