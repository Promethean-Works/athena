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

from athena.assistant.settings import McpServer, McpStdio


def mcp_toolsets(servers: list[McpServer]) -> list[MCPToolset[Any]]:
    """Build one MCP toolset per configured server, in config order.

    Each toolset is a fresh instance: never share one across concurrent runs.
    """
    toolsets: list[MCPToolset[Any]] = []
    for server in servers:
        transport = server.transport
        if isinstance(transport, McpStdio):
            toolsets.append(
                MCPToolset(
                    StdioTransport(
                        command=transport.command,
                        args=transport.args,
                        env=transport.env or None,
                    )
                )
            )
        else:
            toolsets.append(
                MCPToolset(
                    StreamableHttpTransport(
                        url=transport.url,
                        headers=transport.headers or None,
                    )
                )
            )
    return toolsets
