"""Cloud folders mounted for sharing (docs/specs/share-from-explorer.md): mount a remote
so the SMB and NFS shares can publish it, and list or unmount those mounts.

Needs the `cloud.mount` capability (rclone that can mount, plus the OS's FUSE driver).
"""

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from athena import audit
from athena.api.files import _fail
from athena.auth.deps import Authed, DbSession
from athena.cloud import mounts
from athena.db.models import RemoteMount
from athena.files.paths import FileError
from athena.platform.capabilities import Capability

router = APIRouter(prefix="/cloud/mounts", tags=["cloud mounts"])


class MountIn(BaseModel):
    remote: str
    path: str = ""
    """Folder inside the remote; empty for its top."""
    read_only: bool = True


class MountOut(BaseModel):
    id: int
    remote: str
    path: str
    location_id: int
    """The hidden file location at the mount point; share this one over SMB or NFS."""
    read_only: bool


def _out(mount: RemoteMount) -> MountOut:
    return MountOut(
        id=mount.id,  # type: ignore[arg-type]
        remote=mount.remote,
        path=mount.path,
        location_id=mount.location_id,
        read_only=mount.read_only,
    )


async def _capability(request: Request) -> Capability:
    cap = (await request.app.state.capabilities.get()).get("cloud.mount")
    if cap is None or cap.status != "ready":
        detail = cap.detail if cap and cap.detail else "This host can't mount cloud storage"
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail)
    return cap


@router.get("", operation_id="listCloudMounts")
def list_cloud_mounts(db: DbSession) -> list[MountOut]:
    return [_out(m) for m in mounts.list_mounts(db)]


@router.post("", operation_id="mountCloudFolder", status_code=status.HTTP_201_CREATED)
async def mount_cloud_folder(
    body: MountIn, request: Request, user: Authed, db: DbSession
) -> MountOut:
    """Mount a remote folder on this computer (or return the mount that exists)."""
    if not user.user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can mount cloud storage")
    cap = await _capability(request)
    state = request.app.state
    try:
        mount = await mounts.ensure(
            db,
            state.rclone,
            state.settings.data_dir,
            body.remote,
            body.path,
            read_only=body.read_only,
            provider=cap.provider,
        )
    except FileError as exc:
        raise _fail(exc) from exc
    audit.record(db, user.user.username, "cloud.mount", f"{mount.remote}:{mount.path}")
    return _out(mount)


@router.delete(
    "/{mount_id}", operation_id="unmountCloudFolder", status_code=status.HTTP_204_NO_CONTENT
)
async def unmount_cloud_folder(
    mount_id: int, request: Request, user: Authed, db: DbSession
) -> None:
    """Unmount a cloud folder. 409 while a share still uses it."""
    if not user.user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can mount cloud storage")
    mount = db.get(RemoteMount, mount_id)
    if mount is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such mount")
    try:
        await mounts.unmount(db, request.app.state.rclone, mount)
    except FileError as exc:
        raise _fail(exc) from exc
    audit.record(db, user.user.username, "cloud.unmount", f"{mount.remote}:{mount.path}")
