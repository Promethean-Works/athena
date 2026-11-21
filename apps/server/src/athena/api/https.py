"""HTTPS for Athena's own UI and API (docs/specs/https.md). Admins only."""

import hashlib
import ipaddress
import logging
import ssl
import time
from datetime import datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel

from athena import audit
from athena.auth.deps import Authed, DbSession
from athena.crypto import SecretError
from athena.https import letsencrypt, local_ca
from athena.https import settings as https_settings
from athena.https.dns_providers import PROVIDERS, DnsProvider, provider_env
from athena.https.manager import HttpsError, HttpsManager, bind
from athena.https.settings import HttpsSettings, LetsEncryptSettings
from athena.jobs import JobOut

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
    letsencrypt_certificate: CertificateInfo | None
    """The certificate from Let's Encrypt, whether or not that mode is on."""
    last_renewal: datetime | None
    renewal_error: str | None
    """Why the last attempt to get or renew it failed (the old certificate stays)."""
    renewal_job: str | None
    """The id of a certificate job that's running now."""
    port80_free: bool
    """Whether port 80 can be opened, which the HTTP challenge needs."""
    dns_providers: list[DnsProvider]


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


_port80: tuple[float, bool] = (0.0, True)
PORT80_CACHE_SECONDS = 10


def _port80_free(manager: HttpsManager) -> bool:
    """Whether port 80 can be opened on every interface, as lego's HTTP challenge does.

    Not probed while a certificate job runs (the probe could take the port from lego),
    and cached briefly so status calls don't keep opening it.
    """
    global _port80
    checked, free = _port80
    if manager.certificate_job_running or time.monotonic() - checked < PORT80_CACHE_SECONDS:
        return free
    try:
        bind("0.0.0.0", 80).close()
        free = True
    except HttpsError:
        free = False
    _port80 = (time.monotonic(), free)
    return free


def status_of(manager: HttpsManager) -> HttpsStatus:
    on = manager.settings.mode != "off"
    cert_path, _ = manager.cert_files(manager.settings)
    job = manager.renewal_job
    return HttpsStatus(
        settings=https_settings.public(manager.settings),
        http_port=manager.http_port,
        listening=manager.listening_port is not None,
        urls=_urls(local_ca.load_cert(cert_path), manager.settings.port) if on else [],
        certificate=_info(cert_path) if on else None,
        ca=_info(manager.paths.ca_cert),
        last_error=manager.last_error,
        letsencrypt_certificate=_info(letsencrypt.le_paths(manager.paths)[0]),
        last_renewal=manager.last_renewal,
        renewal_error=manager.renewal_error,
        renewal_job=job.id if job is not None and job.status == "running" else None,
        port80_free=_port80_free(manager),
        dns_providers=PROVIDERS,
    )


@router.get("", operation_id="getHttpsStatus")
def get_https(request: Request, user: Authed) -> HttpsStatus:
    _require_admin(user)
    return status_of(_manager(request))


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
    if "letsencrypt" in body.model_fields_set:
        body = https_settings.with_secrets(before, body, request.app.state.secret_box)
    else:
        # Clients that only know the other fields keep it as stored (already encrypted).
        body = body.model_copy(update={"letsencrypt": before.letsencrypt})
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
    return status_of(manager)


@router.post(
    "/certificate", operation_id="issueHttpsCertificate", status_code=status.HTTP_202_ACCEPTED
)
async def issue_certificate(
    body: LetsEncryptSettings, request: Request, user: Authed, db: DbSession
) -> JobOut:
    """Save the Let's Encrypt settings and get (or renew) the certificate in a job.

    The HTTPS mode doesn't change: once the job succeeds, pick Let's Encrypt and save.
    """
    _require_admin(user)
    problem = body.problem()
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problem)
    manager = _manager(request)
    busy = HTTPException(status.HTTP_409_CONFLICT, "A certificate request is already running")
    if manager.certificate_job_running:
        raise busy
    merged = https_settings.with_secrets(
        manager.settings,
        manager.settings.model_copy(update={"letsencrypt": body}),
        request.app.state.secret_box,
    )
    le = merged.letsencrypt
    if le.challenge == "dns":
        try:
            values = https_settings.dns_values(le, request.app.state.secret_box)
            provider_env(le.dns_provider or "", values)
        except SecretError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await manager.save_letsencrypt(le, persist=lambda new: https_settings.save(db, new))
    if manager.certificate_job_running:  # the daily check started one meanwhile
        raise busy
    # Asked for by the admin: a new certificate even if the current one isn't due.
    job = manager.start_certificate_job(le, by=user.user.username, force=True)
    return job.out()


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
    return status_of(manager)


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
