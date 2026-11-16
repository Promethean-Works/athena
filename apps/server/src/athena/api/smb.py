"""SMB shares (docs/mvp-design.md §4.3): publish a file location over the network
via the host's Samba server.

`router` (/api/shares/smb) is for the signed-in admin: list, create and remove SMB
shares. Only Linux is wired (Athena edits /etc/samba/smb.conf and reloads smbd);
macOS and Windows report the capability as unsupported until their share creation
is wired.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from athena import audit
from athena.api.files import _fail, _run
from athena.auth.deps import Authed, DbSession
from athena.db.models import SmbShare
from athena.files import smb

router = APIRouter(prefix="/shares/smb", tags=["smb shares"])


class SmbShareOut(BaseModel):
    id: int
    name: str
    """The share name as it appears on the network (\\\\server\\name)."""
    location_id: int
    location_name: str
    path: str
    """The shared folder's absolute path on the host."""
    read_only: bool
    guest_ok: bool
    created_at: datetime


class SmbShareIn(BaseModel):
    location: int
    name: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")]
    """The share name as it appears on the network."""
    read_only: bool = False
    guest_ok: bool = False


def _out(entry: smb.SmbShareEntry) -> SmbShareOut:
    return SmbShareOut(
        id=entry.id,
        name=entry.name,
        location_id=entry.location_id,
        location_name=entry.location_name,
        path=entry.path,
        read_only=entry.read_only,
        guest_ok=entry.guest_ok,
        created_at=entry.created_at,
    )


@router.get("", operation_id="listSmbShares")
def list_smb_shares(db: DbSession) -> list[SmbShareOut]:
    """The SMB shares Athena created, newest first."""
    return [_out(entry) for entry in smb.list_shares(db)]


@router.post("", operation_id="createSmbShare", status_code=status.HTTP_201_CREATED)
async def create_smb_share(body: SmbShareIn, user: Authed, db: DbSession) -> SmbShareOut:
    """Share a location over SMB. On Linux this writes a section to
    /etc/samba/smb.conf and reloads smbd; on other operating systems it's 501."""
    try:
        entry = await _run(
            lambda: smb.create_share(
                db,
                body.location,
                body.name,
                read_only=body.read_only,
                guest_ok=body.guest_ok,
            )
        )
    except smb.SmbUnsupported as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, exc.message) from exc
    except smb.FileError as exc:
        raise _fail(exc) from exc
    audit.record(
        db,
        user.user.username,
        "smb.share.create",
        f"SMB:{body.name}",
        f"{entry.location_name} ({entry.path})",
    )
    return _out(entry)


@router.delete("/{share_id}", operation_id="removeSmbShare", status_code=status.HTTP_204_NO_CONTENT)
async def remove_smb_share(share_id: int, user: Authed, db: DbSession) -> None:
    """Remove an SMB share: drop its smb.conf section and the tracking row."""
    share = db.get(SmbShare, share_id)
    if share is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such SMB share")
    try:
        await _run(lambda: smb.remove_share(db, share_id))
    except smb.SmbUnsupported as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, exc.message) from exc
    audit.record(db, user.user.username, "smb.share.remove", f"SMB:{share.name}")
