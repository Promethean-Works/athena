"""Stands in for lego in tests: writes a certificate where lego would.

Reads the same flags Athena passes (`--path`, `--cert.name`, `--domains`), records its
argv and environment to FAKE_LEGO_RECORD, and exits with FAKE_LEGO_EXIT (default 0).
"""

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def main() -> int:
    args = sys.argv[1:]
    record = os.environ.get("FAKE_LEGO_RECORD")
    if record:
        Path(record).write_text(json.dumps({"argv": args, "env": dict(os.environ)}))
    code = int(os.environ.get("FAKE_LEGO_EXIT", "0"))
    if code:
        print("fake lego: urn:ietf:params:acme:error:connection")
        return code
    path = Path(args[args.index("--path") + 1])
    name = args[args.index("--cert.name") + 1]
    domains = [args[i + 1] for i, a in enumerate(args) if a == "--domains"]
    days = int(os.environ.get("FAKE_LEGO_DAYS", "90"))
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(UTC)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domains[0])])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Fake ACME CA")]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(hours=1))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(d) for d in domains]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    out = path / "certificates"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (out / f"{name}.key").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    print(f"fake lego: issued {', '.join(domains)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
