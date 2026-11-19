"""Base classes and types for tunnel providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TunnelStatus:
    """Current tunnel status."""

    running: bool
    public_url: str | None = None
    provider: str | None = None
    detail: str | None = None
    config: dict | None = None


@dataclass(frozen=True)
class TunnelConfig:
    """Configuration for a tunnel provider."""

    port: int = 8420
    provider_config: dict | None = None


class TunnelProvider(ABC):
    """Abstract base class for tunnel providers."""

    @property
    @abstractmethod
    def capability_id(self) -> str:
        """The capability ID this provider implements (e.g., 'tunnel.cloudflare')."""
        pass

    @property
    @abstractmethod
    def label(self) -> str:
        """Human-readable label for the provider."""
        pass

    @abstractmethod
    async def start(self, job: Any, config: TunnelConfig) -> str:
        """Start the tunnel. Returns the public URL."""
        pass

    @abstractmethod
    async def stop(self, job: Any) -> None:
        """Stop the tunnel."""
        pass

    @abstractmethod
    def status(self) -> TunnelStatus:
        """Get current tunnel status."""
        pass

    @abstractmethod
    def get_config_schema(self) -> dict:
        """Return JSON schema for the provider's configuration form."""
        pass

    @abstractmethod
    async def install(self, job: Any) -> None:
        """Download and install the tunnel binary."""
        pass

    @abstractmethod
    async def configure_service(self, job: Any, enabled: bool) -> None:
        """Enable/disable auto-start service (systemd/launchd/Task Scheduler)."""
        pass
