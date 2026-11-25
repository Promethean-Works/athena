"""Health and basic host information. Capabilities arrive in milestone M1."""

import asyncio
import platform
import socket
import sys
import time
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from athena import __version__, audit, restart, self_update
from athena.auth.deps import Authed, DbSession, require_user
from athena.backup.service import PlanRunner, athena_plan
from athena.jobs import Job, JobOut
from athena.monitor import HostMonitor, StatsSnapshot
from athena.updates import UpdateInfo, enabled

router = APIRouter(tags=["system"])

OsName = Literal["linux", "darwin", "windows"]


class Health(BaseModel):
    status: Literal["ok"]
    version: str
    started_at: datetime
    """When this server process started; a change tells the UI a restart finished."""


class SystemInfo(BaseModel):
    version: str
    os: OsName
    os_version: str
    arch: str
    hostname: str
    python: str


def current_os() -> OsName:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "darwin"
    return "windows"


@router.get("/health", operation_id="getHealth")
def health(request: Request) -> Health:
    return Health(status="ok", version=__version__, started_at=request.app.state.started_at)


async def _restart_soon() -> None:
    # After the 202 has been sent; uvicorn's graceful shutdown then waits for open requests.
    await asyncio.sleep(0.5)
    restart.request()


@router.post(
    "/system/restart",
    operation_id="restartAthena",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[require_user],
)
def restart_athena(user: Authed, db: DbSession, tasks: BackgroundTasks) -> None:
    """Stop the server; the `athena serve` supervisor starts a new one (admins only)."""
    if not user.user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can restart Athena")
    if not restart.available():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This Athena wasn't started by `athena serve`, so it can't restart itself",
        )
    audit.record(db, user.user.username, "system.restart", "athena")
    tasks.add_task(_restart_soon)


@router.get("/system/info", operation_id="getSystemInfo", dependencies=[require_user])
def system_info() -> SystemInfo:
    os_name = current_os()
    if os_name == "darwin":
        os_version = f"macOS {platform.mac_ver()[0]}"
    elif os_name == "windows":
        os_version = f"Windows {platform.release()} ({platform.version()})"
    else:
        try:
            release = platform.freedesktop_os_release()
            os_version = release.get("PRETTY_NAME", f"Linux {platform.release()}")
        except OSError:
            os_version = f"Linux {platform.release()}"
    return SystemInfo(
        version=__version__,
        os=os_name,
        os_version=os_version,
        arch=platform.machine().lower(),
        hostname=socket.gethostname(),
        python=platform.python_version(),
    )


@router.get("/system/update", operation_id="getUpdateInfo", dependencies=[require_user])
def update_info(request: Request) -> UpdateInfo:
    """Whether a newer Athena release is out, from the daily check (no network call here)."""
    app = request.app
    return app.state.updates.info(enabled(app) and bool(app.state.settings.update_check_url))


class StartUpdate(BaseModel):
    version: str | None = Field(default=None, pattern=r"^\d+\.\d+\.\d+([-.]?(a|b|rc)\.?\d+)?$")
    """A specific release; the latest stable one when omitted."""
    backup: bool = False
    """Back up Athena first, with the first enabled backup plan that includes it. When the
    backup fails the job fails before anything is downloaded; ask again without it to go on."""


EXIT_DELAY_SECONDS = 0.5
BACKUP_FAILED = "The backup failed"
"""Starts the error of a job whose backup failed; the UI offers to update anyway."""
START_INTERVAL_SECONDS = 60.0
"""One accepted update start per minute: it interrupts service, so don't let it be hammered."""


class UpdateStatus(BaseModel):
    phase: str
    """`idle` (no update yet), `preparing` (the server is downloading and checking), then the
    helper's phases while Athena is swapped (`stopping`, `installing`, `starting`, `checking`,
    `rolling_back`) and its last word: `done`, `rolled_back`, `failed` or `aborted`. `interrupted`
    is an update that began, whose helper is gone without a last word (killed, power cut)."""
    step: str | None = None
    from_version: str | None = None
    to_version: str | None = None
    started_at: datetime | None = None
    error: str | None = None
    log_tail: list[str] = Field(default_factory=list)
    job_id: str | None = None
    """The job that downloads and checks the release, while it runs."""
    running_jobs: list[str] = Field(default_factory=list)
    """Titles of the jobs a restart would stop (the update job itself is left out)."""
    terminals: int = 0
    """Open web terminal sessions, which a restart closes."""
    backup_plan: str | None = None
    """Name of the backup plan "Back up Athena first" would run; None when backup isn't ready
    or no enabled plan includes Athena."""


def _parse_time(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


@router.get(
    "/system/update/status",
    operation_id="getUpdateStatus",
    dependencies=[require_user],
)
async def update_status(request: Request, user: Authed, db: DbSession) -> UpdateStatus:
    """What the last update did, from the helper's state file (admins only). The helper
    outlives the server, so this is what the page reads once Athena is back."""
    if not user.user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can see the update status")
    app = request.app
    paths = self_update.Paths(app.state.settings.data_dir)
    state = self_update.read_state(paths) or {}
    job: Job | None = getattr(app.state, "update_job", None)
    preparing = job is not None and job.status == "running"
    phase = str(state.get("phase") or "idle")
    if preparing:
        phase = "preparing"
    elif (
        phase not in ("idle", *self_update.TERMINAL_PHASES)
        and self_update.lock_holder(paths) is None
    ):
        phase = "interrupted"  # the helper died mid-swap, or the host lost power
    backup = (await app.state.capabilities.get()).get("backup")
    plan = athena_plan(db) if backup is not None and backup.available else None
    tail = state.get("log_tail")
    others = [j.title for j in app.state.jobs.running() if j is not job]
    return UpdateStatus(
        phase=phase,
        step=state.get("step") if not preparing else None,
        from_version=state.get("from"),
        to_version=state.get("to"),
        started_at=_parse_time(state.get("started_at")),
        error=state.get("error") or None,
        log_tail=[str(line) for line in tail] if isinstance(tail, list) else [],
        job_id=job.id if preparing and job is not None else None,
        running_jobs=others,
        terminals=len(app.state.terminal_sessions),
        backup_plan=plan.name if plan is not None else None,
    )


@router.post(
    "/system/update",
    operation_id="startUpdate",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[require_user],
)
async def start_update(body: StartUpdate, request: Request, user: Authed, db: DbSession) -> JobOut:
    """Download and check a release, then hand over to the helper, which swaps Athena while
    the server is stopped (admins only). Follow the job at /api/jobs/{id}/events."""
    if not user.user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can update Athena")
    app = request.app
    capability = (await app.state.capabilities.get()).get("self_update")
    if capability is None or not capability.available:
        reason = capability.detail if capability else None
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            reason or "This Athena can't update itself",
        )
    plan = None
    if body.backup:
        backup = (await app.state.capabilities.get()).get("backup")
        plan = athena_plan(db) if backup is not None and backup.available else None
        if plan is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "There's no backup plan that includes Athena to back up first",
            )
        runner = PlanRunner(app.state)
        if runner.busy_destination(plan.destination_id):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Another backup to this destination is running"
            )
    backup_plan_id = plan.id if plan is not None else None
    data_dir = app.state.settings.data_dir
    running: Job | None = getattr(app.state, "update_job", None)
    if (
        (running is not None and running.status == "running")
        or restart.exit_requested()
        or self_update.lock_holder(self_update.Paths(data_dir)) is not None
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "An update is already running")
    last: float | None = app.state.update_started_at
    if last is not None and time.monotonic() - last < START_INTERVAL_SECONDS:
        wait = max(1, round(START_INTERVAL_SECONDS - (time.monotonic() - last)))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"An update was just started. Try again in {wait} seconds.",
            headers={"Retry-After": str(wait)},
        )
    app.state.update_started_at = time.monotonic()
    opts = self_update.Options(
        data_dir=data_dir, version=body.version, check_url=app.state.settings.update_check_url
    )
    loop = asyncio.get_running_loop()
    username = user.user.username

    async def run(job: Job) -> None:
        pending: set[asyncio.Task[None]] = set()

        def say(line: str) -> None:  # also called from worker threads
            def add() -> None:
                task = loop.create_task(job.log(line))
                pending.add(task)
                task.add_done_callback(pending.discard)

            loop.call_soon_threadsafe(add)

        def handoff() -> None:
            loop.call_later(EXIT_DELAY_SECONDS, restart.request_exit)

        try:
            if backup_plan_id is not None:
                await job.log("Backing up Athena first")
                try:
                    await PlanRunner(app.state).run(
                        job, backup_plan_id, username, None, only_athena=True
                    )
                except Exception as exc:
                    app.state.update_started_at = None  # a retry without the backup is allowed
                    raise RuntimeError(f"{BACKUP_FAILED}: {exc}") from exc
            await self_update.run_from_server(opts, say, handoff)
        except self_update.UpdateError as exc:
            raise RuntimeError(str(exc)) from exc
        finally:
            await asyncio.sleep(0)  # let the queued log lines land before the job ends
            if pending:
                await asyncio.gather(*pending)

    job = app.state.jobs.start("Update Athena", run)
    app.state.update_job = job
    audit.record(
        db,
        user.user.username,
        "system.update.start",
        "athena",
        f"{body.version or 'latest'} via ui" + (" (backup first)" if plan is not None else ""),
    )
    return job.out()


def _monitor(request: Request) -> HostMonitor:
    return request.app.state.monitor


@router.get("/system/stats", operation_id="getSystemStats", dependencies=[require_user])
async def system_stats(request: Request) -> StatsSnapshot:
    """Current host stats plus up to an hour of samples for sparklines."""
    return await _monitor(request).snapshot()


@router.get(
    "/system/stats/stream",
    operation_id="streamSystemStats",
    dependencies=[require_user],
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
def stream_system_stats(request: Request) -> StreamingResponse:
    """Server-Sent Events: a `stats` event (`HostStats` JSON) after every new sample."""
    # No CORS headers: the UI is always same-origin (FastAPI in production, the
    # `next dev` proxy in development). Echoing Origin with credentials let any page
    # on the same site (an installed app on another port) read the stream.
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(
        _monitor(request).events(),
        media_type="text/event-stream",
        headers=headers,
    )
