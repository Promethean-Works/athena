"""Runtime settings: CLI flags, then ATHENA_* environment variables, then the `server`
section of `<data-dir>/athena.json`, then the defaults."""

import json
import os
import sys
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir
from pydantic import BaseModel, ConfigDict, Field
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    InitSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

DEFAULT_PORT = 8420


def default_data_dir() -> Path:
    """Per-OS data directory. Matches what scripts/install.sh and install.ps1 pass."""
    if sys.platform.startswith("linux"):
        return Path("/var/lib/athena")
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Athena"
    return Path(user_data_dir("Athena", appauthor=False)) / "data"


DEFAULT_FEEDBACK_REPO = "https://github.com/Promethean-Works/athena"
SETTINGS_FILE = "athena.json"
SECTIONS = ("server", "system", "https", "ai", "webdav", "backup")
"""The sections of athena.json, in file order (`athena.settings_file.AthenaConfig`)."""


class ServerSettings(BaseModel):
    """The `server` section of athena.json. A flag or ATHENA_* variable overrides it."""

    model_config = ConfigDict(extra="forbid")

    host: str = "0.0.0.0"
    """Address to listen on. `0.0.0.0` is every interface; `127.0.0.1` this host only."""
    port: int = Field(DEFAULT_PORT, ge=1, le=65535)
    """The HTTP port."""
    feedback_repo: str = DEFAULT_FEEDBACK_REPO
    """Where "Send feedback" opens issues (forks point it at their own repository)."""
    durable_execution_database_url: str | None = None
    """Postgres URL for the assistant's durable execution (pgtask). Unset: off."""


class _ServerSection(PydanticBaseSettingsSource):
    """The `server` section of athena.json, as a settings source. A file that doesn't
    parse gives nothing here: `athena serve` checks the file and refuses it first."""

    def __init__(self, settings_cls: type[BaseSettings], data_dir: Path) -> None:
        super().__init__(settings_cls)
        self.path = data_dir / SETTINGS_FILE

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False  # unused: __call__ reads the whole section

    def __call__(self) -> dict[str, Any]:
        return server_section(self.path)


def server_section(path: Path) -> dict[str, Any]:
    """The raw `server` values in an athena.json (empty if it's missing or broken)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    server = data.get("server") if isinstance(data, dict) else None
    if not isinstance(server, dict):
        return {}
    return {k: v for k, v in server.items() if k in ServerSettings.model_fields}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATHENA_")

    host: str = "0.0.0.0"
    port: int = Field(DEFAULT_PORT, ge=1, le=65535)
    data_dir: Path = default_data_dir()
    # Directory with the exported web UI. Defaults to the copy bundled in the wheel.
    web_dir: Path = Path(__file__).parent / "web"
    # Set by `athena serve`; tests leave it off so they don't write log files.
    log_to_file: bool = False
    # Postgres database URL for pgtask durable execution. When set, assistant turns run
    # inside pgtask tasks so every model request and tool call is checkpointed; an
    # interrupted run resumes from its last completed step instead of repeating paid work.
    durable_execution_database_url: str | None = None
    # Where "Send feedback" opens issues (docs/specs/feedback.md). Forks point it at their
    # own repository; GitHub gets the issue forms, Codeberg and GitLab a plain issue.
    feedback_repo: str = DEFAULT_FEEDBACK_REPO
    # Folders a local backup destination may live in. Empty means the usual places for a
    # disk to be mounted (/mnt, /media, /Volumes, the home folders; every drive on Windows).
    backup_allowed_roots: list[Path] = []

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # The file lives in the data dir, so the data dir itself can't come from it.
        init = init_settings.init_kwargs if isinstance(init_settings, InitSettingsSource) else {}
        data_dir = init.get("data_dir") or os.environ.get("ATHENA_DATA_DIR") or default_data_dir()
        return init_settings, env_settings, _ServerSection(settings_cls, Path(data_dir))
