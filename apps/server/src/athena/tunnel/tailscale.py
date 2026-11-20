"""Tailscale Funnel provider implementation."""

import json
import logging
import subprocess
from typing import Any

from athena.tunnel.base import TunnelConfig, TunnelProvider, TunnelStatus

log = logging.getLogger(__name__)


class TailscaleTunnelProvider(TunnelProvider):
    """Tailscale Funnel provider."""

    @property
    def capability_id(self) -> str:
        return "tunnel.tailscale"

    @property
    def label(self) -> str:
        return "Tailscale Funnel"

    async def start(self, job: Any, config: TunnelConfig) -> str:
        """Start Tailscale Funnel. Returns public URL."""
        port = config.port

        # Enable funnel for the port
        result = subprocess.run(
            ["tailscale", "funnel", str(port)],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to start Tailscale Funnel: {result.stderr}")

        # Get the funnel URL
        status_result = subprocess.run(
            ["tailscale", "funnel", "status"],
            capture_output=True,
            text=True,
        )

        # Parse the URL from status output
        # Output format: "https://<node>.<tailnet>.ts.net -> localhost:PORT"
        public_url = None
        for line in status_result.stdout.splitlines():
            if "->" in line and f"localhost:{port}" in line:
                public_url = line.split("->")[0].strip()
                break

        if not public_url:
            # Fallback: construct from tailnet info
            status_result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
            )
            if status_result.returncode == 0:
                status = json.loads(status_result.stdout)
                tailnet = status.get("CurrentTailnet", {})
                dns_suffix = tailnet.get("MagicDNSSuffix", "")
                node_name = status.get("Self", {}).get("HostName", "")
                if dns_suffix and node_name:
                    public_url = f"https://{node_name}.{dns_suffix}"

        return public_url or "https://<node>.<tailnet>.ts.net"

    async def stop(self, job: Any) -> None:
        """Stop Tailscale Funnel."""
        subprocess.run(["tailscale", "funnel", "off"], capture_output=True)

    def status(self) -> TunnelStatus:
        """Check Tailscale Funnel status."""
        try:
            # Check if tailscale is running
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
            )

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

            # Check funnel status
            funnel_result = subprocess.run(
                ["tailscale", "funnel", "status"],
                capture_output=True,
                text=True,
            )

            running = False
            public_url = None
            if funnel_result.returncode == 0 and funnel_result.stdout.strip():
                running = True
                for line in funnel_result.stdout.splitlines():
                    if "->" in line:
                        public_url = line.split("->")[0].strip()
                        break

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
