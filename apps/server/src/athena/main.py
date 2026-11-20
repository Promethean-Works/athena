"""FastAPI application: the API under /api, and the exported web UI at /."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from athena import __version__
from athena.api import apps, auth, automation, capabilities, containers, jobs, system
from athena.api import assistant as assistant_api
from athena.api import audit as audit_api
from athena.api import cloud as cloud_api
from athena.api import feedback as feedback_api
from athena.api import files as files_api
from athena.api import https as https_api
from athena.api import packages as packages_api
from athena.api import settings as settings_api
from athena.api import shares as shares_api
from athena.api import smb as smb_api
from athena.api import store as store_api
from athena.api import terminal as terminal_api
from athena.api import tunnel as tunnel_api
from athena.api import webdav as webdav_api
from athena.assistant.models_dev import init_models_dev_service
from athena.assistant.providers import ModelCache
from athena.assistant.turns import Turns
from athena.auth.deps import require_user
from athena.auth.service import LoginThrottle
from athena.automation import service as automation_service
from athena.catalog.registry import CatalogRegistry
from athena.cloud.rclone import Rclone
from athena.config import Settings
from athena.crypto import SecretBox
from athena.db import Database
from athena.files.locations import seed_defaults
from athena.files.webdav import WebDavMiddleware
from athena.https.manager import HttpsManager
from athena.https.redirect import HttpsRedirectMiddleware
from athena.jobs import JobManager
from athena.logging_setup import setup_logging
from athena.mcp.auth import MCPAuthMiddleware
from athena.mcp.lazy import MCP_PATH, LazyMCPApp, MCPPathMiddleware
from athena.monitor import HostMonitor
from athena.packages.base import run_command
from athena.platform.store import CapabilityStore
from athena.terminal import shells

if TYPE_CHECKING:
    from pgtask import Worker

log = logging.getLogger(__name__)


async def _refresh_models_dev_cache(app: FastAPI) -> None:
    """Background task to refresh models.dev cache."""
    try:
        from athena.assistant.models_dev import refresh_models_dev_cache

        await refresh_models_dev_cache(app.state.db.session)
    except Exception as e:
        log.warning(f"Failed to refresh models.dev cache: {e}")


def create_app(
    settings: Settings | None = None,
    capability_store: CapabilityStore | None = None,
    catalogs: CatalogRegistry | None = None,
    monitor: HostMonitor | None = None,
    rclone: Rclone | None = None,
) -> FastAPI:
    settings = settings or Settings()
    if settings.log_to_file:
        setup_logging(settings.data_dir)
    store = capability_store or CapabilityStore()
    db = Database(settings.data_dir / "athena.db")
    db.migrate()
    for session in db.session():
        seed_defaults(session, settings.data_dir)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Initialize models.dev service for dynamic provider loading
        init_models_dev_service(db.session)
        # Refresh models.dev cache in background (non-blocking)
        refresh_task = asyncio.create_task(_refresh_models_dev_cache(app))
        # Detect in the background so the server answers immediately; the first
        # GET /api/system/capabilities waits for it if it isn't done yet.
        task = asyncio.create_task(store.get())
        app.state.monitor.start()
        # Automation scheduler: fires enabled cron triggers on their schedule.
        scheduler_task = asyncio.create_task(automation_service.scheduler_loop(app))
        # Durable execution: run assistant turns inside pgtask tasks against Postgres so
        # an interrupted turn resumes from its last checkpointed step. Only started when a
        # database URL is configured; hosts without Postgres run turns inline instead.
        worker: Worker | None = None
        worker_task: asyncio.Task[None] | None = None
        # HTTPS: a second listener on the HTTPS port when it's turned on (never raises).
        await app.state.https.start()
        if settings.durable_execution_database_url:
            from pgtask import Client, TaskRegistry
            from pgtask import Worker as PgWorker

            pgtask_client = await Client.connect(settings.durable_execution_database_url)
            await pgtask_client.migrate()
            registry = TaskRegistry(queue_name="athena-assistant")
            app.state.assistant_turns.pgtask_client = pgtask_client
            app.state.assistant_turns.pgtask_registry = registry
            app.state.assistant_turns.register_pgtask_handlers()
            worker = PgWorker(settings.durable_execution_database_url, registry, poll_interval=1.0)
            worker_task = asyncio.create_task(worker.run())
        yield
        await app.state.https.stop()
        task.cancel()
        scheduler_task.cancel()
        refresh_task.cancel()
        if worker is not None:
            worker.shutdown()
            if worker_task is not None:
                with contextlib.suppress(Exception):
                    await worker_task
        await app.state.assistant_turns.stop_all()
        await mcp.aclose()
        await app.state.monitor.stop()
        await asyncio.to_thread(app.state.rclone.stop)

    app = FastAPI(
        title="Athena",
        version=__version__,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.capabilities = store
    app.state.db = db
    app.state.login_throttle = LoginThrottle()
    app.state.share_throttle = LoginThrottle(limit=10)
    app.state.jobs = JobManager()
    app.state.app_jobs = {}
    app.state.monitor = monitor or HostMonitor()
    app.state.package_runner = run_command
    app.state.package_jobs = {}
    app.state.terminal_shell = shells.host_shell
    app.state.terminal_sessions = {}
    app.state.terminal_session_check = terminal_api.SESSION_CHECK_SECONDS
    # Started on the first cloud call, so hosts that never use it don't run rclone.
    app.state.rclone = rclone or Rclone(settings.data_dir)
    app.state.secret_box = SecretBox(settings.data_dir)
    app.state.model_cache = ModelCache()
    app.state.ai_transport = None  # tests swap in an httpx2.MockTransport
    app.state.assistant_turns = Turns()
    app.state.catalogs = catalogs or CatalogRegistry(remote_root=settings.data_dir / "catalogs")
    # Wakes the automation scheduler when a trigger is created, enabled or edited.
    app.state.automation_event = asyncio.Event()
    app.state.https = HttpsManager(app, settings.host, settings.port, settings.data_dir)
    # Public: /api/health, /api/auth/*, /api/public/shares/{token} (a share link's
    # visitor), POST /api/automation/webhook/{token} (the token is the credential) and
    # /api/mcp (session or ATHENA_MCP_TOKEN bearer, mounted in the lifespan). Everything
    # else needs a signed-in session. /dav/ has its own sign-in.
    app.include_router(system.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(capabilities.router, prefix="/api", dependencies=[require_user])
    app.include_router(jobs.router, prefix="/api", dependencies=[require_user])
    # The runtime router first, so /containers/runtime/start isn't read as a container ref.
    app.include_router(containers.runtime_router, prefix="/api", dependencies=[require_user])
    app.include_router(containers.router, prefix="/api", dependencies=[require_user])
    app.include_router(apps.router, prefix="/api", dependencies=[require_user])
    app.include_router(store_api.router, prefix="/api", dependencies=[require_user])
    app.include_router(settings_api.router, prefix="/api", dependencies=[require_user])
    app.include_router(packages_api.router, prefix="/api", dependencies=[require_user])
    app.include_router(files_api.router, prefix="/api", dependencies=[require_user])
    app.include_router(shares_api.router, prefix="/api", dependencies=[require_user])
    app.include_router(shares_api.public_router, prefix="/api")
    app.include_router(smb_api.router, prefix="/api", dependencies=[require_user])
    app.include_router(webdav_api.router, prefix="/api", dependencies=[require_user])
    app.include_router(cloud_api.router, prefix="/api", dependencies=[require_user])
    app.include_router(assistant_api.router, prefix="/api", dependencies=[require_user])
    app.include_router(automation.router, prefix="/api", dependencies=[require_user])
    # The webhook is public: the trigger's secret token is the credential, so no
    # session is required (n8n, external agents).
    app.include_router(automation.public_router, prefix="/api")
    app.include_router(tunnel_api.router, prefix="/api", dependencies=[require_user])
    app.include_router(feedback_api.router, prefix="/api", dependencies=[require_user])
    app.include_router(audit_api.router, prefix="/api", dependencies=[require_user])
    app.include_router(https_api.router, prefix="/api", dependencies=[require_user])
    # A WebSocket can't use require_user; the route checks the session and CSRF itself.
    app.include_router(terminal_api.router, prefix="/api")
    # MCP server: streamable-HTTP endpoint for external agents (n8n, Claude Desktop, …).
    # Auth is a session cookie or the ATHENA_MCP_TOKEN bearer token. Built on its first
    # request (see athena.mcp.lazy), and mounted before the web UI's "/".
    mcp = LazyMCPApp(app)
    app.mount(MCP_PATH, MCPAuthMiddleware(mcp))

    # A share link opens the UI's /s/ page, which reads the token from the address.
    share_page = settings.web_dir / "s" / "index.html"

    @app.get("/s/{token}", include_in_schema=False)
    @app.get("/s/{token}/", include_in_schema=False)
    def share_page_route(token: str) -> FileResponse:
        if not share_page.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Web UI not bundled")
        # The token is the secret: don't send it to other sites as a Referer.
        return FileResponse(share_page, headers={"Referrer-Policy": "no-referrer"})

    app.add_middleware(WebDavMiddleware, db=db)
    app.add_middleware(MCPPathMiddleware)
    # Outermost, so a browser on the HTTP port is sent to HTTPS before anything else runs.
    app.add_middleware(HttpsRedirectMiddleware, port=lambda: app.state.https.redirect_port)

    # Mounted last so /api routes win. In development the UI is served by `next dev`
    # instead, and this directory doesn't exist.
    if (settings.web_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")
    else:

        @app.get("/", include_in_schema=False)
        def no_web_ui() -> JSONResponse:
            return JSONResponse(
                {
                    "detail": "Web UI not bundled. In development run `pnpm dev` and open "
                    "http://localhost:3000; the API docs are at /api/docs."
                }
            )

    return app
