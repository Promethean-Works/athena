"""Backup destinations (docs/specs/backup.md). Admins only."""

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlmodel import select

from athena import audit
from athena.auth.deps import Authed, DbSession
from athena.automation import service as automation_service
from athena.backup import repository, snapshots, versions
from athena.backup.plans import PlanItems, parse_items, parse_retention
from athena.backup.repository import DestinationError
from athena.backup.restic import Repository, ResticError
from athena.backup.service import PlanRunner, ResticProvider, repository_of
from athena.backup.settings import Retention
from athena.containers.runtime import Runtime, RuntimeUnavailableError, runtime_from
from athena.crypto import SecretBox
from athena.db.models import App, BackupDestination, BackupPlan
from athena.downloads import DownloadError
from athena.jobs import JobManager, JobOut
from athena.platform.store import CapabilityStore

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
    allowed_roots = list(settings.backup_allowed_roots)
    try:
        folder = repository.check_local_path(draft.path, data_dir, allowed_roots)
        repository.check_writable(folder, allowed_roots)
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


# ---------------------------------------------------------------- plans


class PlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    destination_id: str
    items: PlanItems
    schedule: str | None = Field(default=None, max_length=120)
    """A cron expression, or empty for manual runs only. Scheduled runs come with part 4."""
    retention: Retention = Field(default_factory=Retention)
    enabled: bool = True


class PlanOut(BaseModel):
    id: str
    name: str
    destination_id: str
    items: PlanItems
    schedule: str | None
    retention: Retention
    enabled: bool
    last_run_at: datetime | None
    last_status: Literal["ok", "failed", "skipped"] | None
    last_error: str | None
    created_at: datetime


def _plan_out(row: BackupPlan) -> PlanOut:
    status_ = row.last_status if row.last_status in ("ok", "failed", "skipped") else None
    return PlanOut(
        id=row.id,
        name=row.name,
        destination_id=row.destination_id,
        items=parse_items(row.items),
        schedule=row.schedule,
        retention=parse_retention(row.retention),
        enabled=row.enabled,
        last_run_at=_aware(row.last_run_at),
        last_status=status_,  # type: ignore[arg-type]
        last_error=row.last_error,
        created_at=_aware(row.created_at) or row.created_at,
    )


def _aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; everything stored here is UTC."""
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def _check_plan(body: PlanIn, db: DbSession, plan_id: str | None = None) -> str | None:
    """Validate a plan; returns the cleaned schedule."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter a name")
    if body.items.is_empty():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pick Athena or at least one app")
    if not body.retention.keeps_something():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Keep at least one version, or every backup would go"
        )
    if db.get(BackupDestination, body.destination_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such destination")
    same = db.exec(select(BackupPlan).where(BackupPlan.name == name)).first()
    if same is not None and same.id != plan_id:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A plan called {name} exists")
    known = set(db.exec(select(App.name)).all())
    missing = [a.name for a in body.items.apps if a.name not in known]
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"No app named {', '.join(sorted(missing))}"
        )
    schedule = (body.schedule or "").strip() or None
    if schedule is not None:
        try:
            automation_service.compute_next_run(schedule, datetime.now(UTC))
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return schedule


def _get_plan(db: DbSession, plan_id: str) -> BackupPlan:
    row = db.get(BackupPlan, plan_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such plan")
    return row


@router.get("/plans", operation_id="listBackupPlans")
def list_plans(user: Authed, db: DbSession) -> list[PlanOut]:
    _require_admin(user)
    return [_plan_out(r) for r in db.exec(select(BackupPlan).order_by(BackupPlan.name)).all()]


@router.post("/plans", operation_id="createBackupPlan", status_code=status.HTTP_201_CREATED)
def create_plan(body: PlanIn, user: Authed, db: DbSession) -> PlanOut:
    _require_admin(user)
    schedule = _check_plan(body, db)
    row = BackupPlan(
        id=uuid.uuid4().hex,
        name=body.name.strip(),
        destination_id=body.destination_id,
        items=body.items.model_dump_json(),
        schedule=schedule,
        retention=body.retention.model_dump_json(),
        enabled=body.enabled,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.record(db, user.user.username, "backup.plan.create", row.name)
    return _plan_out(row)


@router.put("/plans/{plan_id}", operation_id="updateBackupPlan")
def update_plan(plan_id: str, body: PlanIn, user: Authed, db: DbSession) -> PlanOut:
    _require_admin(user)
    row = _get_plan(db, plan_id)
    schedule = _check_plan(body, db, plan_id)
    row.name = body.name.strip()
    row.destination_id = body.destination_id
    row.items = body.items.model_dump_json()
    row.schedule = schedule
    row.retention = body.retention.model_dump_json()
    row.enabled = body.enabled
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.record(db, user.user.username, "backup.plan.update", row.name)
    return _plan_out(row)


@router.delete(
    "/plans/{plan_id}", operation_id="deleteBackupPlan", status_code=status.HTTP_204_NO_CONTENT
)
def delete_plan(plan_id: str, user: Authed, db: DbSession) -> None:
    """Forget a plan. Its backups stay in the destination."""
    _require_admin(user)
    row = _get_plan(db, plan_id)
    db.delete(row)
    db.commit()
    audit.record(db, user.user.username, "backup.plan.delete", row.name)


async def _runtime_or_none(request: Request) -> Runtime | None:
    store: CapabilityStore = request.app.state.capabilities
    manifest = await store.get()
    try:
        return runtime_from(manifest.get("containers"))
    except RuntimeUnavailableError:
        return None


@router.post(
    "/plans/{plan_id}/run", operation_id="runBackupPlan", status_code=status.HTTP_202_ACCEPTED
)
async def run_plan(plan_id: str, request: Request, user: Authed, db: DbSession) -> JobOut:
    """Back up every item of the plan now. Follow progress at /api/jobs/{id}/events."""
    _require_admin(user)
    row = _get_plan(db, plan_id)
    runner = PlanRunner(request.app.state)
    if runner.busy_destination(row.destination_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Another backup to this destination is running"
        )
    items = parse_items(row.items)
    runtime = await _runtime_or_none(request)
    if items.apps and runtime is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Apps can't be backed up safely without a container runtime to stop them",
        )
    jobs: JobManager = request.app.state.jobs
    username = user.user.username

    async def body(job):  # type: ignore[no-untyped-def]
        await runner.run(job, plan_id, username, runtime)

    job = jobs.start(f"Back up {row.name}", body, cancellable=True)
    audit.record(db, username, "backup.plan.run", row.name)
    return job.out()


# ---------------------------------------------------------------- versions


class VersionOut(BaseModel):
    id: str
    destination_id: str
    item: str
    """`athena`, or `app:<name>`."""
    time: datetime
    size: int
    """Bytes the item held when it was backed up."""
    new_bytes: int
    """Bytes this version added to the repository, after deduplication."""
    files_added: int | None
    files_changed: int | None
    files_removed: int | None
    """Against the version before it; null for the first one or when restic couldn't say."""
    athena_version: str | None
    os: str | None
    """`linux`, `darwin` or `windows`: where the version came from."""


class VersionFileOut(BaseModel):
    name: str
    path: str
    kind: Literal["dir", "file", "symlink", "other"]
    size: int | None
    modified: datetime | None


class VersionFilesOut(BaseModel):
    root: str
    """Where the version's files start (the folder that was backed up); `path` is inside it."""
    path: str
    """The folder listed."""
    entries: list[VersionFileOut]


def _destination(db: DbSession, destination_id: str) -> BackupDestination:
    row = db.get(BackupDestination, destination_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such destination")
    return row


async def _readable(request: Request, row: BackupDestination) -> tuple[ResticProvider, Repository]:
    """The destination's repository, after checking it's connected."""
    if not await asyncio.to_thread(snapshots.destination_connected, row.location):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"The destination isn't connected: {row.location} is missing or isn't a backup "
            "repository",
        )
    return _provider(request), repository_of(row, _box(request))


@router.get("/versions", operation_id="listBackupVersions")
async def list_versions(
    request: Request,
    user: Authed,
    db: DbSession,
    destination_id: str | None = None,
    item: str | None = None,
) -> list[VersionOut]:
    """Every version of Athena and the apps, newest first. `destination_id` limits it to one
    destination (a destination that isn't connected is then an error; otherwise it's
    skipped), `item` to `athena` or `app:<name>`."""
    _require_admin(user)
    if item is not None and not versions.ITEM.match(item):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "item is `athena` or `app:<name>`")
    if destination_id is not None:
        rows = [_destination(db, destination_id)]
    else:
        rows = list(db.exec(select(BackupDestination).order_by(BackupDestination.name)).all())
    out: list[VersionOut] = []
    for row in rows:
        try:
            provider, repo = await _readable(request, row)
            tool = await provider.get()
            found = await versions.list_versions(tool, repo, item)
            await versions.add_diffs(tool, repo, found, request.app.state.backup_diffs, row.id)
        except HTTPException:
            if destination_id is not None:
                raise
            continue
        except DownloadError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
        except ResticError as exc:
            if destination_id is not None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
            continue
        out += [
            VersionOut(
                id=v.id,
                destination_id=row.id,
                item=v.item,
                time=v.time,
                size=v.size,
                new_bytes=v.new_bytes,
                files_added=v.files_added,
                files_changed=v.files_changed,
                files_removed=v.files_removed,
                athena_version=v.athena_version,
                os=v.os,
            )
            for v in found
        ]
    out.sort(key=lambda v: v.time, reverse=True)
    return out


@router.get("/versions/{version_id}/files", operation_id="listBackupVersionFiles")
async def list_version_files(
    version_id: str,
    destination_id: str,
    request: Request,
    user: Authed,
    db: DbSession,
    path: str | None = None,
) -> VersionFilesOut:
    """One folder level of a version, read-only. Without `path` it's the version's own folder."""
    _require_admin(user)
    row = _destination(db, destination_id)
    provider, repo = await _readable(request, row)
    try:
        tool = await provider.get()
        root = await versions.snapshot_root(tool, repo, version_id)
        folder = versions.check_path(root, path)
        entries = await versions.list_files(tool, repo, version_id, folder)
    except DownloadError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except ResticError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return VersionFilesOut(
        root=root,
        path=folder,
        entries=[
            VersionFileOut(
                name=e.name,
                path=e.path,
                kind=e.kind,  # type: ignore[arg-type]
                size=e.size,
                modified=e.modified,
            )
            for e in entries
        ],
    )
