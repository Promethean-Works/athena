"""Athena's local certificate authority and the self-signed server certificate.

The CA is made once and lives for 10 years, so admins trust it on their devices once.
The server certificate it signs lasts 365 days (Apple refuses more than 825 for
user-trusted CAs) and is reissued when it nears expiry or misses one of the host's
current names or IPv4 addresses. Keys are EC P-256 and written 0600 under
`<data-dir>/tls/`.
"""

import contextlib
import ipaddress
import os
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psutil
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from athena.https.settings import valid_hostname

CA_DAYS = 3650
SERVER_DAYS = 365
RENEW_BEFORE = timedelta(days=30)
# Backdated so a client whose clock is a little behind still accepts a new certificate.
CLOCK_SKEW = timedelta(hours=1)

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


@dataclass(frozen=True)
class TlsPaths:
    dir: Path

    @property
    def ca_key(self) -> Path:
        return self.dir / "ca.key"

    @property
    def ca_cert(self) -> Path:
        return self.dir / "ca.crt"

    @property
    def key(self) -> Path:
        return self.dir / "server.key"

    @property
    def cert(self) -> Path:
        return self.dir / "server.crt"


def tls_paths(data_dir: Path) -> TlsPaths:
    return TlsPaths(data_dir / "tls")


def _write(path: Path, data: bytes, private: bool) -> None:
    """Write atomically (a running server may reload the file), keys readable by owner only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.parent.chmod(0o700)
    tmp = path.with_name(path.name + ".tmp")
    # A stale temp file from a crash could have looser permissions: start fresh, create
    # exclusively (the mode only applies on create), binary so Windows keeps LF.
    tmp.unlink(missing_ok=True)
    mode = 0o600 if private else 0o644
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(tmp, flags, mode)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _key_pem(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _load_key(path: Path) -> ec.EllipticCurvePrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise ValueError(f"{path} is not an EC key")
    return key


def load_cert(path: Path) -> x509.Certificate | None:
    try:
        return x509.load_pem_x509_certificate(path.read_bytes())
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- names


def _short_hostname() -> str:
    return socket.gethostname().strip().lower().rstrip(".").split(".")[0]


def host_names() -> set[str]:
    """`localhost`, the hostname and `<hostname>.local`, skipping ones that aren't valid DNS."""
    full = socket.gethostname().strip().lower().rstrip(".")
    short = full.split(".")[0]
    names = {"localhost", full, short, f"{short}.local"}
    return {n for n in names if n and valid_hostname(n)}


# Container and VM bridges: their addresses aren't how anyone reaches Athena, and they
# come and go with every compose project (`br-*`) or Windows reboot (`vEthernet`), which
# would reissue the certificate each time.
VIRTUAL_INTERFACE_PREFIXES = ("docker", "br-", "veth", "virbr", "vethernet", "cni", "flannel")


def host_addresses() -> set[IPAddress]:
    """Loopback plus the IPv4 addresses of the host's real interfaces that are up.

    Global IPv6 addresses are left out: privacy addresses rotate daily and would
    reissue the certificate every day. Link-local addresses can't go in a certificate.
    """
    out: set[IPAddress] = {ipaddress.ip_address("127.0.0.1"), ipaddress.ip_address("::1")}
    try:
        interfaces = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
    except (OSError, psutil.Error):
        return out
    for name, addrs in interfaces.items():
        if name.lower().startswith(VIRTUAL_INTERFACE_PREFIXES):
            continue
        if name in stats and not stats[name].isup:
            continue
        for addr in addrs:
            if addr.family != socket.AF_INET:
                continue
            try:
                ip = ipaddress.ip_address(addr.address)
            except ValueError:
                continue
            if not ip.is_link_local and not ip.is_unspecified:
                out.add(ip)
    return out


def wanted_names(extra: list[str]) -> tuple[set[str], set[IPAddress]]:
    """DNS names and IP addresses the server certificate must cover."""
    dns = host_names()
    ips = host_addresses()
    for name in extra:
        try:
            ips.add(ipaddress.ip_address(name))
        except ValueError:
            dns.add(name)
    return dns, ips


def cert_names(cert: x509.Certificate) -> tuple[set[str], set[IPAddress]]:
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return set(), set()
    dns = {n.lower() for n in san.get_values_for_type(x509.DNSName)}
    return dns, set(san.get_values_for_type(x509.IPAddress))


# ---------------------------------------------------------------- CA


def _ca_name() -> x509.Name:
    label = _short_hostname() or "athena"
    return x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, f"Athena Local CA ({label})"[:64]),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Athena"),
        ]
    )


def _make_ca(paths: TlsPaths, now: datetime) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = _ca_name()
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - CLOCK_SKEW)
        .not_valid_after(now + timedelta(days=CA_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    _write(paths.ca_key, _key_pem(key), private=True)
    _write(paths.ca_cert, cert.public_bytes(serialization.Encoding.PEM), private=False)
    return key, cert


def ensure_ca(
    paths: TlsPaths, now: datetime | None = None
) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    """The CA key and certificate, made if missing, unreadable or expired."""
    now = now or datetime.now(UTC)
    cert = load_cert(paths.ca_cert)
    if cert is not None and paths.ca_key.is_file() and cert.not_valid_after_utc > now:
        try:
            key = _load_key(paths.ca_key)
        except (OSError, ValueError, TypeError):  # TypeError: a password-protected key
            key = None
        if key is not None and key.public_key() == cert.public_key():
            return key, cert
    return _make_ca(paths, now)


def rotate_ca(paths: TlsPaths) -> None:
    """Throw away the CA and the server certificate it signed; the next ensure makes both."""
    for path in (paths.ca_key, paths.ca_cert, paths.key, paths.cert):
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------- server certificate


def reissue_reason(
    cert: x509.Certificate | None,
    ca_cert: x509.Certificate,
    dns: set[str],
    ips: set[IPAddress],
    now: datetime,
) -> str | None:
    """Why the server certificate must be reissued, or None if it's still good.

    A certificate covering more than is wanted is fine, so an interface going away
    doesn't cause a reissue; one that misses a wanted name is not.
    """
    if cert is None:
        return "missing"
    if cert.issuer != ca_cert.subject:
        return "signed by another CA"
    try:
        cert.verify_directly_issued_by(ca_cert)
    except (ValueError, TypeError, InvalidSignature):
        return "signed by another CA"
    if cert.not_valid_after_utc - now < RENEW_BEFORE:
        return "expires soon"
    have_dns, have_ips = cert_names(cert)
    if not dns <= have_dns or not ips <= have_ips:
        return "names changed"
    return None


def _issue(
    paths: TlsPaths,
    ca_key: ec.EllipticCurvePrivateKey,
    ca_cert: x509.Certificate,
    dns: set[str],
    ips: set[IPAddress],
    now: datetime,
) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    sans: list[x509.GeneralName] = [x509.DNSName(n) for n in sorted(dns)]
    sans += [x509.IPAddress(ip) for ip in sorted(ips, key=lambda ip: (ip.version, int(ip)))]
    cn = _short_hostname() or "athena"
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn[:64])]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - CLOCK_SKEW)
        .not_valid_after(now + timedelta(days=SERVER_DAYS))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=False,
                crl_sign=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    # Key first: a reload between the two writes then fails on a mismatch instead of
    # serving a certificate whose key is gone.
    _write(paths.key, _key_pem(key), private=True)
    _write(paths.cert, cert.public_bytes(serialization.Encoding.PEM), private=False)


def _key_matches(path: Path, cert: x509.Certificate) -> bool:
    try:
        return _load_key(path).public_key() == cert.public_key()
    except (OSError, ValueError, TypeError):
        return False


def ensure_server_cert(paths: TlsPaths, extra: list[str], now: datetime | None = None) -> bool:
    """Make sure a good server certificate exists. True if a new one was issued."""
    now = now or datetime.now(UTC)
    ca_key, ca_cert = ensure_ca(paths, now)
    dns, ips = wanted_names(extra)
    cert = load_cert(paths.cert)
    if cert is not None and not _key_matches(paths.key, cert):
        cert = None  # e.g. a crash between writing the key and the certificate
    if reissue_reason(cert, ca_cert, dns, ips, now) is None:
        return False
    _issue(paths, ca_key, ca_cert, dns, ips, now)
    return True
