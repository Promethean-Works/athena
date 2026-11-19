"""Host-wide settings that only admins change (docs/design/security.md).

Stored as one JSON row in `system_settings`. Unknown or invalid stored values fall back
to the defaults, so an older or newer server never fails on them.

Secret values in `tunnel_config` (API and auth tokens) are encrypted with `SecretBox`
before they're stored, and never leave the server: `public()` drops them and lists the
ones that are set in `tunnel_secrets_set`. Values stored in plain text by an older
server still work and are encrypted on the next save.
"""

import logging
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlmodel import Session

from athena.crypto import SecretBox
from athena.db.models import SystemSetting

log = logging.getLogger(__name__)
KEY = "system"


class SystemSettings(BaseModel):
    terminal_enabled: bool = True
    """The web terminal (host shell and container shells). Admins can turn it off."""

    tunnel_enabled: bool = False
    """Master toggle for tunnel feature."""

    tunnel_provider: str | None = None
    """Active tunnel provider: 'cloudflare' | 'tailscale' | 'ngrok'."""

    tunnel_config: dict = {}
    """Provider-specific configuration. Secret keys (see `is_secret`) are stored encrypted
    and never returned; on save, an empty or missing secret keeps the stored value and
    `null` clears it."""

    tunnel_auto_start: bool = True
    """Auto-start tunnel on boot when enabled."""

    tunnel_port: int = 8420
    """Local port to expose via tunnel."""

    tunnel_secrets_set: list[str] = []
    """Which secret keys of `tunnel_config` have a stored value. Read only: ignored on save."""


def load(db: Session) -> SystemSettings:
    row = db.get(SystemSetting, KEY)
    if row is None:
        return SystemSettings()
    try:
        return SystemSettings.model_validate_json(row.value)
    except ValidationError:
        log.warning("ignoring invalid system settings")
        return SystemSettings()


def save(db: Session, settings: SystemSettings) -> None:
    row = db.get(SystemSetting, KEY) or SystemSetting(key=KEY, value="")
    row.value = settings.model_dump_json(exclude={"tunnel_secrets_set"})
    db.add(row)
    db.commit()


ENCRYPTED = "enc:"
"""Prefix of an encrypted secret in `tunnel_config`. Values without it are plain text
written by an older server."""

_SECRET_SUFFIXES = ("token", "secret", "password", "key")


def is_secret(key: str) -> bool:
    """Whether a `tunnel_config` key holds a secret (`api_token`, `auth_token`, ...)."""
    return key.lower().endswith(_SECRET_SUFFIXES)


def public(settings: SystemSettings) -> SystemSettings:
    """The settings as the API returns them: secrets dropped, the stored ones listed."""
    config = settings.tunnel_config
    return settings.model_copy(
        update={
            "tunnel_config": {k: v for k, v in config.items() if not is_secret(k)},
            "tunnel_secrets_set": sorted(k for k, v in config.items() if is_secret(k) and v),
        }
    )


def merge_tunnel_config(
    stored: dict[str, Any], incoming: dict[str, Any], box: SecretBox
) -> dict[str, Any]:
    """The config to store: plain keys from `incoming`, secrets encrypted.

    A secret that's missing or empty in `incoming` keeps its stored value (the UI never
    gets it back to send), `null` clears it. Stored plain-text secrets get encrypted.
    """
    merged = {k: v for k, v in incoming.items() if not is_secret(k)}
    for key in {k for k in (*stored, *incoming) if is_secret(k)}:
        if key in incoming and incoming[key] is None:
            continue
        new = incoming.get(key)
        if isinstance(new, str) and new:
            merged[key] = ENCRYPTED + box.encrypt(new)
            continue
        old = stored.get(key)
        if isinstance(old, str) and old:
            merged[key] = old if old.startswith(ENCRYPTED) else ENCRYPTED + box.encrypt(old)
    return merged


def provider_config(settings: SystemSettings, box: SecretBox) -> dict[str, Any]:
    """The tunnel config with secrets decrypted, for the tunnel provider only.

    Raises `athena.crypto.SecretError` if a secret can't be decrypted.
    """
    config = dict(settings.tunnel_config)
    for key, value in config.items():
        if is_secret(key) and isinstance(value, str) and value.startswith(ENCRYPTED):
            config[key] = box.decrypt(value.removeprefix(ENCRYPTED))
    return config
