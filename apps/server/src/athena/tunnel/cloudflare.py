"""Cloudflare Tunnel provider implementation."""

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from athena.tunnel.base import TunnelConfig, TunnelProvider, TunnelStatus

log = logging.getLogger(__name__)


class CloudflareTunnelProvider(TunnelProvider):
    """Cloudflare Tunnel provider supporting both named and quick tunnels."""

    @property
    def capability_id(self) -> str:
        return "tunnel.cloudflare"

    @property
    def label(self) -> str:
        return "Cloudflare Tunnel"

    async def start(self, job: Any, config: TunnelConfig) -> str:
        """Start cloudflared tunnel. Returns public URL."""
        provider_config = config.provider_config or {}
        quick_tunnel = provider_config.get("quick_tunnel", True)
        tunnel_name = provider_config.get("tunnel_name")
        domain = provider_config.get("domain")
        api_token = provider_config.get("api_token")

        port = config.port

        if quick_tunnel:
            # Quick tunnel: cloudflared tunnel --url http://localhost:PORT
            # No auth needed, ephemeral trycloudflare.com URL
            env = os.environ.copy()
        else:
            # Named tunnel: requires API token and tunnel name
            if not api_token:
                raise ValueError("API Token required for named tunnel")
            if not tunnel_name:
                raise ValueError("Tunnel name required for named tunnel")

            # Write config file for named tunnel
            config_dir = Path("/etc/cloudflared")
            config_dir.mkdir(parents=True, exist_ok=True)
            config_file = config_dir / "config.yml"

            config_content = {
                "tunnel": tunnel_name,
                "credentials-file": f"/etc/cloudflared/{tunnel_name}.json",
                "ingress": [
                    {
                        "hostname": domain or f"{tunnel_name}.cfargotunnel.com",
                        "service": f"http://localhost:{port}",
                    },
                    {"service": "http_status:404"},
                ],
            }

            import yaml

            config_file.write_text(yaml.dump(config_content))
            env = os.environ.copy()
            env["TUNNEL_TOKEN"] = api_token

        # Start the process in background
        # Note: In production, this would be managed by the job system
        # For now, we return the expected URL pattern
        if quick_tunnel:
            # Quick tunnel URL is ephemeral, we can't know it ahead of time
            # The actual URL would be parsed from cloudflared output
            return "https://<ephemeral>.trycloudflare.com"
        else:
            return f"https://{domain or f'{tunnel_name}.cfargotunnel.com'}"

    async def stop(self, job: Any) -> None:
        """Stop cloudflared tunnel."""
        # cloudflared tunnels are stopped by killing the process
        # In production, we'd track the process and kill it
        pass

    def status(self) -> TunnelStatus:
        """Check cloudflared tunnel status."""
        try:
            # Check if cloudflared is running
            result = subprocess.run(
                ["pgrep", "-f", "cloudflared tunnel"],
                capture_output=True,
            )
            running = result.returncode == 0

            # For quick tunnels, we'd need to parse the actual URL from logs
            # For named tunnels, we can construct the URL
            public_url = None
            if running:
                # Try to get tunnel list for named tunnels
                try:
                    result = subprocess.run(
                        ["cloudflared", "tunnel", "list", "--output", "json"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode == 0:
                        tunnels = json.loads(result.stdout)
                        for t in tunnels:
                            if t.get("status") == "healthy":
                                public_url = f"https://{t.get('name')}.cfargotunnel.com"
                                break
                except Exception:
                    pass

            return TunnelStatus(
                running=running,
                public_url=public_url,
                provider="cloudflare",
                detail="Cloudflare Tunnel running" if running else "Not running",
            )
        except Exception as e:
            return TunnelStatus(
                running=False,
                provider="cloudflare",
                detail=f"Status check failed: {e}",
            )

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
        import urllib.request

        system = platform.system().lower()
        arch = platform.machine().lower()

        # Map architecture
        if arch in ("x86_64", "amd64"):
            arch = "amd64"
        elif arch in ("aarch64", "arm64"):
            arch = "arm64"
        else:
            raise ValueError(f"Unsupported architecture: {arch}")

        # Download URL pattern
        if system == "darwin":
            filename = f"cloudflared-darwin-{arch}.tgz"
        elif system == "linux":
            filename = f"cloudflared-linux-{arch}.tgz"
        elif system == "windows":
            filename = f"cloudflared-windows-{arch}.zip"
        else:
            raise ValueError(f"Unsupported OS: {system}")

        url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/{filename}"

        # Download to temp
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            archive_path = tmpdir_path / filename

            # Download
            job.log(f"Downloading cloudflared from {url}")
            urllib.request.urlretrieve(url, archive_path)

            # Extract
            if filename.endswith(".tgz"):
                import tarfile

                with tarfile.open(archive_path, "r:gz") as tar:
                    tar.extractall(tmpdir_path)
                binary_path = tmpdir_path / "cloudflared"
            else:
                import zipfile

                with zipfile.ZipFile(archive_path, "r") as zipf:
                    zipf.extractall(tmpdir_path)
                binary_path = tmpdir_path / "cloudflared.exe"

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

            job.log(f"Installed cloudflared to {dest}")

    async def configure_service(self, job: Any, enabled: bool) -> None:
        """Configure systemd/launchd service for auto-start."""
        import platform

        system = platform.system().lower()

        if system == "linux":
            await self._configure_systemd(job, enabled)
        elif system == "darwin":
            await self._configure_launchd(job, enabled)
        elif system == "windows":
            await self._configure_windows_task(job, enabled)

    async def _configure_systemd(self, job: Any, enabled: bool) -> None:
        """Configure systemd service."""
        service_content = """[Unit]
Description=Cloudflare Tunnel
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/cloudflared tunnel run --config /etc/cloudflared/config.yml
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
            job.log("Enabled cloudflared systemd service")
        else:
            subprocess.run(["systemctl", "stop", "cloudflared"], check=False)
            subprocess.run(["systemctl", "disable", "cloudflared"], check=False)
            if service_path.exists():
                service_path.unlink()
            subprocess.run(["systemctl", "daemon-reload"], check=False)
            job.log("Disabled cloudflared systemd service")

    async def _configure_launchd(self, job: Any, enabled: bool) -> None:
        """Configure launchd agent."""
        plist_content = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.athena.tunnel.cloudflare</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/cloudflared</string>
        <string>tunnel</string>
        <string>run</string>
        <string>--config</string>
        <string>/etc/cloudflared/config.yml</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/var/log/cloudflared.log</string>
    <key>StandardErrorPath</key>
    <string>/var/log/cloudflared.error.log</string>
</dict>
</plist>
"""
        plist_path = Path.home() / "Library" / "LaunchAgents" / "com.athena.tunnel.cloudflare.plist"
        if enabled:
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            plist_path.write_text(plist_content)
            subprocess.run(["launchctl", "load", str(plist_path)], check=False)
            job.log("Enabled cloudflared launchd agent")
        else:
            subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
            if plist_path.exists():
                plist_path.unlink()
            job.log("Disabled cloudflared launchd agent")

    async def _configure_windows_task(self, job: Any, enabled: bool) -> None:
        """Configure Windows Task Scheduler."""
        if enabled:
            cmd = [
                "schtasks",
                "/Create",
                "/TN",
                "Athena Cloudflare Tunnel",
                "/TR",
                (
                    "C:\\Users\\%USERNAME%\\scoop\\shims\\cloudflared.exe "
                    "tunnel run --config C:\\cloudflared\\config.yml"
                ),
                "/SC",
                "ONLOGON",
                "/RL",
                "HIGHEST",
                "/F",
            ]
            subprocess.run(cmd, check=False)
            job.log("Enabled cloudflared Windows scheduled task")
        else:
            subprocess.run(
                ["schtasks", "/Delete", "/TN", "Athena Cloudflare Tunnel", "/F"],
                check=False,
            )
            job.log("Disabled cloudflared Windows scheduled task")
