"""Sends browsers on the HTTP port to the HTTPS listener.

307, not 308: it keeps the method like 308, but browsers don't cache it as permanent, so
turning HTTPS off later doesn't leave them stuck on a port that's gone.

Only page loads are redirected: GET or HEAD outside `/api/` and `/dav`, that a browser
sends as a navigation (`Sec-Fetch-Mode: navigate`, or `Accept: text/html` from browsers
too old to send it). Everything else on the HTTP port keeps working as before: API calls
from a page already open over HTTP (a cross-origin redirect would fail CORS), WebDAV
mounts, MCP clients, automation webhooks, and store apps calling Athena from a container
(they come from a bridge address and wouldn't trust the certificate).

Also never redirected, so there's always a way back in:
- requests from the host itself (`curl http://127.0.0.1:8420`, the CLI, service checks);
- requests that came through a local proxy or tunnel (they carry `X-Forwarded-*` or
  `Forwarded`; uvicorn has already swapped the client for the visitor's address, and the
  tunnel terminates TLS itself);
- WebSockets (a redirect can't be followed there).
"""

import ipaddress
from collections.abc import Callable

from starlette.types import ASGIApp, Receive, Scope, Send

from athena.https.settings import valid_hostname

_PROXY_HEADERS = (b"x-forwarded-for", b"x-forwarded-proto", b"forwarded")
_SKIP_PREFIXES = ("/api/", "/dav/")
_SKIP_PATHS = ("/api", "/dav")


def _is_page_load(scope: Scope, headers: dict[bytes, bytes]) -> bool:
    if scope.get("method") not in ("GET", "HEAD"):
        return False
    path = scope.get("path", "/")
    if path in _SKIP_PATHS or path.startswith(_SKIP_PREFIXES):
        return False
    mode = headers.get(b"sec-fetch-mode")
    if mode is not None:
        return mode == b"navigate"
    return b"text/html" in headers.get(b"accept", b"")


def _hostname(host_header: str) -> str | None:
    """The host part of a Host header, if it's a plain name or IP address."""
    host = host_header.strip().lower()
    if host.startswith("["):  # [::1]:8420
        end = host.find("]")
        if end < 0:
            return None
        inner = host[1:end]
        try:
            return f"[{ipaddress.IPv6Address(inner)}]"
        except ValueError:
            return None
    name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    try:
        return str(ipaddress.IPv4Address(name))
    except ValueError:
        pass
    return name if valid_hostname(name) and not name.startswith("*") else None


def _is_loopback(client: tuple[str, int] | None) -> bool:
    if client is None:
        return False
    try:
        return ipaddress.ip_address(client[0].split("%")[0]).is_loopback
    except ValueError:
        return False


def location(scope: Scope, port: int) -> str | None:
    """Where to send this request, or None to serve it as is."""
    headers = dict(scope.get("headers") or [])
    if any(h in headers for h in _PROXY_HEADERS) or _is_loopback(scope.get("client")):
        return None
    if not _is_page_load(scope, headers):
        return None
    host = _hostname(headers.get(b"host", b"").decode("latin-1"))
    if host is None:
        return None
    netloc = host if port == 443 else f"{host}:{port}"
    path = scope.get("raw_path") or scope.get("path", "/").encode()
    query = scope.get("query_string") or b""
    target = f"https://{netloc}{path.decode('latin-1')}"
    return f"{target}?{query.decode('latin-1')}" if query else target


class HttpsRedirectMiddleware:
    def __init__(self, app: ASGIApp, port: Callable[[], int | None]) -> None:
        self.app = app
        self.port = port

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("scheme") == "http":
            port = self.port()
            target = location(scope, port) if port is not None else None
            if target is not None:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 307,
                        "headers": [
                            (b"location", target.encode("latin-1")),
                            (b"content-length", b"0"),
                            (b"cache-control", b"no-store"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": b""})
                return
        await self.app(scope, receive, send)
