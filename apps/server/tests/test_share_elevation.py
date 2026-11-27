"""Creating shares that need root: sudo with a password on macOS, UAC on Windows."""

import base64
import os
import sqlite3
import stat
import sys
from pathlib import Path

import pytest
from conftest import make_app, signed_in
from fake_probe import FakeProbe
from fastapi.testclient import TestClient

from athena.files import netshare
from athena.files.netshare import Elevation, ElevationDenied, ShareReloadFailed
from athena.platform.capabilities import CapabilityManifest
from athena.platform.detect import detect
from athena.platform.store import CapabilityStore

posix = pytest.mark.skipif(sys.platform == "win32", reason="uses shell scripts as fake tools")
PASSWORD = "s3cret-host-pw"


def _tool(folder: Path, name: str, body: str) -> None:
    path = folder / name
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def fake_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A `sudo` that checks the password on stdin, and a `sharing` that logs its arguments."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    _tool(
        bin_dir,
        "sudo",
        f"""read pw
if [ "$pw" != "{PASSWORD}" ]; then echo "Sorry, try again." >&2; exit 1; fi
shift 4
echo "sudo: $*" >> {log}
exec "$@"
""",
    )
    _tool(bin_dir, "sharing", f'echo "sharing $*" >> {log}\n')
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


def _macos_store() -> CapabilityStore:
    probe = FakeProbe(os="darwin", binaries={"sharing": "/usr/sbin/sharing"})
    return CapabilityStore(detector=lambda: detect(probe))


def test_sudo_password_goes_through_stdin(fake_host: Path) -> None:
    with netshare.elevated(Elevation("sudo", PASSWORD)):
        netshare.run_command(["sharing", "-l"], "list")
    assert fake_host.read_text(encoding="utf-8").splitlines() == ["sudo: sharing -l", "sharing -l"]


@posix
def test_wrong_password_is_denied_and_never_echoed(fake_host: Path) -> None:
    with netshare.elevated(Elevation("sudo", "wrong-pw")), pytest.raises(ElevationDenied) as info:
        netshare.run_command(["sharing", "-l"], "list")
    assert "wrong-pw" not in info.value.message
    assert not fake_host.exists()


@posix
def test_failed_command_error_hides_the_password(tmp_path: Path, monkeypatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _tool(bin_dir, "sudo", f'read pw\necho "boom {PASSWORD}" >&2\nexit 2\n')
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    with netshare.elevated(Elevation("sudo", PASSWORD)), pytest.raises(ShareReloadFailed) as info:
        netshare.run_command(["sharing", "-l"], "list")
    assert PASSWORD not in info.value.message


def test_elevation_repr_hides_the_password() -> None:
    assert PASSWORD not in repr(Elevation("sudo", PASSWORD))


def test_uac_command_carries_values_as_base64_not_script() -> None:
    nasty = "C:\\Shares\\a'; Remove-Item -Recurse C:\\ #"
    argv = [*["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"], "Do-Thing"]
    out = netshare.uac_argv(argv, {"ATHENA_SHARE_PATH": nasty}, "C:\\err.txt")
    assert out[:3] == ["powershell.exe", "-NoProfile", "-NonInteractive"]
    outer = base64.b64decode(out[-1]).decode("utf-16-le")
    assert "-Verb RunAs" in outer
    inner = base64.b64decode(outer.split("'-EncodedCommand','")[1].split("'")[0]).decode(
        "utf-16-le"
    )
    assert "Do-Thing" in inner
    assert "Remove-Item" not in inner and nasty not in inner
    assert base64.b64encode(nasty.encode()).decode() in inner


@posix
def test_api_asks_for_a_password_then_creates_the_share(fake_host: Path, tmp_path: Path) -> None:
    (tmp_path / "media").mkdir()
    with TestClient(make_app(tmp_path, store=_macos_store())) as client:
        signed_in(client)
        caps = CapabilityManifest.model_validate(client.get("/api/system/capabilities").json())
        smb = caps.get("shares.smb")
        assert smb is not None and (smb.status, smb.elevation) == ("needs_privilege", "password")
        loc = client.post(
            "/api/files/locations", json={"name": "Media", "path": str(tmp_path / "media")}
        ).json()["id"]
        body = {"location": loc, "name": "media"}

        res = client.post("/api/shares/smb", json=body)
        assert res.status_code == 403 and "password" in res.json()["detail"]

        res = client.post("/api/shares/smb", json=body, headers={"X-Host-Password": "nope"})
        assert res.status_code == 403 and "nope" not in res.text
        assert client.get("/api/shares/smb").json() == []

        res = client.post("/api/shares/smb", json=body, headers={"X-Host-Password": PASSWORD})
        assert res.status_code == 201, res.text
        assert PASSWORD not in res.text
        calls = fake_host.read_text(encoding="utf-8")
        assert "sharing -a" in calls and PASSWORD not in calls

        share_id = res.json()["id"]
        res = client.delete(f"/api/shares/smb/{share_id}")
        assert res.status_code == 403
        res = client.delete(f"/api/shares/smb/{share_id}", headers={"X-Host-Password": PASSWORD})
        assert res.status_code == 204, res.text
        assert "sharing -r media" in fake_host.read_text(encoding="utf-8")
        rows = sqlite3.connect(tmp_path / "data" / "athena.db").execute(
            "select action, target, detail from audit_log"
        )
        assert PASSWORD not in repr(rows.fetchall())
