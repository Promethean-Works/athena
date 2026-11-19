"""Tunnel provider registry."""

from athena.tunnel.base import TunnelProvider
from athena.tunnel.cloudflare import CloudflareTunnelProvider
from athena.tunnel.ngrok import NgrokTunnelProvider
from athena.tunnel.tailscale import TailscaleTunnelProvider

# Registry of tunnel providers keyed by capability ID
TUNNEL_PROVIDERS: dict[str, TunnelProvider] = {
    "tunnel.cloudflare": CloudflareTunnelProvider(),
    "tunnel.tailscale": TailscaleTunnelProvider(),
    "tunnel.ngrok": NgrokTunnelProvider(),
}


def get_provider(capability_id: str) -> TunnelProvider | None:
    """Get tunnel provider by capability ID."""
    return TUNNEL_PROVIDERS.get(capability_id)


def get_all_providers() -> list[TunnelProvider]:
    """Get all tunnel providers."""
    return list(TUNNEL_PROVIDERS.values())


__all__ = [
    "TUNNEL_PROVIDERS",
    "TunnelProvider",
    "get_all_providers",
    "get_provider",
]
