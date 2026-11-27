"""NFS shares (docs/specs/network-shares.md): export a file location over the network
from the host's NFS server.

`router` (/api/shares/nfs) is for the signed-in admin: list, create and remove NFS
shares. Creating and removing need the `shares.nfs` capability to be ready.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from athena import audit
from athena.api.files import _fail, _run
from athena.api.netshares import (
    HostPassword,
    release_mount,
    require_share_capability,
    share_elevation,
)
from athena.auth.deps import Authed, DbSession
from athena.db.models import NfsShare
from athena.files import nfs
from athena.files.netshare import with_elevation
from athena.files.paths import FileError

router = APIRouter(prefix="/shares/nfs", tags=["nfs shares"])


class NfsShareOut(BaseModel):
    id: int
    location_id: int
    location_name: str
    path: str
    """The exported folder's absolute path on the host (`host:/path` for clients)."""
    folder: str
    """Where it sits inside the location, `/`-separated; empty for the whole location."""
    clients: list[str]
    read_only: bool
    created_at: datetime


class NfsShareIn(BaseModel):
    location: int
    folder: str = ""
    """A folder inside the location to share, relative to it; empty shares the whole location."""
    clients: Annotated[
        list[Annotated[str, Field(max_length=260)]], Field(max_length=nfs.MAX_CLIENTS)
    ]
    """Who may mount it: IP addresses, networks like 192.168.1.0/24, or host names."""
    read_only: bool = False


def _out(entry: nfs.NfsShareEntry) -> NfsShareOut:
    return NfsShareOut(
        id=entry.id,
        location_id=entry.location_id,
        location_name=entry.location_name,
        path=entry.path,
        folder=entry.folder,
        clients=entry.clients,
        read_only=entry.read_only,
        created_at=entry.created_at,
    )


@router.get("", operation_id="listNfsShares")
def list_nfs_shares(db: DbSession) -> list[NfsShareOut]:
    """The NFS shares Athena created, newest first."""
    return [_out(entry) for entry in nfs.list_shares(db)]


@router.post("", operation_id="createNfsShare", status_code=status.HTTP_201_CREATED)
async def create_nfs_share(
    body: NfsShareIn,
    request: Request,
    user: Authed,
    db: DbSession,
    password: HostPassword = None,
) -> NfsShareOut:
    """Export a location over NFS to the listed clients (501 if the host can't)."""
    cap = await require_share_capability(request, "shares.nfs")
    flavor = nfs.flavor_for(cap.provider)
    elevation = share_elevation(cap, password)
    try:
        entry = await _run(
            with_elevation(
                elevation,
                lambda: nfs.create_share(
                    db,
                    body.location,
                    body.clients,
                    read_only=body.read_only,
                    flavor=flavor,
                    folder=body.folder,
                ),
            )
        )
    except FileError as exc:
        raise _fail(exc) from exc
    audit.record(
        db,
        user.user.username,
        "nfs.share.create",
        f"NFS:{entry.path}",
        f"{entry.location_name} to {', '.join(entry.clients)}",
    )
    return _out(entry)


@router.delete("/{share_id}", operation_id="removeNfsShare", status_code=status.HTTP_204_NO_CONTENT)
async def remove_nfs_share(
    share_id: int,
    request: Request,
    user: Authed,
    db: DbSession,
    password: HostPassword = None,
) -> None:
    """Stop exporting a location and drop its tracking row."""
    share = db.get(NfsShare, share_id)
    if share is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such NFS share")
    location_id = share.location_id
    cap = await require_share_capability(request, "shares.nfs")
    flavor = nfs.flavor_for(cap.provider)
    elevation = share_elevation(cap, password)
    try:
        await _run(with_elevation(elevation, lambda: nfs.remove_share(db, share_id, flavor=flavor)))
    except FileError as exc:
        raise _fail(exc) from exc
    await release_mount(request, db, location_id)
    audit.record(db, user.user.username, "nfs.share.remove", f"NFS:{share.path}")
