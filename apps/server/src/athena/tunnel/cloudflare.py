"""Cloudflare Tunnel provider implementation."""

import asyncio
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from athena.tunnel import servicefiles
from athena.tunnel.base import TunnelConfig, TunnelProvider, TunnelStatus
from athena.tunnel.process import TunnelProcess, find_binary

log = logging.getLogger(__name__)

_ARCH_ALIASES = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "armv7l": "arm",
    "armv6l": "arm",
    "i386": "386",
    "i686": "386",
    "x86": "386",
}


def release_asset(system: str, machine: str) -> str:
    """Name of the cloudflared release asset for this OS and CPU.

    Linux and Windows releases are bare binaries; only macOS ships a .tgz.
    Windows has no arm64 build, so Windows on ARM runs the amd64 one
    under emulation.
    """
    arch = _ARCH_ALIASES.get(machine.lower())
    system = system.lower()
    if system == "linux" and arch in ("amd64", "arm64", "arm", "386"):
        return f"cloudflared-linux-{arch}"
    if system == "darwin" and arch in ("amd64", "arm64"):
        return f"cloudflared-darwin-{arch}.tgz"
    if system == "windows" and arch in ("amd64", "arm64", "386"):
        return f"cloudflared-windows-{'amd64' if arch == 'arm64' else arch}.exe"
    raise ValueError(f"cloudflared has no release for {system} on {machine}")


_QUICK_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
_CONNECTED = re.compile(r"Registered tunnel connection")
_START_TIMEOUT = 60.0


def _cloudflared_running() -> bool:
    """Whether any `cloudflared tunnel` process runs (e.g. from the auto-start service)."""
    if sys.platform == "win32":
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq cloudflared.exe", "/NH"],
            capture_output=True,
            text=True,
        )
        return "cloudflared.exe" in result.stdout
    result = subprocess.run(["pgrep", "-f", "cloudflared tunnel"], capture_output=True)
    return result.returncode == 0


class CloudflareTunnelProvider(TunnelProvider):
    """Cloudflare Tunnel provider supporting both named and quick tunnels."""

    @property
    def capability_id(self) -> str:
        return "tunnel.cloudflare"

    @property
    def label(self) -> str:
        return "Cloudflare Tunnel"

    def __init__(self) -> None:
        self._process: TunnelProcess | None = None
        self._url: str | None = None

    async def start(self, job: Any, config: TunnelConfig) -> str:
        """Run cloudflared and wait until it reports its public URL. Returns the URL.

        A quick tunnel (`--url`) needs no account and prints a random
        trycloudflare.com URL. A named tunnel runs with the tunnel token from the
        Cloudflare dashboard (passed in `TUNNEL_TOKEN`, not argv, so `ps` can't see
        it); its routes are set up in the dashboard, so the URL is the configured
        domain.
        """
        if self._process is not None and self._process.alive:
            raise RuntimeError("The tunnel is already running; stop it first")
        provider_config = config.provider_config or {}
        quick_tunnel = provider_config.get("quick_tunnel", True)
        tunnel_name = provider_config.get("tunnel_name")
        domain = provider_config.get("domain")
        api_token = provider_config.get("api_token")

        binary = find_binary("cloudflared")
        if binary is None:
            raise RuntimeError("cloudflared isn't installed")
        env = os.environ.copy()
        if quick_tunnel:
            argv = [binary, "tunnel", "--no-autoupdate", "--url", f"http://localhost:{config.port}"]
            ready = _QUICK_URL
        else:
            if not api_token:
                raise ValueError("API Token required for named tunnel")
            if not tunnel_name:
                raise ValueError("Tunnel name required for named tunnel")
            argv = [binary, "tunnel", "--no-autoupdate", "run"]
            env["TUNNEL_TOKEN"] = api_token
            ready = _CONNECTED

        await job.log(f"Starting cloudflared for http://localhost:{config.port}")
        process = TunnelProcess(argv, env, ready)
        match = await process.wait_ready(_START_TIMEOUT)
        self._process = process
        if quick_tunnel:
            self._url = match.group(0)
        else:
            self._url = f"https://{domain or f'{tunnel_name}.cfargotunnel.com'}"
        return self._url

    async def stop(self, job: Any) -> None:
        """Stop the cloudflared that Athena started."""
        process, self._process, self._url = self._process, None, None
        if process is None or not process.alive:
            if _cloudflared_running():
                raise RuntimeError(
                    "cloudflared is running but Athena didn't start it "
                    "(an auto-start service or another program); stop it there"
                )
            await job.log("The tunnel wasn't running")
            return
        await asyncio.to_thread(process.stop)

    def shutdown(self) -> None:
        if self._process is not None:
            self._process.stop()
            self._process = None
            self._url = None

    def status(self) -> TunnelStatus:
        """Check cloudflared tunnel status."""
        if self._process is not None and self._process.alive:
            return TunnelStatus(
                running=True,
                public_url=self._url,
                provider="cloudflare",
                detail="Cloudflare Tunnel running",
            )
        try:
            running = _cloudflared_running()
        except Exception as e:
            return TunnelStatus(
                running=False,
                provider="cloudflare",
                detail=f"Status check failed: {e}",
            )
        if running:
            detail = "cloudflared is running outside Athena"
        elif self._process is not None:
            detail = f"cloudflared exited (code {self._process.proc.returncode})"
        else:
            detail = "Not running"
        return TunnelStatus(running=running, provider="cloudflare", detail=detail)

    def get_config_schema(self) -> dict:
        """Return JSON schema for Cloudflare Tunnel configuration."""
        return {
            "type": "object",
            "properties": {
                "quick_tunnel": {
                    "type": "boolean",
                    "title": "Quick Tunnel (trycloudflare.com)",
                    "description": "Use ephemeral trycloudflare.com URL (no auth needed)",
                    "default": True,
                },
                "api_token": {
                    "type": "string",
                    "title": "API Token",
                    "description": (
                        "Cloudflare API Token with Tunnel permissions (required for named tunnels)"
                    ),
                    "format": "password",
                },
                "tunnel_name": {
                    "type": "string",
                    "title": "Tunnel Name",
                    "description": "Name of the named tunnel (required for named tunnels)",
                },
                "domain": {
                    "type": "string",
                    "title": "Custom Domain",
                    "description": "Custom domain for the tunnel (optional, requires DNS setup)",
                },
            },
            "required": [],
        }

    async def install(self, job: Any) -> None:
        """Download and install cloudflared."""
        import platform
        import tempfile
        import urllib.request

        system = platform.system().lower()
        filename = release_asset(system, platform.machine())
        url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/{filename}"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            download_path = tmpdir_path / filename

            await job.log(f"Downloading cloudflared from {url}")
            await asyncio.to_thread(urllib.request.urlretrieve, url, download_path)

            if filename.endswith(".tgz"):
                import tarfile

                with tarfile.open(download_path, "r:gz") as tar:
                    tar.extract("cloudflared", tmpdir_path, filter="data")
                binary_path = tmpdir_path / "cloudflared"
            else:
                # Linux and Windows releases are the bare binary.
                binary_path = download_path

            # Install to PATH
            if system == "windows":
                # Windows: install to ~/scoop/shims or similar
                install_dir = Path.home() / "scoop" / "shims"
                install_dir.mkdir(parents=True, exist_ok=True)
                dest = install_dir / "cloudflared.exe"
            else:
                # Linux/macOS: install to /usr/local/bin (needs sudo) or ~/.local/bin
                install_dir = Path("/usr/local/bin")
                if not os.access(install_dir, os.W_OK):
                    install_dir = Path.home() / ".local" / "bin"
                    install_dir.mkdir(parents=True, exist_ok=True)
                dest = install_dir / "cloudflared"

            shutil.copy2(binary_path, dest)
            if system != "windows":
                dest.chmod(0o755)

            await job.log(f"Installed cloudflared to {dest}")

    async def configure_service(
        self,
        job: Any,
        enabled: bool,
        port: int = 8420,
        provider_config: dict | None = None,
    ) -> None:
        """Configure systemd/launchd/Task Scheduler for auto-start.

        Only a named tunnel can run as a service (a quick tunnel's URL changes on each
        start). The service runs `cloudflared tunnel run --token-file <file>`; the file
        holds the tunnel token and is readable by its owner only."""
        import platform

        system = platform.system().lower()
        token_path = servicefiles.private_dir() / "cloudflared.token"
        if enabled:
            config = provider_config or {}
            token = config.get("api_token")
            if config.get("quick_tunnel", True) or not token:
                raise ValueError(
                    "Auto-start needs a named tunnel: turn off quick tunnel and save its token"
                )
            binary = find_binary("cloudflared")
            if binary is None:
                raise RuntimeError("cloudflared isn't installed")
            servicefiles.write_private(token_path, token)
            argv = [binary, "tunnel", "--no-autoupdate", "run", "--token-file", str(token_path)]
        else:
            argv = []

        if system == "linux":
            await self._configure_systemd(job, enabled, argv)
        elif system == "darwin":
            await self._configure_launchd(job, enabled, argv)
        elif system == "windows":
            await self._configure_windows_task(job, enabled, argv)
        if not enabled:
            servicefiles.remove_private(token_path)

    async def _configure_systemd(self, job: Any, enabled: bool, argv: list[str]) -> None:
        """Configure systemd service."""
        service_content = f"""[Unit]
Description=Cloudflare Tunnel
After=network.target

[Service]
Type=simple
ExecStart={shlex.join(argv)}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
        service_path = Path("/etc/systemd/system/cloudflared.service")
        if enabled:
            service_path.write_text(service_content)
            subprocess.run(["systemctl", "daemon-reload"], check=False)
            subprocess.run(["systemctl", "enable", "cloudflared"], check=False)
            subprocess.run(["systemctl", "start", "cloudflared"], check=False)
            await job.log("Enabled cloudflared systemd service")
        else:
            subprocess.run(["systemctl", "stop", "cloudflared"], check=False)
            subprocess.run(["systemctl", "disable", "cloudflared"], check=False)
            if service_path.exists():
                service_path.unlink()
            subprocess.run(["systemctl", "daemon-reload"], check=False)
            await job.log("Disabled cloudflared systemd service")

    async def _configure_launchd(self, job: Any, enabled: bool, argv: list[str]) -> None:
        """Configure launchd agent."""
        args = "\n".join(f"        <string>{escape(a)}</string>" for a in argv)
        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.athena.tunnel.cloudflare</string>
    <key>ProgramArguments</key>
    <array>
{args}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
"""
        plist_path = Path.home() / "Library" / "LaunchAgents" / "com.athena.tunnel.cloudflare.plist"
        if enabled:
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            plist_path.write_text(plist_content)
            subprocess.run(["launchctl", "load", str(plist_path)], check=False)
            await job.log("Enabled cloudflared launchd agent")
        else:
            subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
            if plist_path.exists():
                plist_path.unlink()
            await job.log("Disabled cloudflared launchd agent")

    async def _configure_windows_task(self, job: Any, enabled: bool, argv: list[str]) -> None:
        """Configure Windows Task Scheduler."""
        if enabled:
            cmd = [
                "schtasks",
                "/Create",
                "/TN",
                "Athena Cloudflare Tunnel",
                "/TR",
                servicefiles.windows_command(argv),
                "/SC",
                "ONLOGON",
                "/RL",
                "HIGHEST",
                "/F",
            ]
            subprocess.run(cmd, check=False)
            await job.log("Enabled cloudflared Windows scheduled task")
        else:
            subprocess.run(
                ["schtasks", "/Delete", "/TN", "Athena Cloudflare Tunnel", "/F"],
                check=False,
            )
            await job.log("Disabled cloudflared Windows scheduled task")
