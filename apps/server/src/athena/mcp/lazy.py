"""The MCP endpoint, built on its first request.

fastmcp (and the MCP SDK under it) costs about 120 MB and most of a second to import, and
many hosts never use the endpoint, so `create_app` mounts this stand-in instead. The first
request builds the real server and starts its lifespan (the streamable-HTTP session
manager) in a task of its own, so the same task enters and exits it; `aclose` ends it when
Athena stops.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI
    from starlette.types import ASGIApp, Receive, Scope, Send

log = logging.getLogger(__name__)

MCP_PATH = "/api/mcp"


class LazyMCPApp:
    def __init__(self, app: FastAPI) -> None:
        self._app = app
        self._starting: asyncio.Task[ASGIApp] | None = None
        """Builds and starts the server; shared by the requests that wait for it."""
        self._runner: asyncio.Task[None] | None = None
        """Holds the server's lifespan open until `_stop` is set."""
        self._stop = asyncio.Event()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        inner = await self._ensure()
        await inner(scope, receive, send)

    async def _ensure(self) -> ASGIApp:
        if self._starting is None or self._needs_restart(self._starting):
            self._starting = asyncio.create_task(self._start())
        # Shielded: a request that goes away mid-start mustn't cancel the shared start.
        return await asyncio.shield(self._starting)

    def _needs_restart(self, starting: asyncio.Task[ASGIApp]) -> bool:
        if not starting.done():
            return False
        if starting.cancelled() or starting.exception() is not None:
            return True  # the requests that waited got the error; try again
        runner = self._runner
        if runner is not None and runner.done():
            if not runner.cancelled() and (exc := runner.exception()) is not None:
                log.error("the MCP server stopped; starting it again", exc_info=exc)
            return True
        return False

    async def _start(self) -> ASGIApp:
        # Importing fastmcp takes a second or more (longer on a Pi): not on the event loop.
        server = await asyncio.to_thread(importlib.import_module, "athena.mcp.server")
        # path="/" so the MCP endpoint is reached at /api/mcp (not /api/mcp/mcp).
        mcp_app = server.build_mcp_server(self._app).http_app(transport="streamable-http", path="/")
        ready = asyncio.Event()
        stop = self._stop

        async def run() -> None:
            async with mcp_app.lifespan(self._app):
                ready.set()
                await stop.wait()

        self._runner = runner = asyncio.create_task(run())
        waiter = asyncio.create_task(ready.wait())
        try:
            await asyncio.wait({runner, waiter}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            waiter.cancel()
        if not ready.is_set():
            runner.result()  # raises the lifespan's error
            raise RuntimeError("the MCP server stopped while starting")
        return mcp_app

    async def aclose(self) -> None:
        """End the server's lifespan (when it was started) and forget it, so a later
        lifespan of the same app starts a fresh one. Never raises: shutdown goes on."""
        self._stop.set()
        starting, runner = self._starting, self._runner
        self._starting = self._runner = None
        self._stop = asyncio.Event()
        for task in (starting, runner):
            if task is None:
                continue
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("the MCP server didn't stop cleanly")


class MCPPathMiddleware:
    """Sends `/api/mcp` to the MCP mount, which only matches `/api/mcp/…`.

    Without it a bare `/api/mcp` falls through to the web UI's "/" mount (405) when the UI
    is bundled; without the UI, Starlette answers with a redirect that not every MCP client
    follows for a POST.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] == MCP_PATH:
            scope = {**scope, "path": MCP_PATH + "/", "raw_path": (MCP_PATH + "/").encode()}
        await self.app(scope, receive, send)
