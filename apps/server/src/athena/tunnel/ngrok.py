"""Ngrok provider implementation."""

import asyncio
import json
import logging
import os
import platform
import re
import shlex
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from athena.tunnel import servicefiles
from athena.tunnel.base import TunnelConfig, TunnelProvider, TunnelStatus
from athena.tunnel.process import TunnelProcess, find_binary

log = logging.getLogger(__name__)


# logfmt line: `... msg="started tunnel" obj=tunnels name=command_line addr=... url=https://x`
_STARTED = re.compile(r'msg="started tunnel".*?\burl=(https://\S+)')
_START_TIMEOUT = 60.0


def _config_file(token: str) -> str:
    """ngrok agent config (v3) with the auth token. The token is JSON-quoted, which is
    valid YAML, so odd characters can't break the file."""
    return f"version: 3\nagent:\n  authtoken: {json.dumps(token)}\n"


def _api_url() -> str | None:
    """The HTTPS URL from the local ngrok agent API (port 4040), if one runs."""
    try:
        with urllib.request.urlopen("http://localhost:4040/api/tunnels", timeout=2) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return None
    for tunnel in data.get("tunnels", []):
        if tunnel.get("proto") == "https":
            return tunnel.get("public_url")
    return None


class NgrokTunnelProvider(TunnelProvider):
    """Ngrok tunnel provider."""

    @property
    def capability_id(self) -> str:
        return "tunnel.ngrok"

    @property
    def label(self) -> str:
        return "Ngrok"

    def __init__(self) -> None:
        self._process: TunnelProcess | None = None
        self._url: str | None = None

    async def start(self, job: Any, config: TunnelConfig) -> str:
        """Run `ngrok http` and wait for its public URL. Returns the URL.

        The auth token goes in `NGROK_AUTHTOKEN` rather than argv or ngrok's config
        file, so it isn't visible in `ps` or written to disk in plain text.
        """
        if self._process is not None and self._process.alive:
            raise RuntimeError("The tunnel is already running; stop it first")
        provider_config = config.provider_config or {}
        auth_token = provider_config.get("auth_token")
        domain = provider_config.get("domain")
        subdomain = provider_config.get("subdomain")
        if not auth_token:
            raise ValueError("Ngrok auth token required")
        binary = find_binary("ngrok")
        if binary is None:
            raise RuntimeError("ngrok isn't installed")

        argv = [binary, "http", str(config.port), "--log", "stdout", "--log-format", "logfmt"]
        if domain:
            argv += ["--domain", domain]
        elif subdomain:
            argv += ["--subdomain", subdomain]
        env = os.environ.copy()
        env["NGROK_AUTHTOKEN"] = auth_token

        await job.log(f"Starting ngrok for http://localhost:{config.port}")
        process = TunnelProcess(argv, env, _STARTED)
        match = await process.wait_ready(_START_TIMEOUT)
        self._process = process
        self._url = match.group(1)
        return self._url

    async def stop(self, job: Any) -> None:
        """Stop the ngrok that Athena started."""
        process, self._process, self._url = self._process, None, None
        if process is None or not process.alive:
            if _api_url() is not None:
                raise RuntimeError(
                    "ngrok is running but Athena didn't start it "
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
        """Athena's own ngrok, else one found through ngrok's local API."""
        if self._process is not None and self._process.alive:
            return TunnelStatus(
                running=True,
                public_url=self._url,
                provider="ngrok",
                detail=f"Ngrok tunnel active: {self._url}",
            )
        public_url = _api_url()
        if public_url is not None:
            return TunnelStatus(
                running=True,
                public_url=public_url,
                provider="ngrok",
                detail=f"Ngrok tunnel active (started outside Athena): {public_url}",
            )
        if self._process is not None:
            detail = f"ngrok exited (code {self._process.proc.returncode})"
        else:
            detail = "Ngrok not running"
        return TunnelStatus(running=False, provider="ngrok", detail=detail)

    def get_config_schema(self) -> dict:
        """Return JSON schema for Ngrok configuration."""
        return {
            "type": "object",
            "properties": {
                "auth_token": {
                    "type": "string",
                    "title": "Auth Token",
                    "description": "Your ngrok auth token (required)",
                    "format": "password",
                },
                "domain": {
                    "type": "string",
                    "title": "Custom Domain",
                    "description": "Custom domain (requires paid plan)",
                },
                "subdomain": {
                    "type": "string",
                    "title": "Subdomain",
                    "description": "Custom subdomain (requires paid plan)",
                },
            },
            "required": ["auth_token"],
        }

    async def install(self, job: Any) -> None:
        """Download and install ngrok."""

        system = platform.system().lower()
        arch = platform.machine().lower()

        # Map architecture
        if arch in ("x86_64", "amd64"):
            arch = "amd64"
        elif arch in ("aarch64", "arm64"):
            arch = "arm64"
        elif arch in ("armv7l", "armv7"):
            arch = "arm"
        else:
            raise ValueError(f"Unsupported architecture: {arch}")

        # Download URL pattern
        if system == "darwin":
            filename = f"ngrok-v3-stable-darwin-{arch}.zip"
        elif system == "linux":
            filename = f"ngrok-v3-stable-linux-{arch}.tgz"
        elif system == "windows":
            filename = f"ngrok-v3-stable-windows-{arch}.zip"
        else:
            raise ValueError(f"Unsupported OS: {system}")

        url = f"https://bin.equinox.io/c/bNyj1mQVY4c/{filename}"

        # Download to temp
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            archive_path = tmpdir_path / filename

            # Download
            await job.log(f"Downloading ngrok from {url}")
            urllib.request.urlretrieve(url, archive_path)

            # Extract
            if filename.endswith(".tgz"):
                import tarfile

                with tarfile.open(archive_path, "r:gz") as tar:
                    tar.extractall(tmpdir_path)
                binary_path = tmpdir_path / "ngrok"
            else:
                import zipfile

                with zipfile.ZipFile(archive_path, "r") as zipf:
                    zipf.extractall(tmpdir_path)
                binary_path = tmpdir_path / "ngrok.exe"

            # Install to PATH
            if system == "windows":
                install_dir = Path.home() / "scoop" / "shims"
                install_dir.mkdir(parents=True, exist_ok=True)
                dest = install_dir / "ngrok.exe"
            else:
                install_dir = Path("/usr/local/bin")
                if not os.access(install_dir, os.W_OK):
                    install_dir = Path.home() / ".local" / "bin"
                    install_dir.mkdir(parents=True, exist_ok=True)
                dest = install_dir / "ngrok"

            shutil.copy2(binary_path, dest)
            if system != "windows":
                dest.chmod(0o755)

            await job.log(f"Installed ngrok to {dest}")

    async def configure_service(
        self,
        job: Any,
        enabled: bool,
        port: int = 8420,
        provider_config: dict | None = None,
    ) -> None:
        """Configure systemd/launchd/Task Scheduler for auto-start.

        The service runs `ngrok http <port> --config <file>`; the file holds the auth
        token and is readable by its owner only. Enabling needs the saved auth token."""

        system = platform.system().lower()
        config_path = servicefiles.private_dir() / "ngrok.yml"
        if enabled:
            token = (provider_config or {}).get("auth_token")
            if not token:
                raise ValueError("Save the ngrok auth token before enabling auto-start")
            binary = find_binary("ngrok")
            if binary is None:
                raise RuntimeError("ngrok isn't installed")
            servicefiles.write_private(config_path, _config_file(token))
            argv = [binary, "http", str(port), "--config", str(config_path)]
        else:
            argv = []

        if system == "linux":
            await self._configure_systemd(job, enabled, argv)
        elif system == "darwin":
            await self._configure_launchd(job, enabled, argv)
        elif system == "windows":
            await self._configure_windows_task(job, enabled, argv)
        if not enabled:
            servicefiles.remove_private(config_path)

    async def _configure_systemd(self, job: Any, enabled: bool, argv: list[str]) -> None:
        """Configure systemd service."""
        service_content = f"""[Unit]
Description=Ngrok Tunnel
After=network.target

[Service]
Type=simple
ExecStart={shlex.join(argv)}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
        service_path = Path("/etc/systemd/system/ngrok.service")
        if enabled:
            service_path.write_text(service_content)
            subprocess.run(["systemctl", "daemon-reload"], check=False)
            subprocess.run(["systemctl", "enable", "ngrok"], check=False)
            subprocess.run(["systemctl", "start", "ngrok"], check=False)
            await job.log("Enabled ngrok systemd service")
        else:
            subprocess.run(["systemctl", "stop", "ngrok"], check=False)
            subprocess.run(["systemctl", "disable", "ngrok"], check=False)
            if service_path.exists():
                service_path.unlink()
            subprocess.run(["systemctl", "daemon-reload"], check=False)
            await job.log("Disabled ngrok systemd service")

    async def _configure_launchd(self, job: Any, enabled: bool, argv: list[str]) -> None:
        """Configure launchd agent."""
        args = "\n".join(f"        <string>{escape(a)}</string>" for a in argv)
        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.athena.tunnel.ngrok</string>
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
        plist_path = Path.home() / "Library" / "LaunchAgents" / "com.athena.tunnel.ngrok.plist"
        if enabled:
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            plist_path.write_text(plist_content)
            subprocess.run(["launchctl", "load", str(plist_path)], check=False)
            await job.log("Enabled ngrok launchd agent")
        else:
            subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
            if plist_path.exists():
                plist_path.unlink()
            await job.log("Disabled ngrok launchd agent")

    async def _configure_windows_task(self, job: Any, enabled: bool, argv: list[str]) -> None:
        """Configure Windows Task Scheduler."""
        if enabled:
            cmd = [
                "schtasks",
                "/Create",
                "/TN",
                "Athena Ngrok Tunnel",
                "/TR",
                servicefiles.windows_command(argv),
                "/SC",
                "ONLOGON",
                "/RL",
                "HIGHEST",
                "/F",
            ]
            subprocess.run(cmd, check=False)
            await job.log("Enabled ngrok Windows scheduled task")
        else:
            subprocess.run(
                ["schtasks", "/Delete", "/TN", "Athena Ngrok Tunnel", "/F"],
                check=False,
            )
            await job.log("Disabled ngrok Windows scheduled task")
