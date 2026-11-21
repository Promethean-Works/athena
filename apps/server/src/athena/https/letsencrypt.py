"""Getting and renewing a Let's Encrypt certificate with lego (docs/specs/https.md).

`lego run` gets a certificate when it has none under the name `athena` and renews it
otherwise (only when it's due, unless forced). Athena then copies lego's files to
`tls/le.crt` (full chain) and `tls/le.key`, which the HTTPS listener serves.

Provider credentials reach lego only through its environment, built from scratch here
so nothing else from Athena's environment (no stray `LEGO_*` variable) changes what
lego does; they never appear on the command line or in the job log.
"""

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from athena.https import local_ca
from athena.https.dns_providers import provider_env
from athena.https.local_ca import TlsPaths
from athena.https.settings import LetsEncryptSettings

CERT_NAME = "athena"
RENEW_DAYS = 30
"""Renew when fewer days than this are left (Let's Encrypt certificates last 90)."""

ACME_DIRECTORY_ENV = "ATHENA_ACME_DIRECTORY"
"""Testing only: an ACME directory URL to use instead of Let's Encrypt (Pebble in CI)."""
ACME_CA_ENV = "ATHENA_ACME_CA_CERTIFICATES"
"""Testing only: a CA file lego trusts for that ACME server."""
HTTP_ADDRESS_ENV = "ATHENA_ACME_HTTP_ADDRESS"
"""Testing only: where lego answers the HTTP-01 challenge instead of `:80`."""

# Variables a child process needs to run at all (temp dirs, certificate stores, DNS).
_PASS_THROUGH = (
    "PATH",
    "HOME",
    "TMPDIR",
    "TEMP",
    "TMP",
    "SYSTEMROOT",
    "WINDIR",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "https_proxy",
    "http_proxy",
    "no_proxy",
)


def le_paths(paths: TlsPaths) -> tuple[Path, Path]:
    """(certificate, key) the listener serves in Let's Encrypt mode."""
    return paths.dir / "le.crt", paths.dir / "le.key"


def lego_dir(paths: TlsPaths) -> Path:
    return paths.dir / "lego"


def _issued_for(paths: TlsPaths) -> Path:
    return paths.dir / "le.json"


@dataclass
class Command:
    argv: list[str]
    env: dict[str, str]
    """The child's whole environment. Contains secrets: never log it."""


def _server(le: LetsEncryptSettings) -> str:
    return os.environ.get(ACME_DIRECTORY_ENV) or (
        "letsencrypt-staging" if le.staging else "letsencrypt"
    )


def issued_for(paths: TlsPaths) -> list[str] | None:
    """The domains the installed Let's Encrypt certificate was requested for."""
    try:
        before = json.loads(_issued_for(paths).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    domains = before.get("domains") if isinstance(before, dict) else None
    return domains if isinstance(domains, list) else None


def must_force(paths: TlsPaths, le: LetsEncryptSettings) -> bool:
    """Whether the stored certificate was for other domains or another server, so a
    renewal must ask for a new one instead of renewing it as it is."""
    cert, _ = le_paths(paths)
    try:
        before = json.loads(_issued_for(paths).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cert.is_file()
    return before != {"domains": le.domains, "server": _server(le)}


def build_command(
    binary: Path,
    paths: TlsPaths,
    le: LetsEncryptSettings,
    dns_values: dict[str, str],
    *,
    force: bool = False,
) -> Command:
    """The lego invocation for these settings. Raises `ValueError` if they're incomplete."""
    problem = le.problem()
    if problem:
        raise ValueError(problem)
    argv = [
        str(binary),
        "run",
        "--accept-tos",
        "--email",
        le.email,
        "--path",
        str(lego_dir(paths)),
        "--cert.name",
        CERT_NAME,
        "--key-type",
        "ec256",
        "--server",
        _server(le),
        "--renew-days",
        str(RENEW_DAYS),
        "--no-random-sleep",
        "--log.format",
        "text",
    ]
    for domain in le.domains:
        argv += ["--domains", domain]
    if force:
        argv += ["--renew-force", "--force-cert-domains"]
    env = {k: v for k in _PASS_THROUGH if (v := os.environ.get(k))}
    if ca := os.environ.get(ACME_CA_ENV):
        env["LEGO_CA_CERTIFICATES"] = ca
    if le.challenge == "dns":
        assert le.dns_provider is not None  # checked by problem()
        argv += ["--dns", le.dns_provider]
        env.update(provider_env(le.dns_provider, dns_values))
    else:
        argv += ["--http", "--http.address", os.environ.get(HTTP_ADDRESS_ENV) or ":80"]
    return Command(argv, env)


def install_certificate(paths: TlsPaths, le: LetsEncryptSettings) -> x509.Certificate:
    """Copy lego's certificate and key to where the listener reads them.

    Raises `ValueError` if lego left no usable pair (the old files stay as they were).
    """
    src = lego_dir(paths) / "certificates"
    chain = (src / f"{CERT_NAME}.crt").read_bytes()
    key_pem = (src / f"{CERT_NAME}.key").read_bytes()
    cert = x509.load_pem_x509_certificate(chain)
    key = serialization.load_pem_private_key(key_pem, password=None)
    if cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    ) != key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    ):
        raise ValueError("lego's certificate doesn't match its key")
    cert_path, key_path = le_paths(paths)
    local_ca.write_file(key_path, key_pem, private=True)
    local_ca.write_file(cert_path, chain, private=False)
    local_ca.write_file(
        _issued_for(paths),
        json.dumps({"domains": le.domains, "server": _server(le)}).encode(),
        private=False,
    )
    return cert


def due(paths: TlsPaths, now: datetime | None = None) -> bool:
    """Whether the Let's Encrypt certificate is missing or has under `RENEW_DAYS` left."""
    cert = local_ca.load_cert(le_paths(paths)[0])
    if cert is None:
        return True
    now = now or datetime.now(UTC)
    return cert.not_valid_after_utc - now < timedelta(days=RENEW_DAYS)
