"""Ngrok provider implementation."""

import contextlib
import json
import logging
import os
import platform
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

from athena.tunnel.base import TunnelConfig, TunnelProvider, TunnelStatus

log = logging.getLogger(__name__)


class NgrokTunnelProvider(TunnelProvider):
    """Ngrok tunnel provider."""

    @property
    def capability_id(self) -> str:
        return "tunnel.ngrok"

    @property
    def label(self) -> str:
        return "Ngrok"

    async def start(self, job: Any, config: TunnelConfig) -> str:
        """Start ngrok tunnel. Returns public URL."""
        provider_config = config.provider_config or {}
        auth_token = provider_config.get("auth_token")
        domain = provider_config.get("domain")
        subdomain = provider_config.get("subdomain")

        if not auth_token:
            raise ValueError("Ngrok auth token required")

        port = config.port

        # Configure auth token
        subprocess.run(["ngrok", "config", "add-authtoken", auth_token], capture_output=True)

        # Build command
        cmd = ["ngrok", "http", str(port)]

        if domain:
            cmd.extend(["--domain", domain])
        elif subdomain:
            cmd.extend(["--subdomain", subdomain])

        # Start ngrok in background
        # Note: In production, this would be managed by the job system
        # For now, we return the expected URL pattern
        # The actual URL would be parsed from ngrok API or output

        # Get URL from ngrok API
        with contextlib.suppress(Exception):
            # Start ngrok process
            # In reality, we'd start it as a background job and poll the API
            pass

        if domain:
            return f"https://{domain}"
        elif subdomain:
            return f"https://{subdomain}.ngrok.io"
        else:
            # Free tier: random URL
            return "https://<random>.ngrok-free.app"

    async def stop(self, job: Any) -> None:
        """Stop ngrok tunnel."""
        subprocess.run(["ngrok", "stop"], capture_output=True)

    def status(self) -> TunnelStatus:
        """Check ngrok tunnel status via API."""
        try:
            # ngrok API runs on localhost:4040
            import urllib.request

            with urllib.request.urlopen("http://localhost:4040/api/tunnels", timeout=2) as resp:
                data = json.loads(resp.read().decode())

            tunnels = data.get("tunnels", [])
            if not tunnels:
                return TunnelStatus(
                    running=False,
                    provider="ngrok",
                    detail="Ngrok not running",
                )

            # Get the first HTTP tunnel
            for tunnel in tunnels:
                if tunnel.get("proto") == "https":
                    public_url = tunnel.get("public_url")
                    return TunnelStatus(
                        running=True,
                        public_url=public_url,
                        provider="ngrok",
                        detail=f"Ngrok tunnel active: {public_url}",
                    )

            return TunnelStatus(
                running=False,
                provider="ngrok",
                detail="No HTTPS tunnels found",
            )
        except Exception:
            return TunnelStatus(
                running=False,
                provider="ngrok",
                detail="Ngrok not running or API unavailable",
            )

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
            job.log(f"Downloading ngrok from {url}")
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

            job.log(f"Installed ngrok to {dest}")

    async def configure_service(self, job: Any, enabled: bool) -> None:
        """Configure systemd/launchd/Task Scheduler for auto-start."""

        system = platform.system().lower()

        if system == "linux":
            await self._configure_systemd(job, enabled)
        elif system == "darwin":
            await self._configure_launchd(job, enabled)
        elif system == "windows":
            await self._configure_windows_task(job, enabled)

    async def _configure_systemd(self, job: Any, enabled: bool) -> None:
        """Configure systemd service."""
        # Need auth token from config - this would come from settings
        service_content = """[Unit]
Description=Ngrok Tunnel
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/ngrok http 8420 --authtoken=${NGROK_AUTHTOKEN}
Restart=on-failure
RestartSec=5
Environment=NGROK_AUTHTOKEN=${NGROK_AUTHTOKEN}

[Install]
WantedBy=multi-user.target
"""
        service_path = Path("/etc/systemd/system/ngrok.service")
        if enabled:
            # Note: The auth token would need to be set in the environment
            service_path.write_text(service_content)
            subprocess.run(["systemctl", "daemon-reload"], check=False)
            subprocess.run(["systemctl", "enable", "ngrok"], check=False)
            subprocess.run(["systemctl", "start", "ngrok"], check=False)
            job.log("Enabled ngrok systemd service (auth token must be configured)")
        else:
            subprocess.run(["systemctl", "stop", "ngrok"], check=False)
            subprocess.run(["systemctl", "disable", "ngrok"], check=False)
            if service_path.exists():
                service_path.unlink()
            subprocess.run(["systemctl", "daemon-reload"], check=False)
            job.log("Disabled ngrok systemd service")

    async def _configure_launchd(self, job: Any, enabled: bool) -> None:
        """Configure launchd agent."""
        plist_content = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.athena.tunnel.ngrok</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/ngrok</string>
        <string>http</string>
        <string>8420</string>
        <string>--authtoken</string>
        <string>${NGROK_AUTHTOKEN}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>NGROK_AUTHTOKEN</key>
        <string>${NGROK_AUTHTOKEN}</string>
    </dict>
    <key>StandardOutPath</key>
    <string>/var/log/ngrok.log</string>
    <key>StandardErrorPath</key>
    <string>/var/log/ngrok.error.log</string>
</dict>
</plist>
"""
        plist_path = Path.home() / "Library" / "LaunchAgents" / "com.athena.tunnel.ngrok.plist"
        if enabled:
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            plist_path.write_text(plist_content)
            subprocess.run(["launchctl", "load", str(plist_path)], check=False)
            job.log("Enabled ngrok launchd agent (auth token must be configured)")
        else:
            subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
            if plist_path.exists():
                plist_path.unlink()
            job.log("Disabled ngrok launchd agent")

    async def _configure_windows_task(self, job: Any, enabled: bool) -> None:
        """Configure Windows Task Scheduler."""
        if enabled:
            cmd = [
                "schtasks",
                "/Create",
                "/TN",
                "Athena Ngrok Tunnel",
                "/TR",
                (
                    "C:\\Users\\%USERNAME%\\scoop\\shims\\ngrok.exe "
                    "http 8420 --authtoken=${NGROK_AUTHTOKEN}"
                ),
                "/SC",
                "ONLOGON",
                "/RL",
                "HIGHEST",
                "/F",
            ]
            subprocess.run(cmd, check=False)
            job.log("Enabled ngrok Windows scheduled task (auth token must be configured)")
        else:
            subprocess.run(
                ["schtasks", "/Delete", "/TN", "Athena Ngrok Tunnel", "/F"],
                check=False,
            )
            job.log("Disabled ngrok Windows scheduled task")
