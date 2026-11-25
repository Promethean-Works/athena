"""Lazy router for the assistant API.

The assistant API imports pydantic-ai and the whole agent stack (~200 MB, ~1 s cold start,
longer on a Pi). Most hosts don't use it on every request, so this stand-in mounts in its
place and builds the real router on the first assistant request.
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

ASSISTANT_PREFIX = "/api/assistant"


class LazyAssistantRouter:
    """Stand-in that imports the real assistant router on first request."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app
        self._real_router = None
        self._starting: asyncio.Task[ASGIApp] | None = None
        self._openapi_routes = None

    @property
    def routes(self):
        """Return inner routes for OpenAPI schema generation.

        This synchronously builds the routes if not already loaded, so the CLI
        can generate the schema without making an actual request.
        """
        if self._openapi_routes is not None:
            return self._openapi_routes
        return self.get_openapi_routes()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        inner = await self._ensure()
        await inner(scope, receive, send)

    async def _ensure(self) -> ASGIApp:
        if self._starting is None or self._needs_restart(self._starting):
            self._starting = asyncio.create_task(self._start())
        return await asyncio.shield(self._starting)

    def _needs_restart(self, starting: asyncio.Task[ASGIApp]) -> bool:
        if not starting.done():
            return False
        try:
            starting.result()
            return False
        except Exception:
            log.exception("assistant router failed to start, will retry")
            return True

    async def _start(self) -> ASGIApp:
        # Importing the assistant module takes ~1 s (longer on a Pi): not on the event loop.
        module = await asyncio.to_thread(importlib.import_module, "athena.api.assistant")
        # The real router has prefix="/assistant"; we mount at /api/assistant so strip it.
        # Create a new router and copy all routes with the "/assistant" prefix removed.
        from fastapi import APIRouter, FastAPI

        inner_router = APIRouter(prefix="")
        for route in module.router.routes:
            # Create a copy of the route with the "/assistant" prefix stripped
            new_path = route.path
            if new_path.startswith("/assistant"):
                new_path = new_path[len("/assistant") :] or "/"
            inner_router.add_api_route(
                new_path,
                route.endpoint,
                methods=route.methods,
                name=route.name,
                include_in_schema=route.include_in_schema,
                status_code=route.status_code,
                response_model=route.response_model,
                dependencies=route.dependencies,
            )
        # Create a FastAPI app and include the router, sharing the outer app's state
        inner_app = FastAPI()
        inner_app.include_router(inner_router)
        inner_app.state = self._app.state
        return inner_app

    def get_openapi_routes(self):
        """Synchronously build and return the inner routes for OpenAPI schema generation.

        This blocks on the import (unlike the async version) so the CLI can generate
        the schema without making an actual request.
        """
        if self._openapi_routes is not None:
            return self._openapi_routes
        # Synchronous import for schema generation
        module = importlib.import_module("athena.api.assistant")
        from fastapi import APIRouter

        inner_router = APIRouter(prefix="")
        for route in module.router.routes:
            new_path = route.path
            if new_path.startswith("/assistant"):
                new_path = new_path[len("/assistant") :] or "/"
            inner_router.add_api_route(
                new_path,
                route.endpoint,
                methods=route.methods,
                name=route.name,
                include_in_schema=route.include_in_schema,
                status_code=route.status_code,
                response_model=route.response_model,
                dependencies=route.dependencies,
            )
        self._openapi_routes = inner_router.routes
        return self._openapi_routes
