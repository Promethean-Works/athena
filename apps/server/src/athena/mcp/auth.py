"""Authentication for the MCP server.

A request is authenticated either with a bearer token (`ATHENA_MCP_TOKEN`
environment variable, for headless clients such as n8n's MCP client node or
external agents) or with Athena's session cookie (for browser-based MCP
clients). The authenticated principal is exposed to tools through
`mcp_current_user`.

A token client has no account of its own: it acts as the admin user (the
oldest admin in `users`, resolved per tool call by `athena.mcp.server`), and
its audit rows say they came through the MCP token.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass

from sqlmodel import Session
from starlette import status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from athena.auth.service import session_for_token

COOKIE_NAME = "athena_session"
BEARER_PREFIX = "Bearer "


@dataclass(frozen=True)
class MCPPrincipal:
    """Who is calling: a signed-in user, or a client holding `ATHENA_MCP_TOKEN`."""

    username: str | None
    """The session's username; None for token clients (they act as the admin)."""
    via_token: bool = False


TOKEN_PRINCIPAL = MCPPrincipal(username=None, via_token=True)

mcp_current_user: ContextVar[MCPPrincipal | None] = ContextVar("mcp_current_user", default=None)


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
        principal: MCPPrincipal | None = None

        token = _bearer_token(request)
        if token:
            expected = os.environ.get("ATHENA_MCP_TOKEN")
            if expected and secrets.compare_digest(token, expected):
                principal = TOKEN_PRINCIPAL
        else:
            session_cookie = request.cookies.get(COOKIE_NAME)
            if session_cookie:
                engine = request.app.state.db.engine
                with Session(engine) as session:
                    found = session_for_token(session, session_cookie)
                if found is not None:
                    _, user = found
                    principal = MCPPrincipal(username=user.username)

        if principal is None:
            return JSONResponse(
                {"error": "Not authenticated"}, status_code=status.HTTP_401_UNAUTHORIZED
            )

        token_var = mcp_current_user.set(principal)
        try:
            return await call_next(request)
        finally:
            mcp_current_user.reset(token_var)


def require_mcp_user() -> MCPPrincipal:
    """Return the authenticated principal for the current MCP request, or raise."""
    principal = mcp_current_user.get()
    if principal is None:
        from fastapi import HTTPException, status

        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return principal
