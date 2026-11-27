"""MCP (Model Context Protocol) client toolsets for the assistant's agents.

Builds a `pydantic_ai.mcp.MCPToolset` per configured MCP server. Each call creates fresh
instances so concurrent runs never share a connection; the agent's run context manager
connects and disconnects them for the duration of the turn.

Servers are configured in Settings → AI (`ai_settings.mcp_servers`): a stdio server runs a
local command, an http server is reached over streamable HTTP.
"""

from typing import Any

from fastmcp.client.transports import StdioTransport, StreamableHttpTransport
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.tools import RunContext, ToolDefinition
from pydantic_ai.toolsets import AbstractToolset

from athena.assistant.settings import McpServer, McpStdio


def is_read_only(tool_def: ToolDefinition) -> bool:
    """Whether the server marks the tool read-only (the MCP `readOnlyHint` annotation)."""
    annotations = (tool_def.metadata or {}).get("annotations") or {}
    return annotations.get("readOnlyHint") is True


def _needs_approval(_ctx: RunContext[Any], tool_def: ToolDefinition, _args: dict[str, Any]) -> bool:
    return not is_read_only(tool_def)


def _only_read_only(_ctx: RunContext[Any], tool_def: ToolDefinition) -> bool:
    return is_read_only(tool_def)


def guard(toolset: AbstractToolset[Any], *, can_ask: bool = True) -> AbstractToolset[Any]:
    """Put an outside server's tools behind the same approval as Athena's own actions.

    Tool results (web pages, logs) can carry a prompt injection, and a server's tools can
    change things, so a call needs an Approve card unless the server marks the tool
    read-only. A helper agent can't ask anyone, so with `can_ask=False` it only gets the
    read-only tools.
    """
    if can_ask:
        return toolset.approval_required(_needs_approval)
    return toolset.filtered(_only_read_only)


def mcp_toolsets(servers: list[McpServer], *, can_ask: bool = True) -> list[AbstractToolset[Any]]:
    """Build one MCP toolset per configured server, in config order, behind `guard`.

    Each toolset is a fresh instance: never share one across concurrent runs.
    """
    toolsets: list[AbstractToolset[Any]] = []
    for server in servers:
        transport = server.transport
        if isinstance(transport, McpStdio):
            client = MCPToolset(
                StdioTransport(
                    command=transport.command, args=transport.args, env=transport.env or None
                )
            )
        else:
            client = MCPToolset(
                StreamableHttpTransport(url=transport.url, headers=transport.headers or None)
            )
        toolsets.append(guard(client, can_ask=can_ask))
    return toolsets
