"""Assistant settings (Settings → AI). Host-wide, admins only; one JSON row in
`system_settings` under the key "ai". Invalid stored values fall back to defaults."""

import logging
from typing import Annotated

from pydantic import BaseModel, Field, ValidationError
from sqlmodel import Session

from athena.db.models import SystemSetting
from athena.terminal.shells import default_commands

log = logging.getLogger(__name__)
KEY = "ai"


class ModelRef(BaseModel):
    provider_id: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=255)


ShellCommand = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[^\s;&|<>()`$]+$")]
"""One program name (or path): no spaces or shell operators."""


class AiSettings(BaseModel):
    default_model: ModelRef | None = None
    """Used for new chats."""
    title_model: ModelRef | None = None
    """A small model for writing chat titles; the chat's own model when empty."""
    advisor_model: ModelRef | None = None
    """A second model the assistant may consult once per request (`advisor` tool); off when
    empty. Its provider sees the question the chat's model writes, not the chat."""
    refine_answers: bool = False
    """Has the model review and rewrite each answer once before the turn ends (at least one
    more model request per turn)."""
    shell_enabled: bool = False
    """Lets the assistant ask to run shell commands (each still needs approval)."""
    shell_commands: list[ShellCommand] = Field(default_factory=default_commands, max_length=200)
    """The programs it may ask to run; every part of a pipe or chain is checked."""
    memory_enabled: bool = True
    """Lets the assistant keep notes across chats (`<data-dir>/assistant/memory.db`)."""
    spend_limit_usd: float | None = Field(default=None, gt=0, le=10_000)
    """Stops a chat once its cost reaches this, for models with known prices."""


def load(db: Session) -> AiSettings:
    row = db.get(SystemSetting, KEY)
    if row is None:
        return AiSettings()
    try:
        return AiSettings.model_validate_json(row.value)
    except ValidationError:
        log.warning("ignoring invalid AI settings")
        return AiSettings()


def save(db: Session, settings: AiSettings) -> None:
    row = db.get(SystemSetting, KEY) or SystemSetting(key=KEY, value="")
    row.value = settings.model_dump_json()
    db.add(row)
    db.commit()
