"""Capability gate and elevation shared by the SMB and NFS share routes."""

from typing import Annotated

from fastapi import Header, HTTPException, Request, status
from sqlmodel import Session

from athena.files.netshare import Elevation
from athena.platform.capabilities import Capability
from athena.platform.store import CapabilityStore

HostPassword = Annotated[
    str | None,
    Header(
        alias="X-Host-Password",
        description="The host account's password, for a share that needs root (macOS). "
        "Used for this request only; never stored or logged.",
    ),
]


async def require_share_capability(request: Request, capability_id: str) -> Capability:
    """The usable capability (`provider` picks the flavour), or 501 with its own reason.

    `needs_privilege` counts as usable when Athena can ask for the rights (`elevation`)."""
    store: CapabilityStore = request.app.state.capabilities
    cap = (await store.get()).get(capability_id)
    usable = cap is not None and (
        cap.status == "ready" or (cap.status == "needs_privilege" and cap.elevation is not None)
    )
    if cap is None or not usable:
        detail = cap.detail if cap and cap.detail else "This host can't create these shares"
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail)
    return cap


def share_elevation(cap: Capability, password: str | None) -> Elevation | None:
    """How to run this share action: `None` when Athena already has the rights."""
    if cap.status == "ready":
        return None
    if cap.elevation == "system":
        return Elevation("uac")
    if not password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Enter your computer's password to continue")
    return Elevation("sudo", password)


async def release_mount(request: Request, db: Session, location_id: int) -> None:
    """After removing a share: unmount its cloud folder if no other share needs it."""
    from athena.cloud import mounts

    await mounts.release_if_unused(db, request.app.state.rclone, location_id)
