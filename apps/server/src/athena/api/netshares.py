"""Capability gate shared by the SMB and NFS share routes."""

from fastapi import HTTPException, Request, status

from athena.platform.store import CapabilityStore


async def require_share_capability(request: Request, capability_id: str) -> None:
    """501 with the capability's own reason unless the host can create this kind of share."""
    store: CapabilityStore = request.app.state.capabilities
    cap = (await store.get()).get(capability_id)
    if cap is None or cap.status != "ready":
        detail = cap.detail if cap and cap.detail else "This host can't create these shares"
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail)
