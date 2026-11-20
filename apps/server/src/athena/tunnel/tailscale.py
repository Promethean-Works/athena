"""Tailscale Funnel provider implementation."""

import asyncio
import json
import logging
import subprocess
from typing import Any

from athena.tunnel.base import TunnelConfig, TunnelProvider, TunnelStatus

log = logging.getLogger(__name__)


_TIMEOUT = 30


def _run(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def funnel_url_from(serve_config: dict) -> str | None:
    """The public URL from `tailscale funnel status --json`, or None when Funnel is off.

    `AllowFunnel` maps `<node>.<tailnet>.ts.net:<port>` to true for each funnelled port.
    """
    for host_port, allowed in (serve_config.get("AllowFunnel") or {}).items():
        if allowed:
            host, _, port = host_port.rpartition(":")
            return f"https://{host}" if port == "443" else f"https://{host_port}"
    return None


def _funnel_url() -> str | None:
    result = _run(["tailscale", "funnel", "status", "--json"], _TIMEOUT)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return funnel_url_from(json.loads(result.stdout))


class TailscaleTunnelProvider(TunnelProvider):
    """Tailscale Funnel provider."""

    @property
    def capability_id(self) -> str:
        return "tunnel.tailscale"

    @property
    def label(self) -> str:
        return "Tailscale Funnel"

    async def start(self, job: Any, config: TunnelConfig) -> str:
        """Turn on Tailscale Funnel for the port, in the background. Returns the URL.

        Without `--bg`, `tailscale funnel <port>` stays in the foreground until it's
        interrupted, and the job would never finish.
        """
        await job.log(f"Turning on Tailscale Funnel for http://localhost:{config.port}")
        result = await asyncio.to_thread(
            _run, ["tailscale", "funnel", "--bg", str(config.port)], _TIMEOUT
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to start Tailscale Funnel: {result.stderr or result.stdout}"
            )
        url = await asyncio.to_thread(_funnel_url)
        if url is None:
            raise RuntimeError("Tailscale Funnel was turned on but reports no public URL")
        return url

    async def stop(self, job: Any) -> None:
        """Turn off Tailscale Funnel on HTTPS port 443 (where `funnel --bg` puts it)."""
        result = await asyncio.to_thread(
            _run, ["tailscale", "funnel", "--https=443", "off"], _TIMEOUT
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to stop Tailscale Funnel: {result.stderr or result.stdout}")

    def status(self) -> TunnelStatus:
        """Check Tailscale Funnel status."""
        try:
            result = _run(["tailscale", "status", "--json"], _TIMEOUT)
            if result.returncode != 0:
                return TunnelStatus(
                    running=False,
                    provider="tailscale",
                    detail="Tailscale not running",
                )
            status = json.loads(result.stdout)
            backend_state = status.get("BackendState", "")
            if backend_state != "Running":
                return TunnelStatus(
                    running=False,
                    provider="tailscale",
                    detail=f"Tailscale not logged in (state: {backend_state})",
                )
            public_url = _funnel_url()
            running = public_url is not None
            tailnet_name = status.get("CurrentTailnet", {}).get("MagicDNSSuffix", "tailnet")
            return TunnelStatus(
                running=running,
                public_url=public_url,
                provider="tailscale",
                detail=(
                    f"Logged in to {tailnet_name}"
                    + (" - Funnel active" if running else " - Funnel inactive")
                ),
            )
        except Exception as e:
            return TunnelStatus(
                running=False,
                provider="tailscale",
                detail=f"Status check failed: {e}",
            )

    def get_config_schema(self) -> dict:
        """Return JSON schema for Tailscale Funnel configuration."""
        return {
            "type": "object",
            "properties": {
                "tailnet_name": {
                    "type": "string",
                    "title": "Tailnet",
                    "description": "Your Tailscale tailnet (detected automatically)",
                    "readOnly": True,
                },
            },
            "required": [],
        }

    async def install(self, job: Any) -> None:
        """Install Tailscale using the official install script."""
        import platform
        import urllib.request

        system = platform.system().lower()

        if system == "windows":
            # Windows: use winget or download MSI
            await job.log("Installing Tailscale on Windows...")
            result = subprocess.run(
                ["winget", "install", "--id", "Tailscale.Tailscale", "--silent"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                # Fallback to scoop
                result = subprocess.run(
                    ["scoop", "install", "tailscale"],
                    capture_output=True,
                    text=True,
                )
            if result.returncode != 0:
                raise RuntimeError(
                    "Failed to install Tailscale. Please install manually from https://tailscale.com/download"
                )
        else:
            # Linux/macOS: use official install script
            await job.log("Downloading Tailscale install script...")
            script_url = "https://tailscale.com/install.sh"
            with urllib.request.urlopen(script_url) as response:
                script = response.read()

            await job.log("Running Tailscale install script...")
            result = subprocess.run(
                ["sh"],
                input=script,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Tailscale install failed: {result.stderr}")

        await job.log("Tailscale installed. Run 'tailscale up' to authenticate.")

    async def configure_service(self, job: Any, enabled: bool, port: int = 8420) -> None:
        """Configure auto-start. Tailscale runs as a system daemon (tailscaled)."""
        import platform

        system = platform.system().lower()

        if system == "linux":
            if enabled:
                subprocess.run(["systemctl", "enable", "--now", "tailscaled"], check=False)
                await job.log("Enabled tailscaled systemd service")
            else:
                subprocess.run(["systemctl", "disable", "tailscaled"], check=False)
                await job.log("Disabled tailscaled systemd service")
        elif system == "darwin":
            # macOS: tailscale runs as a launch daemon installed by the pkg
            if enabled:
                subprocess.run(
                    ["launchctl", "load", "/Library/LaunchDaemons/com.tailscale.tailscaled.plist"],
                    check=False,
                )
                await job.log("Enabled tailscaled launchd daemon")
            else:
                subprocess.run(
                    [
                        "launchctl",
                        "unload",
                        "/Library/LaunchDaemons/com.tailscale.tailscaled.plist",
                    ],
                    check=False,
                )
                await job.log("Disabled tailscaled launchd daemon")
        elif system == "windows":
            # Windows: Tailscale runs as a service
            if enabled:
                subprocess.run(["sc", "config", "Tailscale", "start=", "auto"], check=False)
                subprocess.run(["net", "start", "Tailscale"], check=False)
                await job.log("Enabled Tailscale Windows service")
            else:
                subprocess.run(["net", "stop", "Tailscale"], check=False)
                subprocess.run(["sc", "config", "Tailscale", "start=", "demand"], check=False)
                await job.log("Disabled Tailscale Windows service")
