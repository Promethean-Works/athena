"""Outside MCP servers' tools need an Approve card, unless marked read-only."""

import asyncio
from typing import Any

import pytest
from fastmcp import FastMCP
from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.exceptions import UserError
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import ToolDefinition

from athena.assistant import mcp as athena_mcp


def _server() -> FastMCP:
    server = FastMCP("outside")

    @server.tool(annotations={"readOnlyHint": True})
    def look_up(topic: str) -> str:
        return f"notes on {topic}"

    @server.tool
    def delete_everything(path: str) -> str:
        return f"deleted {path}"

    return server


def _toolset(can_ask: bool):
    from pydantic_ai.mcp import MCPToolset

    return athena_mcp.guard(MCPToolset(_server()), can_ask=can_ask)


def _run(toolset, call: str) -> Any:
    agent = Agent(
        TestModel(call_tools=[call]),
        toolsets=[toolset],
        output_type=[str, DeferredToolRequests],
    )

    async def go() -> Any:
        async with agent:
            return (await agent.run("go")).output

    return asyncio.run(go())


def test_a_tool_without_the_read_only_hint_waits_for_approval() -> None:
    out = _run(_toolset(can_ask=True), "delete_everything")
    assert isinstance(out, DeferredToolRequests)
    assert [c.tool_name for c in out.approvals] == ["delete_everything"]


def test_a_read_only_tool_runs_without_a_card() -> None:
    out = _run(_toolset(can_ask=True), "look_up")
    assert not isinstance(out, DeferredToolRequests)
    assert "notes on" in out


def test_a_helper_agent_only_gets_the_read_only_tools() -> None:
    assert "notes on" in _run(_toolset(can_ask=False), "look_up")
    # The tool isn't offered at all: the test model can't even be told to call it.
    with pytest.raises(UserError, match="unknown tool"):
        _run(_toolset(can_ask=False), "delete_everything")


def test_read_only_hint_must_be_exactly_true() -> None:
    def tool(meta: dict | None) -> ToolDefinition:
        return ToolDefinition(name="t", metadata=meta)

    assert athena_mcp.is_read_only(tool({"annotations": {"readOnlyHint": True}}))
    for meta in (None, {}, {"annotations": None}, {"annotations": {"readOnlyHint": "yes"}}):
        assert not athena_mcp.is_read_only(tool(meta))
