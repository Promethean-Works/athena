"""HTTPS for Athena's own UI and API (docs/specs/https.md). Admins only."""

import hashlib
import ipaddress
import logging
import ssl
from datetime import datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel

from athena import audit
from athena.auth.deps import Authed, DbSession
from athena.https import local_ca
from athena.https import settings as https_settings
from athena.https.manager import HttpsError, HttpsManager
from athena.https.settings import HttpsSettings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/https", tags=["https"])

CA_FILENAME = "athena-local-ca.crt"


class CertificateInfo(BaseModel):
    subject: str
    issuer: str
    names: list[str]
    not_before: datetime
    not_after: datetime
    sha256: str
    """SHA-256 fingerprint, colon-separated hex (what browsers show)."""


class HttpsStatus(BaseModel):
    settings: HttpsSettings
    http_port: int
    listening: bool
    """Whether the HTTPS listener is serving right now."""
    urls: list[str]
    """Addresses to open Athena over HTTPS, one per name in the certificate."""
    certificate: CertificateInfo | None
    ca: CertificateInfo | None
    """Athena's local CA, to download and trust on each device."""
    last_error: str | None


def _manager(request: Request) -> HttpsManager:
    return request.app.state.https


def _require_admin(user: Authed) -> None:
    if not user.user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can change HTTPS")


def _info(path: Path) -> CertificateInfo | None:
    cert = local_ca.load_cert(path)
    if cert is None:
        return None
    dns, ips = local_ca.cert_names(cert)
    digest = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest().upper()
    return CertificateInfo(
        subject=cert.subject.rfc4514_string(),
        issuer=cert.issuer.rfc4514_string(),
        names=sorted(dns) + [str(ip) for ip in sorted(ips, key=lambda i: (i.version, int(i)))],
        not_before=cert.not_valid_before_utc,
        not_after=cert.not_valid_after_utc,
        sha256=":".join(digest[i : i + 2] for i in range(0, len(digest), 2)),
    )


def _urls(cert: x509.Certificate | None, port: int) -> list[str]:
    if cert is None:
        return []
    dns, ips = local_ca.cert_names(cert)
    suffix = "" if port == 443 else f":{port}"
    out = [f"https://{n}{suffix}" for n in sorted(dns) if n != "localhost" and "*" not in n]
    for ip in sorted(ips, key=lambda i: (i.version, int(i))):
        if not ip.is_loopback:
            host = f"[{ip}]" if isinstance(ip, ipaddress.IPv6Address) else str(ip)
            out.append(f"https://{host}{suffix}")
    return out


def _status(manager: HttpsManager) -> HttpsStatus:
    on = manager.settings.mode != "off"
    paths = manager.paths
    return HttpsStatus(
        settings=manager.settings,
        http_port=manager.http_port,
        listening=manager.listening_port is not None,
        urls=_urls(local_ca.load_cert(paths.cert), manager.settings.port) if on else [],
        certificate=_info(paths.cert) if on else None,
        ca=_info(paths.ca_cert),
        last_error=manager.last_error,
    )


@router.get("", operation_id="getHttpsStatus")
def get_https(request: Request, user: Authed) -> HttpsStatus:
    _require_admin(user)
    return _status(_manager(request))


@router.put("", operation_id="setHttpsSettings")
async def set_https(
    body: HttpsSettings, request: Request, user: Authed, db: DbSession
) -> HttpsStatus:
    """Applied at once: the HTTPS listener starts, moves or stops before this returns.

    If the new settings can't be applied (the port is in use, say), nothing is saved and
    the current listener keeps running.
    """
    _require_admin(user)
    manager = _manager(request)
    before = manager.settings
    try:
        await manager.apply(body, persist=lambda new: https_settings.save(db, new))
    except HttpsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if (before.mode, before.port) != (body.mode, body.port):
        target = body.mode if body.mode == "off" else f"{body.mode}:{body.port}"
        audit.record(db, user.user.username, "https.mode_changed", target)
    if (before.redirect, before.extra_names) != (body.redirect, body.extra_names):
        redirect = "redirect on" if body.redirect else "redirect off"
        audit.record(db, user.user.username, "https.settings_changed", redirect)
    return _status(manager)


@router.post("/ca/rotate", operation_id="rotateHttpsCa")
async def rotate_ca(request: Request, user: Authed, db: DbSession) -> HttpsStatus:
    """A new local CA and certificate. Devices that trusted the old CA must trust the new one."""
    _require_admin(user)
    manager = _manager(request)
    try:
        await manager.rotate_ca()
    except (OSError, ValueError, ssl.SSLError) as exc:
        log.exception("HTTPS CA rotation")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Couldn't make a new CA; see the server log."
        ) from exc
    audit.record(db, user.user.username, "https.ca_rotated")
    return _status(manager)


@router.get(
    "/ca.crt",
    operation_id="downloadHttpsCa",
    response_class=Response,
    responses={200: {"content": {"application/x-x509-ca-cert": {}}}},
)
def download_ca(request: Request, user: Authed) -> Response:
    """Athena's local CA certificate (PEM), to install on devices. Never the key."""
    _require_admin(user)
    path = _manager(request).paths.ca_cert
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Turn on self-signed HTTPS first")
    return Response(
        path.read_bytes(),
        media_type="application/x-x509-ca-cert",
        headers={"Content-Disposition": f'attachment; filename="{CA_FILENAME}"'},
    )
