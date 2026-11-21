"""Backup destinations (docs/specs/backup.md). Admins only."""

import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlmodel import select

from athena import audit
from athena.auth.deps import Authed, DbSession
from athena.backup import repository
from athena.backup.repository import DestinationError
from athena.backup.restic import Repository, ResticError
from athena.backup.service import ResticProvider
from athena.crypto import SecretBox
from athena.db.models import BackupDestination, BackupPlan
from athena.downloads import DownloadError

router = APIRouter(prefix="/backup", tags=["backup"])


def _require_admin(user: Authed) -> None:
    if not user.user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can manage backups")


def _provider(request: Request) -> ResticProvider:
    return request.app.state.restic


def _box(request: Request) -> SecretBox:
    return request.app.state.secret_box


class DestinationOut(BaseModel):
    id: str
    name: str
    kind: Literal["local", "rclone"]
    location: str
    """The folder, or `<remote>:<path>` on an rclone remote."""
    created_at: datetime


class DestinationDraft(BaseModel):
    """What the admin typed; the recovery kit is made from it before anything is created."""

    name: str = Field(min_length=1, max_length=64)
    kind: Literal["local"] = "local"
    path: str
    """The folder or disk to keep the repository in."""
    password: str | None = None
    """Their own repository password; empty means Athena generates a strong one."""


class RecoveryKit(BaseModel):
    name: str
    location: str
    password: str
    """Shown once. Athena only keeps an encrypted copy, and never returns it again."""
    kit: str
    """The text of the recovery kit file."""
    filename: str


class DestinationIn(DestinationDraft):
    password: str
    recovery_kit_saved: bool
    """The admin ticked "I saved this". Required: without the kit a dead host can't restore."""


def _out(row: BackupDestination) -> DestinationOut:
    return DestinationOut(
        id=row.id,
        name=row.name,
        kind="rclone" if row.kind == "rclone" else "local",
        location=row.location,
        created_at=row.created_at,
    )


def _location(request: Request, draft: DestinationDraft) -> str:
    """The checked, writable folder for a draft, as the text stored in the database."""
    settings = request.app.state.settings
    data_dir: Path = settings.data_dir
    allowed_raw = getattr(settings, "backup_local_allowed_roots", []) or []
    allowed_roots = [Path(p) for p in allowed_raw]
    try:
        folder = repository.check_local_path(draft.path, data_dir, allowed_roots)
        repository.check_writable(folder)
    except DestinationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return str(folder)


def _password(draft: DestinationDraft) -> str:
    try:
        if draft.password:
            return repository.check_password(draft.password)
    except DestinationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return repository.generate_password()


@router.get("/destinations", operation_id="listBackupDestinations")
def list_destinations(user: Authed, db: DbSession) -> list[DestinationOut]:
    _require_admin(user)
    rows = db.exec(select(BackupDestination).order_by(BackupDestination.name)).all()
    return [_out(r) for r in rows]


@router.post("/destinations/recovery-kit", operation_id="createBackupRecoveryKit")
def recovery_kit(draft: DestinationDraft, request: Request, user: Authed) -> RecoveryKit:
    """Check a destination and make its recovery kit, without creating anything yet."""
    _require_admin(user)
    location = _location(request, draft)
    password = _password(draft)
    return RecoveryKit(
        name=draft.name.strip(),
        location=location,
        password=password,
        kit=repository.recovery_kit(draft.name.strip(), location, password),
        filename=repository.kit_filename(draft.name),
    )


@router.post(
    "/destinations",
    operation_id="createBackupDestination",
    status_code=status.HTTP_201_CREATED,
)
async def create_destination(
    body: DestinationIn, request: Request, user: Authed, db: DbSession
) -> DestinationOut:
    """Create the repository (or open an existing one, which is how a new host finds old
    backups) and keep its password, encrypted, for scheduled runs."""
    _require_admin(user)
    if not body.recovery_kit_saved:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Save the recovery kit first: without it a lost server means unreadable backups",
        )
    name = body.name.strip()
    location = _location(request, body)
    password = _password(body)
    if db.exec(select(BackupDestination).where(BackupDestination.name == name)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"A destination called {name} exists")
    if db.exec(select(BackupDestination).where(BackupDestination.location == location)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "That folder is already a destination")
    try:
        tool = await _provider(request).get()
        created = await repository.init_or_open(tool, Repository(location, password))
    except DownloadError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except ResticError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    row = BackupDestination(
        id=uuid.uuid4().hex,
        name=name,
        kind="local",
        location=location,
        password=_box(request).encrypt(password),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.record(
        db,
        user.user.username,
        "backup.destination.create",
        name,
        "new repository" if created else "opened an existing repository",
    )
    return _out(row)


@router.delete(
    "/destinations/{destination_id}",
    operation_id="deleteBackupDestination",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_destination(
    destination_id: str,
    user: Authed,
    db: DbSession,
    delete_backups: bool = False,
) -> None:
    """Forget a destination. The backups stay where they are unless `delete_backups`."""
    _require_admin(user)
    row = db.get(BackupDestination, destination_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such destination")
    in_use = db.exec(select(BackupPlan).where(BackupPlan.destination_id == row.id)).first()
    if in_use is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"The plan {in_use.name} uses this destination"
        )
    if delete_backups:
        try:
            await asyncio.to_thread(repository.delete_repository, Path(row.location))
        except DestinationError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR, f"Couldn't delete the backups: {exc}"
            ) from exc
    db.delete(row)
    db.commit()
    audit.record(
        db,
        user.user.username,
        "backup.destination.delete",
        row.name,
        "backups deleted" if delete_backups else "backups kept",
    )
