"""Authentication for the MCP server.

A request is authenticated either with a bearer token (`ATHENA_MCP_TOKEN`
environment variable, for headless clients such as n8n's MCP client node or
external agents) or with Athena's session cookie (for browser-based MCP
clients). The authenticated username is exposed to tools through
`mcp_current_user`.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from contextvars import ContextVar

from sqlmodel import Session
from starlette import status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from athena.auth.service import session_for_token

COOKIE_NAME = "athena_session"
BEARER_PREFIX = "Bearer "

mcp_current_user: ContextVar[str | None] = ContextVar("mcp_current_user", default=None)


def _bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if not auth.startswith(BEARER_PREFIX):
        return None
    return auth[len(BEARER_PREFIX) :].strip()


class MCPAuthMiddleware(BaseHTTPMiddleware):
    """Wraps the MCP streamable-HTTP app and requires a session or bearer token."""

    def __init__(self, app) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        username: str | None = None

        token = _bearer_token(request)
        if token:
            expected = os.environ.get("ATHENA_MCP_TOKEN")
            if expected and secrets.compare_digest(token, expected):
                username = "mcp-client"
        else:
            session_cookie = request.cookies.get(COOKIE_NAME)
            if session_cookie:
                engine = request.app.state.db.engine
                with Session(engine) as session:
                    found = session_for_token(session, session_cookie)
                if found is not None:
                    _, user = found
                    username = user.username

        if username is None:
            return JSONResponse(
                {"error": "Not authenticated"}, status_code=status.HTTP_401_UNAUTHORIZED
            )

        token_var = mcp_current_user.set(username)
        try:
            return await call_next(request)
        finally:
            mcp_current_user.reset(token_var)


def require_mcp_user() -> str:
    """Return the authenticated username for the current MCP request, or raise."""
    username = mcp_current_user.get()
    if username is None:
        from fastapi import HTTPException, status

        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return username
