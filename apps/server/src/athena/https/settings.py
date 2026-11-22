"""HTTPS settings (docs/specs/https.md), stored as the `https` section of `athena.json`.

They live apart from `SystemSettings` so saving Settings → System never sends back stale
HTTPS values, and so `athena https off` can change them without the rest.
"""

import ipaddress
import logging
import re
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, field_validator

from athena.crypto import SecretBox
from athena.system_settings import ENCRYPTED, is_secret, merge_tunnel_config

if TYPE_CHECKING:
    from athena.settings_file import SettingsFile

log = logging.getLogger(__name__)
DEFAULT_HTTPS_PORT = 8443
MAX_EXTRA_NAMES = 20

Mode = Literal["off", "self_signed", "letsencrypt"]
Challenge = Literal["http", "dns"]
MAX_DOMAINS = 10

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


class LetsEncryptSettings(BaseModel):
    domains: list[str] = Field(default_factory=list, max_length=MAX_DOMAINS)
    """Public DNS names for the certificate. The first one names it. `*.example.com`
    needs the DNS challenge."""

    email: str = Field("", max_length=254)
    """Let's Encrypt's contact for the account (expiry warnings)."""

    challenge: Challenge = "http"
    """`http`: Let's Encrypt connects to port 80 here. `dns`: a TXT record is made
    through the DNS provider's API (no open ports; needed for wildcards)."""

    dns_provider: str | None = None
    """An id from `dns_providers.PROVIDERS` when `challenge` is `dns`."""

    dns_config: dict[str, str | None] = Field(default_factory=dict)
    """The provider's fields. Secrets are stored encrypted and never returned: an empty
    secret keeps the stored one, `null` clears it."""

    dns_secrets_set: list[str] = Field(default_factory=list)
    """Read-only: the secret fields that have a stored value."""

    staging: bool = False
    """Use Let's Encrypt's staging server (untrusted certificates, generous limits)."""

    @field_validator("domains")
    @classmethod
    def _domains(cls, domains: list[str]) -> list[str]:
        out: list[str] = []
        for raw in domains:
            name = raw.strip().lower().rstrip(".")
            if not name:
                continue
            if "." not in name.removeprefix("*.") or not valid_hostname(name):
                raise ValueError(f"{raw!r} is not a public domain name")
            if name not in out:
                out.append(name)
        return out

    @field_validator("email")
    @classmethod
    def _email(cls, email: str) -> str:
        # Good enough to catch typos; Let's Encrypt checks the address itself.
        email = email.strip()
        local, _, domain = email.rpartition("@")
        if email and (not local or "." not in domain.strip(".") or any(c.isspace() for c in email)):
            raise ValueError(f"{email!r} is not an email address")
        return email

    def problem(self) -> str | None:
        """Why a certificate can't be requested with these settings, or None."""
        from athena.https.dns_providers import BY_ID

        if not self.domains:
            return "Add at least one domain."
        if not self.email:
            return "Add an email address for Let's Encrypt."
        if self.challenge == "http" and any(d.startswith("*.") for d in self.domains):
            return "Wildcard domains need the DNS challenge."
        if self.challenge == "dns" and self.dns_provider not in BY_ID:
            return "Pick a DNS provider."
        return None


class HttpsSettings(BaseModel):
    mode: Mode = "off"
    """`off` serves plain HTTP only; `self_signed` adds HTTPS with Athena's local CA;
    `letsencrypt` serves the certificate from Let's Encrypt (get one first)."""

    port: int = Field(DEFAULT_HTTPS_PORT, ge=1, le=65535)
    """The HTTPS port. The HTTP port keeps working (and redirects, see `redirect`)."""

    redirect: bool = True
    """Send browsers on the HTTP port to HTTPS. Requests from the host itself, through a
    local proxy or tunnel, and `/api/health` are never redirected."""

    extra_names: list[str] = Field(default_factory=list, max_length=MAX_EXTRA_NAMES)
    """More names or addresses for the self-signed certificate (`nas.home.lan`)."""

    letsencrypt: LetsEncryptSettings = Field(default_factory=LetsEncryptSettings)
    """Kept when another mode is picked, so switching back needs no retyping."""

    @field_validator("extra_names")
    @classmethod
    def _names(cls, names: list[str]) -> list[str]:
        out: list[str] = []
        for raw in names:
            name = normalize_name(raw)
            if name not in out:
                out.append(name)
        return out


def load(config: "SettingsFile") -> HttpsSettings:
    """A copy of the https settings this run uses (athena.json, read at startup)."""
    return config.section("https")


def save(config: "SettingsFile", settings: HttpsSettings) -> None:
    config.save("https", settings)


def public(settings: HttpsSettings) -> HttpsSettings:
    """The settings as the API returns them: DNS secrets dropped, the stored ones listed."""
    le = settings.letsencrypt
    config = le.dns_config
    return settings.model_copy(
        update={
            "letsencrypt": le.model_copy(
                update={
                    "dns_config": {k: v for k, v in config.items() if not is_secret(k)},
                    "dns_secrets_set": sorted(k for k, v in config.items() if is_secret(k) and v),
                }
            )
        }
    )


def with_secrets(stored: HttpsSettings, incoming: HttpsSettings, box: SecretBox) -> HttpsSettings:
    """`incoming` with its DNS secrets encrypted, empty ones keeping the stored value."""
    from athena.https.dns_providers import BY_ID

    provider = BY_ID.get(incoming.letsencrypt.dns_provider or "")
    known = {f.key for f in provider.fields} if provider else set()
    wanted = {k: v for k, v in incoming.letsencrypt.dns_config.items() if k in known}
    kept = {k: v for k, v in stored.letsencrypt.dns_config.items() if k in known}
    config = merge_tunnel_config(kept, wanted, box)
    le = incoming.letsencrypt.model_copy(update={"dns_config": config, "dns_secrets_set": []})
    return incoming.model_copy(update={"letsencrypt": le})


def dns_values(settings: LetsEncryptSettings, box: SecretBox) -> dict[str, str]:
    """The DNS provider's fields with secrets decrypted, for lego's environment only.

    Raises `athena.crypto.SecretError` if a secret can't be decrypted.
    """
    out: dict[str, str] = {}
    for key, value in settings.dns_config.items():
        if not isinstance(value, str):
            continue
        if is_secret(key) and value.startswith(ENCRYPTED):
            value = box.decrypt(value.removeprefix(ENCRYPTED))
        out[key] = value
    return out
