"""Assistant settings (Settings → AI). Host-wide, admins only; one JSON row in
`system_settings` under the key "ai". Invalid stored values fall back to defaults."""

import logging
from typing import Annotated, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator
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


class McpStdio(BaseModel):
    """An MCP server launched with a local command (stdio transport)."""

    type: Literal["stdio"] = "stdio"
    command: str = Field(min_length=1, max_length=255)
    """The program to run, e.g. `npx` or `uvx`."""
    args: list[str] = Field(default_factory=list, max_length=50)
    """Arguments passed to the command; no shell is used."""
    env: dict[str, str] = Field(default_factory=dict, max_length=50)
    """Extra environment variables for the subprocess."""


class McpHttp(BaseModel):
    """An MCP server reached over streamable HTTP."""

    type: Literal["http"] = "http"
    url: str = Field(min_length=1, max_length=1024)
    """The server's MCP endpoint, e.g. http://127.0.0.1:8000/mcp."""
    headers: dict[str, str] = Field(default_factory=dict, max_length=50)
    """Extra HTTP headers sent with every request."""


McpTransport = Annotated[McpStdio | McpHttp, Field(discriminator="type")]
"""A connection to one MCP server: stdio or streamable HTTP."""


class McpServer(BaseModel):
    """One configured MCP server the assistant may use."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$", min_length=1, max_length=64)
    """Unique id used to reference the server, e.g. `filesystem` or `github`."""
    transport: McpTransport


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
    web_research_enabled: bool = False
    """Lets the assistant search the web with Exa (needs EXA_API_KEY in the
    server environment)."""
    review_model: ModelRef | None = None
    """A second model that reviews each action awaiting approval, auto-approving
    low-risk ones so the admin only sees the risky ones (off when empty)."""
    review_tool_calls: bool = False
    """Let the review model approve safe actions before the admin sees them."""
    mcp_servers: list[McpServer] = Field(default_factory=list, max_length=50)
    """MCP servers the assistant can connect to and use tools from (Settings → AI)."""

    @model_validator(mode="after")
    def _unique_mcp_ids(self) -> "AiSettings":
        seen: set[str] = set()
        for server in self.mcp_servers:
            if server.id in seen:
                raise ValueError(f"MCP server id {server.id!r} is used more than once")
            seen.add(server.id)
        return self


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
