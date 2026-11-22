"""Health and basic host information. Capabilities arrive in milestone M1."""

import asyncio
import platform
import socket
import sys
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from athena import __version__, audit, restart, self_update
from athena.auth.deps import Authed, DbSession, require_user
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


EXIT_DELAY_SECONDS = 0.5


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
    data_dir = app.state.settings.data_dir
    running: Job | None = getattr(app.state, "update_job", None)
    if (
        (running is not None and running.status == "running")
        or restart.exit_requested()
        or self_update.lock_holder(self_update.Paths(data_dir)) is not None
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "An update is already running")
    opts = self_update.Options(
        data_dir=data_dir, version=body.version, check_url=app.state.settings.update_check_url
    )
    loop = asyncio.get_running_loop()

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
            await self_update.run_from_server(opts, say, handoff)
        except self_update.UpdateError as exc:
            raise RuntimeError(str(exc)) from exc
        finally:
            await asyncio.sleep(0)  # let the queued log lines land before the job ends
            if pending:
                await asyncio.gather(*pending)

    job = app.state.jobs.start("Update Athena", run)
    app.state.update_job = job
    audit.record(db, user.user.username, "system.update.start", body.version or "latest")
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
