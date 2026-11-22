"""Auto-start service files: the token lives in a 0600 file, never in the unit/plist/argv."""

import asyncio
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from athena.tunnel import cloudflare, ngrok, servicefiles
from athena.tunnel.cloudflare import CloudflareTunnelProvider
from athena.tunnel.ngrok import NgrokTunnelProvider

SECRET = "tok-s3cret-123"


class _Job:
    def __init__(self) -> None:
        self.lines: list[str] = []

    async def log(self, line: str) -> None:
        self.lines.append(line)


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Fake host: secrets dir and home under tmp_path, subprocess.run recorded."""
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    monkeypatch.setattr(servicefiles, "private_dir", lambda: secrets)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(ngrok, "find_binary", lambda name: f"/bin/{name}")
    monkeypatch.setattr(cloudflare, "find_binary", lambda name: f"/bin/{name}")
    calls: list[list[str]] = []
    monkeypatch.setattr(ngrok.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(cloudflare.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    return {"secrets": secrets, "home": tmp_path, "calls": calls, "mp": monkeypatch}


def _system(host: dict[str, Any], name: str) -> None:
    host["mp"].setattr("platform.system", lambda: name)


def _plist(host: dict[str, Any], label: str) -> str:
    path = host["home"] / "Library" / "LaunchAgents" / f"com.athena.tunnel.{label}.plist"
    return path.read_text()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_write_private_is_0600_even_over_a_loose_file(tmp_path: Path) -> None:
    path = tmp_path / "t"
    path.write_text("old")
    path.chmod(0o644)
    servicefiles.write_private(path, "new")
    assert path.read_text() == "new"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_ngrok_launchd_uses_a_private_config_not_a_placeholder(host: dict[str, Any]) -> None:
    _system(host, "Darwin")
    job = _Job()
    asyncio.run(NgrokTunnelProvider().configure_service(job, True, 9000, {"auth_token": SECRET}))
    config = host["secrets"] / "ngrok.yml"
    assert SECRET in config.read_text()
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    plist = _plist(host, "ngrok")
    assert "${" not in plist
    assert SECRET not in plist
    assert f"<string>{config}</string>" in plist
    assert "<string>9000</string>" in plist
    assert not any(SECRET in line for line in job.lines)


def test_ngrok_systemd_unit_has_no_token(host: dict[str, Any], monkeypatch) -> None:
    _system(host, "Linux")
    written: dict[Path, str] = {}
    monkeypatch.setattr(Path, "write_text", lambda self, text, **kw: written.update({self: text}))
    asyncio.run(NgrokTunnelProvider().configure_service(_Job(), True, 8420, {"auth_token": SECRET}))
    unit = written[Path("/etc/systemd/system/ngrok.service")]
    assert "${" not in unit
    assert SECRET not in unit
    assert f"ExecStart=/bin/ngrok http 8420 --config {host['secrets'] / 'ngrok.yml'}" in unit
    assert ["systemctl", "enable", "ngrok"] in host["calls"]


def test_ngrok_service_needs_a_token(host: dict[str, Any]) -> None:
    _system(host, "Darwin")
    with pytest.raises(ValueError, match="auth token"):
        asyncio.run(NgrokTunnelProvider().configure_service(_Job(), True, 8420, {}))
    assert host["calls"] == []
    assert not (host["secrets"] / "ngrok.yml").exists()


def test_ngrok_windows_task_points_at_the_config(host: dict[str, Any]) -> None:
    _system(host, "Windows")
    asyncio.run(NgrokTunnelProvider().configure_service(_Job(), True, 8420, {"auth_token": SECRET}))
    cmd = host["calls"][0]
    assert cmd[:2] == ["schtasks", "/Create"]
    tr = cmd[cmd.index("/TR") + 1]
    assert "--config" in tr
    assert SECRET not in tr
    assert "${" not in tr


def test_ngrok_disable_removes_the_token_file(host: dict[str, Any]) -> None:
    _system(host, "Darwin")
    asyncio.run(NgrokTunnelProvider().configure_service(_Job(), True, 8420, {"auth_token": SECRET}))
    asyncio.run(NgrokTunnelProvider().configure_service(_Job(), False, 8420, {}))
    assert not (host["secrets"] / "ngrok.yml").exists()
    assert host["calls"][-1][:2] == ["launchctl", "unload"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_cloudflared_named_tunnel_service_uses_a_private_token_file(host: dict[str, Any]) -> None:
    _system(host, "Darwin")
    config = {"quick_tunnel": False, "tunnel_name": "home", "api_token": SECRET}
    asyncio.run(CloudflareTunnelProvider().configure_service(_Job(), True, 8420, config))
    token = host["secrets"] / "cloudflared.token"
    assert token.read_text() == SECRET
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
    plist = _plist(host, "cloudflare")
    assert "/etc/cloudflared" not in plist
    assert SECRET not in plist
    assert "<string>--token-file</string>" in plist
    assert f"<string>{token}</string>" in plist


def test_cloudflared_refuses_a_quick_tunnel_service(host: dict[str, Any]) -> None:
    _system(host, "Linux")
    for config in ({"quick_tunnel": True}, {"quick_tunnel": False, "tunnel_name": "x"}):
        with pytest.raises(ValueError, match="named tunnel"):
            asyncio.run(CloudflareTunnelProvider().configure_service(_Job(), True, 8420, config))
    assert host["calls"] == []
    assert list(host["secrets"].iterdir()) == []


def test_cloudflared_systemd_unit_has_no_missing_config(
    host: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _system(host, "Linux")
    written: dict[Path, str] = {}
    monkeypatch.setattr(Path, "write_text", lambda self, text, **kw: written.update({self: text}))
    config = {"quick_tunnel": False, "tunnel_name": "home", "api_token": SECRET}
    asyncio.run(CloudflareTunnelProvider().configure_service(_Job(), True, 8420, config))
    unit = written[Path("/etc/systemd/system/cloudflared.service")]
    assert "/etc/cloudflared" not in unit
    assert SECRET not in unit
    assert "run --token-file" in unit
