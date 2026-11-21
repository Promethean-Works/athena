"""Database tables. Every change here needs an Alembic migration in db/migrations/versions;
tests/test_db.py fails if the models and migrations drift apart."""

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True, max_length=64)
    password_hash: str
    is_admin: bool = True
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))
    appearance: str | None = None
    """The user's appearance settings as JSON (see athena.api.settings.Appearance)."""
    dashboard: str | None = None
    """The user's dashboard layout as JSON (see athena.api.settings.DashboardLayout)."""


class AuthSession(SQLModel, table=True):
    """A signed-in browser. Only a SHA-256 of the cookie token is stored."""

    __tablename__ = "sessions"

    id: int | None = Field(default=None, primary_key=True)
    token_hash: str = Field(unique=True, index=True, max_length=64)
    user_id: int = Field(foreign_key="users.id", index=True, ondelete="CASCADE")
    csrf_token: str = Field(max_length=64)
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))
    expires_at: datetime = Field(sa_type=DateTime(timezone=True))


class AuditEntry(SQLModel, table=True):
    """Who did what to the host (docs/design/security.md). Never edited, only appended."""

    __tablename__ = "audit_log"

    id: int | None = Field(default=None, primary_key=True)
    at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True), index=True)
    username: str = Field(max_length=64)
    action: str = Field(max_length=64, index=True)
    """Dotted verb, e.g. "container.stop", "runtime.start"."""
    target: str | None = Field(default=None, max_length=255)
    detail: str | None = None


class App(SQLModel, table=True):
    """An Athena-managed app: a compose project in <data-dir>/apps/<name>/compose.yaml."""

    __tablename__ = "apps"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True, max_length=63)
    """Compose project name: lowercase letters, digits, dash and underscore."""
    source: str = Field(default="compose", max_length=16)
    """How it was created: "compose", "docker-run" or "catalog"."""
    catalog_id: str | None = Field(default=None, max_length=128)
    """For catalog installs: "<catalog>/<app id>", e.g. "builtin/jellyfin"."""
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))


class Catalog(SQLModel, table=True):
    """A remote app catalog, downloaded to <data-dir>/catalogs/<id>/."""

    __tablename__ = "catalogs"

    id: str = Field(primary_key=True, max_length=63)
    name: str = Field(max_length=100)
    url: str = Field(max_length=500)
    kind: str = Field(default="auto", max_length=16)
    """auto, athena or casaos."""
    app_count: int = 0
    refreshed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))


class SystemSetting(SQLModel, table=True):
    """Small markers, one value per key (`files_defaults_seeded`). Settings live in
    `<data-dir>/athena.json` (`athena.settings_file`), not here."""

    __tablename__ = "system_settings"

    key: str = Field(primary_key=True, max_length=64)
    value: str


class FileLocation(SQLModel, table=True):
    """A folder the file manager may browse (docs/design/files.md). Nothing outside
    the configured locations is reachable through the files API."""

    __tablename__ = "file_locations"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, max_length=64)
    path: str = Field(max_length=1024)
    """Absolute path on the host."""
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))


class Share(SQLModel, table=True):
    """A public link to a file or folder in a location (docs/design/files.md).

    The token is the link, so it's stored as is: the admin can copy the link again
    later. Removing the location removes its links.
    """

    __tablename__ = "shares"

    id: int | None = Field(default=None, primary_key=True)
    token: str = Field(unique=True, index=True, max_length=64)
    location_id: int = Field(foreign_key="file_locations.id", index=True, ondelete="CASCADE")
    path: str = Field(max_length=4096)
    """Relative to the location, with `/` separators; "" is the location itself."""
    mode: str = Field(default="read", max_length=16)
    """"read": view and download. "upload": a drop box that can't be listed."""
    password_hash: str | None = None
    expires_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    created_by: str = Field(max_length=64)
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))
    downloads: int = 0
    uploads: int = 0


class SmbShare(SQLModel, table=True):
    """An SMB share Athena created for a file location (docs/design/files.md).

    The share is published by the host's Samba server (Linux) from smb.conf; this
    row tracks what Athena created so it can be listed and removed.
    """

    __tablename__ = "smb_shares"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True, max_length=64)
    """The share name as it appears on the network (\\\\server\\name)."""
    location_id: int = Field(foreign_key="file_locations.id", index=True, ondelete="CASCADE")
    path: str = Field(max_length=1024)
    """The shared folder's absolute path on the host."""
    read_only: bool = Field(default=False)
    guest_ok: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))


class AiProvider(SQLModel, table=True):
    """An AI provider the assistant can use (docs/design/assistant.md). Server-wide."""

    __tablename__ = "ai_providers"

    id: str = Field(primary_key=True, max_length=32)
    kind: str = Field(max_length=32)
    """A models.dev provider id or "ollama" (athena.assistant.kinds), e.g. "anthropic"."""
    name: str = Field(max_length=64)
    config: str = "{}"
    """Non-secret settings as JSON, e.g. {"base_url": "…"}."""
    secrets: str | None = None
    """Secret settings (API keys) as JSON, encrypted with athena.crypto.SecretBox."""
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))


class ModelsDevCache(SQLModel, table=True):
    """Cached provider and model data from models.dev (docs/design/assistant.md)."""

    __tablename__ = "models_dev_cache"

    provider_id: str = Field(primary_key=True, max_length=64)
    """Provider ID from models.dev."""
    name: str = Field(max_length=128)
    """Provider display name."""
    api_url: str | None = Field(default=None, max_length=512)
    """Provider's API endpoint if OpenAI-compatible."""
    npm_package: str | None = Field(default=None, max_length=128)
    """NPM package for AI SDK."""
    doc_url: str | None = Field(default=None, max_length=512)
    """Documentation URL."""
    env_vars: list = Field(default=[], sa_type=JSON)
    """Required environment variables as JSON array."""
    models: dict = Field(default={}, sa_type=JSON)
    """Model data as JSON object (id -> model info)."""
    model_count: int = 0
    """Number of models."""
    is_openai_compatible: bool = False
    """Whether provider uses OpenAI-compatible API."""
    fetched_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))
    """When this data was fetched from models.dev."""
    expires_at: datetime = Field(sa_type=DateTime(timezone=True), index=True)
    """When this cache entry expires."""


class AiIntegration(SQLModel, table=True):
    """A hosted integration the assistant can use (docs/design/assistant.md, part D.5).

    Each integration is an MCP server Athena runs (a stdio command or a streamable-HTTP
    endpoint) with a per-server encrypted token. Server-wide, admins only.
    """

    __tablename__ = "ai_integrations"

    id: str = Field(primary_key=True, max_length=64)
    kind: str = Field(max_length=64)
    """One of athena.assistant.integrations.KINDS, e.g. "github" or "linear"."""
    name: str = Field(max_length=64)
    config: str = "{}"
    """The integration's transport and where its token goes, as JSON
    (see athena.assistant.integrations.Integration)."""
    secrets: str | None = None
    """The token as JSON, encrypted with athena.crypto.SecretBox."""
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))


class AiConversation(SQLModel, table=True):
    """An assistant chat. `history` is pydantic-ai's Conversation as JSON."""

    __tablename__ = "ai_conversations"

    id: str = Field(primary_key=True, max_length=32)
    user_id: int = Field(foreign_key="users.id", index=True, ondelete="CASCADE")
    title: str = Field(default="New chat", max_length=200)
    provider_id: str | None = Field(default=None, max_length=32)
    """The model picked last in this chat. Not a foreign key: removing a provider keeps
    its chats, which then ask for another model."""
    model: str | None = Field(default=None, max_length=255)
    history: str | None = None
    transcript: str | None = None
    """Every message as the admin saw it, once compaction has shortened `history` (the
    model's view). None while the two are the same."""
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(
        default_factory=utcnow, sa_type=DateTime(timezone=True), index=True
    )


class AutomationTrigger(SQLModel, table=True):
    """A durable trigger that starts an automation job (docs/design/automation.md).

    kind "cron" fires on a cron expression; kind "http" fires when its webhook
    URL is called. `action` is the job to run, stored as JSON.
    """

    __tablename__ = "automation_triggers"

    id: str = Field(primary_key=True, max_length=64)
    kind: str = Field(max_length=16)
    """cron or http."""
    name: str = Field(max_length=64)
    cron_expression: str | None = Field(default=None, max_length=200)
    """Set for kind "cron"; e.g. "*/5 * * * *"."""
    action: dict = Field(sa_type=JSON)
    """The job to run, e.g. {"kind": "app", "name": "…", "verb": "start"}."""
    enabled: bool = Field(default=True)
    webhook_token: str | None = Field(default=None, max_length=64, unique=True, index=True)
    """Secret for kind "http"; POST /api/automation/webhook/{token} fires it."""
    next_run_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True), index=True)
    last_run_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(
        default_factory=utcnow, sa_type=DateTime(timezone=True), index=True
    )


class AutomationJobRun(SQLModel, table=True):
    """One execution of an automation trigger. Append-only history of what ran."""

    __tablename__ = "automation_job_runs"

    id: str = Field(primary_key=True, max_length=64)
    trigger_id: str | None = Field(default=None, max_length=64)
    status: str = Field(max_length=16)
    """running, succeeded or failed."""
    started_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))
    finished_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    output: str | None = None
    """Joined job log lines."""
    error: str | None = None
