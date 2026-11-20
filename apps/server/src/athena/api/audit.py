"""The audit log, read-only, for the dashboard's Recent activity card (admins only)."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import col, select

from athena.auth.deps import Authed, DbSession
from athena.db.models import AuditEntry

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEntryOut(BaseModel):
    """`detail` is left out on purpose: it can hold a shell command or a path the
    user typed, and the dashboard only needs who did what to which target."""

    id: int
    at: datetime
    username: str
    action: str
    target: str | None


@router.get("", operation_id="listAuditEntries")
def list_entries(
    user: Authed,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[AuditEntryOut]:
    """The newest entries first."""
    if not user.user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can read the audit log")
    rows = db.exec(
        select(AuditEntry)
        .order_by(col(AuditEntry.at).desc(), col(AuditEntry.id).desc())
        .limit(limit)
    ).all()
    return [
        AuditEntryOut(id=r.id or 0, at=r.at, username=r.username, action=r.action, target=r.target)
        for r in rows
    ]
