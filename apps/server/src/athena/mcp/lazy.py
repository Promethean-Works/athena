"""The MCP endpoint, built on its first request.

fastmcp (and the MCP SDK under it) costs about 120 MB and most of a second to import, and
many hosts never use the endpoint, so `create_app` mounts this stand-in instead. The first
request builds the real server and starts its lifespan (the streamable-HTTP session
manager) in a task of its own, so the same task enters and exits it; `aclose` ends it when
Athena stops.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI
    from starlette.types import ASGIApp, Receive, Scope, Send

MCP_PATH = "/api/mcp"


class LazyMCPApp:
    def __init__(self, app: FastAPI) -> None:
        self._app = app
        self._inner: ASGIApp | None = None
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._runner: asyncio.Task[None] | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        inner = self._inner or await self._start()
        await inner(scope, receive, send)

    async def _start(self) -> ASGIApp:
        async with self._lock:
            if self._inner is not None:
                return self._inner
            from athena.mcp.server import build_mcp_server

            # path="/" so the MCP endpoint is reached at /api/mcp (not /api/mcp/mcp).
            mcp_app = build_mcp_server(self._app).http_app(transport="streamable-http", path="/")
            ready = asyncio.Event()

            async def run() -> None:
                async with mcp_app.lifespan(self._app):
                    ready.set()
                    await self._stop.wait()

            runner = asyncio.create_task(run())
            waiter = asyncio.create_task(ready.wait())
            await asyncio.wait({runner, waiter}, return_when=asyncio.FIRST_COMPLETED)
            if runner.done():  # the lifespan failed before it was ready
                waiter.cancel()
                runner.result()
            self._runner = runner
            self._inner = mcp_app
            return mcp_app

    async def aclose(self) -> None:
        self._stop.set()
        if self._runner is not None:
            await self._runner


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
