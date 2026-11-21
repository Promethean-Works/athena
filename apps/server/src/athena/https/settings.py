"""HTTPS settings (docs/specs/https.md), stored as their own `system_settings` row.

They live apart from `SystemSettings` so saving Settings → System never sends back stale
HTTPS values, and so `athena https off` can change them without the rest.
"""

import ipaddress
import logging
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlmodel import Session

from athena.db.models import SystemSetting

log = logging.getLogger(__name__)
KEY = "https"
DEFAULT_HTTPS_PORT = 8443
MAX_EXTRA_NAMES = 20

Mode = Literal["off", "self_signed"]

# One DNS label: letters, digits and inner hyphens, at most 63 characters.
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def valid_hostname(name: str) -> bool:
    """A DNS name (`nas`, `nas.home.lan`), optionally with a leading `*.` wildcard."""
    if len(name) > 253:
        return False
    labels = name.removeprefix("*.").split(".")
    return all(_LABEL.match(label) for label in labels)


def normalize_name(raw: str) -> str:
    """A host name or IP address as it goes in a certificate. Raises `ValueError`."""
    name = raw.strip().lower().rstrip(".")
    try:
        return str(ipaddress.ip_address(name.strip("[]")))
    except ValueError:
        pass
    if not valid_hostname(name):
        raise ValueError(f"{raw!r} is not a valid host name or IP address")
    return name


class HttpsSettings(BaseModel):
    mode: Mode = "off"
    """`off` serves plain HTTP only; `self_signed` adds HTTPS with Athena's local CA."""

    port: int = Field(DEFAULT_HTTPS_PORT, ge=1, le=65535)
    """The HTTPS port. The HTTP port keeps working (and redirects, see `redirect`)."""

    redirect: bool = True
    """Send browsers on the HTTP port to HTTPS. Requests from the host itself, through a
    local proxy or tunnel, and `/api/health` are never redirected."""

    extra_names: list[str] = Field(default_factory=list, max_length=MAX_EXTRA_NAMES)
    """More names or addresses for the self-signed certificate (`nas.home.lan`)."""

    @field_validator("extra_names")
    @classmethod
    def _names(cls, names: list[str]) -> list[str]:
        out: list[str] = []
        for raw in names:
            name = normalize_name(raw)
            if name not in out:
                out.append(name)
        return out


def load(db: Session) -> HttpsSettings:
    row = db.get(SystemSetting, KEY)
    if row is None:
        return HttpsSettings()
    try:
        return HttpsSettings.model_validate_json(row.value)
    except ValidationError:
        log.warning("ignoring invalid HTTPS settings")
        return HttpsSettings()


def save(db: Session, settings: HttpsSettings) -> None:
    row = db.get(SystemSetting, KEY) or SystemSetting(key=KEY, value="")
    row.value = settings.model_dump_json()
    db.add(row)
    db.commit()
