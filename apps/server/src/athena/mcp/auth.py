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
from urllib.parse import urlsplit

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


def _from_another_origin(request: Request) -> bool:
    """A browser page on another origin (a web app on a sibling port counts) is making this
    request. Browsers always send Origin on a cross-origin POST; other clients have none."""
    origin = request.headers.get("origin")
    if origin is None:
        return False
    # Behind a proxy the browser's address is in X-Forwarded-Host. A page can't forge that
    # header cross-origin: a custom header needs a CORS preflight, which this app never allows.
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    return urlsplit(origin).netloc != host


class MCPAuthMiddleware(BaseHTTPMiddleware):
    """Wraps the MCP streamable-HTTP app and requires a session or bearer token."""

    def __init__(self, app) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        principal: MCPPrincipal | None = None

        token = _bearer_token(request)
        if token:
            expected = os.environ.get("ATHENA_MCP_TOKEN")
            # Bytes: compare_digest raises on a str with non-ASCII characters, which an
            # unauthenticated caller can put in the header (a 500 instead of a 401).
            if expected and secrets.compare_digest(token.encode(), expected.encode()):
                principal = TOKEN_PRINCIPAL
        else:
            session_cookie = request.cookies.get(COOKIE_NAME)
            # The cookie is sent to every port on this host; a page from another origin must
            # not be able to use it (there's no CSRF token on this endpoint).
            if session_cookie and not _from_another_origin(request):
                engine = request.app.state.db.engine
                with Session(engine) as session:
                    found = session_for_token(session, session_cookie)
                if found is not None:
                    _, user = found
                    # MCP tools change the host, so plain users are not let in.
                    if user.is_admin:
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
