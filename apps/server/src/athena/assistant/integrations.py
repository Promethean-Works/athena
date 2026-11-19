"""Hosted integrations: curated MCP servers Athena runs for the assistant
(docs/design/assistant.md, part D.5).

Each integration is an MCP server (a stdio command or a streamable-HTTP endpoint) with a
per-server encrypted token. Integrations are administered in Settings → AI and, once
added, their tools are offered to the assistant on each turn. The token is encrypted at
rest (like provider keys) and injected into the server's stdio environment or HTTP
headers when the toolset is built.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from fastmcp.client.transports import StdioTransport, StreamableHttpTransport
from pydantic import BaseModel, Field
from pydantic_ai.mcp import MCPToolset
from sqlmodel import Session, col, select

from athena.assistant.settings import McpStdio, McpTransport
from athena.crypto import SecretBox, SecretError
from athena.db.models import AiIntegration

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntegrationKind:
    """One curated integration: an id, a label and a description."""

    id: str
    label: str
    """Human name shown in the add form, e.g. "GitHub"."""
    description: str
    """What it's for."""


KINDS: tuple[IntegrationKind, ...] = (
    IntegrationKind("github", "GitHub", "Repositories, issues and pull requests."),
    IntegrationKind("linear", "Linear", "Issues, projects and cycles."),
    IntegrationKind("notion", "Notion", "Pages, databases and blocks."),
    IntegrationKind("slack", "Slack", "Channels, messages and users."),
    IntegrationKind("google_workspace", "Google Workspace", "Mail, calendar and Drive."),
    IntegrationKind("day_ai", "Day.ai", "Meeting notes and contacts."),
    IntegrationKind("grain", "Grain", "Meeting recordings and highlights."),
    IntegrationKind("ordinal", "Ordinal", "Calendar and scheduling."),
    IntegrationKind("posthog", "PostHog", "Product analytics and experiments."),
    IntegrationKind("pylon", "Pylon", "Customer support tickets and conversations."),
    IntegrationKind("stackone", "StackOne", "Unified HR, payroll and accounting."),
    IntegrationKind("logfire_mcp", "Logfire", "Observability traces and metrics."),
    IntegrationKind("pixeltable", "PixelTable", "…"),
)
BY_ID = {kind.id: kind for kind in KINDS}


class Integration(BaseModel):
    """One configured hosted integration (the non-secret parts)."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$", min_length=1, max_length=64)
    kind: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    transport: McpTransport
    """How to reach the server: a stdio command or a streamable-HTTP URL."""
    token_env: str | None = Field(default=None, max_length=128)
    """For a stdio server: the env var that receives the decrypted token."""
    token_header: str | None = Field(default=None, max_length=128)
    """For an HTTP server: the header that receives the decrypted token."""


class IntegrationIn(BaseModel):
    """Create or update a hosted integration: the token value is encrypted on write."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$", min_length=1, max_length=64)
    kind: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    transport: McpTransport
    token_env: str | None = Field(default=None, max_length=128)
    token_header: str | None = Field(default=None, max_length=128)
    token: str | None = Field(default=None, max_length=4096)
    """The API token or OAuth access token. Left empty on update keeps the stored value."""


class IntegrationUpdate(BaseModel):
    kind: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    transport: McpTransport
    token_env: str | None = Field(default=None, max_length=128)
    token_header: str | None = Field(default=None, max_length=128)
    token: str | None = Field(default=None, max_length=4096)


class IntegrationOut(BaseModel):
    """What the API returns: everything except the secret token."""

    id: str
    kind: str
    name: str
    transport: McpTransport
    token_env: str | None = None
    token_header: str | None = None
    secrets_set: list[str] = Field(default_factory=list)
    """Which secret fields have a stored value."""


class IntegrationKindOut(BaseModel):
    id: str
    label: str
    description: str


def integration_kinds_out() -> list[IntegrationKindOut]:
    """The curated integration kinds, for the add form."""
    return [IntegrationKindOut(id=k.id, label=k.label, description=k.description) for k in KINDS]


def load(db: Session) -> list[Integration]:
    """All configured integrations, in config order. Unknown kinds are skipped."""
    rows = db.exec(select(AiIntegration).order_by(col(AiIntegration.created_at))).all()
    integrations: list[Integration] = []
    for row in rows:
        if row.kind not in BY_ID:
            log.warning("ignoring hosted integration with unknown kind %r", row.kind)
            continue
        try:
            integrations.append(Integration.model_validate_json(row.config or "{}"))
        except Exception:  # a corrupt row must not break every chat turn
            log.warning("ignoring hosted integration %r with bad config", row.id)
    return integrations


def _token(row: AiIntegration, box: SecretBox, key: str | None) -> str | None:
    """The decrypted token for `key`, or None when there is none or it can't be read."""
    if not row.secrets or not key:
        return None
    try:
        secrets = json.loads(box.decrypt(row.secrets))
    except (SecretError, json.JSONDecodeError):
        log.warning("can't decrypt the token for hosted integration %r", row.id)
        return None
    if isinstance(secrets, dict):
        return secrets.get(key) or None
    return None


def integration_toolsets(rows: list[AiIntegration], box: SecretBox) -> list[MCPToolset[Any]]:
    """Build one MCP toolset per integration, injecting each decrypted token.

    A stdio server receives its token in `token_env`; an HTTP server in `token_header`.
    Integrations whose token can't be decrypted are skipped.
    """
    toolsets: list[MCPToolset[Any]] = []
    for row in rows:
        if row.kind not in BY_ID:
            continue
        try:
            integration = Integration.model_validate_json(row.config or "{}")
        except Exception:
            log.warning("ignoring hosted integration %r with bad config", row.id)
            continue
        transport = integration.transport
        if isinstance(transport, McpStdio):
            env = dict(transport.env or {})
            key = integration.token_env
            token = _token(row, box, key)
            if token is not None and key:
                env[key] = token
            toolsets.append(
                MCPToolset(
                    StdioTransport(
                        command=transport.command,
                        args=transport.args,
                        env=env,
                    )
                )
            )
        else:
            headers = dict(transport.headers or {})
            key = integration.token_header
            token = _token(row, box, key)
            if token is not None and key:
                headers[key] = token
            toolsets.append(
                MCPToolset(
                    StreamableHttpTransport(
                        url=transport.url,
                        headers=headers,
                    )
                )
            )
    return toolsets


def _out(row: AiIntegration, box: SecretBox) -> IntegrationOut:
    """The API shape for one integration row, without the secret token."""
    try:
        integration = Integration.model_validate_json(row.config or "{}")
    except Exception:  # config is validated on write, so this is defensive only
        integration = Integration(
            id=row.id,
            kind=row.kind,
            name=row.name,
            transport=McpStdio(command="x", args=[]),
        )
    secrets_set: list[str] = []
    if row.secrets:
        try:
            secrets = json.loads(box.decrypt(row.secrets))
            if isinstance(secrets, dict):
                secrets_set = sorted(secrets)
        except (SecretError, json.JSONDecodeError):
            pass
    return IntegrationOut(
        id=integration.id,
        kind=integration.kind,
        name=integration.name,
        transport=integration.transport,
        token_env=integration.token_env,
        token_header=integration.token_header,
        secrets_set=secrets_set,
    )
