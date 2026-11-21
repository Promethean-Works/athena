"""Health and basic host information. Capabilities arrive in milestone M1."""

import asyncio
import platform
import socket
import sys
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from athena import __version__, audit, restart
from athena.auth.deps import Authed, DbSession, require_user
from athena.monitor import HostMonitor, StatsSnapshot

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
