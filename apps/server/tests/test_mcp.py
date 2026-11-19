"""MCP server tests."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

from conftest import signed_in
from fastapi.testclient import TestClient

from athena.config import Settings
from athena.main import create_app

MCP_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}

ACCEPT = {"Accept": "application/json, text/event-stream"}


def _sse_json(text: str) -> dict:
    """Extract the JSON payload from a streamable-HTTP SSE response."""
    for line in text.splitlines():
        if line.startswith("data: "):
            import json as _json

            return _json.loads(line[len("data: ") :])
    raise AssertionError(f"no SSE data line in: {text!r}")


def _mcp_init(client: TestClient) -> str:
    resp = client.post("/api/mcp", json=MCP_INIT, headers=ACCEPT)
    assert resp.status_code == 200, resp.text
    sid = resp.headers.get("Mcp-Session-Id")
    assert sid is not None, "initialize must return a Mcp-Session-Id"
    return sid


def _mcp_call(
    client: TestClient,
    sid: str,
    method: str,
    params: dict | None = None,
    extra_headers: dict[str, str] | None = None,
):
    headers = {**ACCEPT, "Mcp-Session-Id": sid}
    if extra_headers:
        headers.update(extra_headers)
    body = {"jsonrpc": "2.0", "id": 2, "method": method, "params": params or {}}
    resp = client.post("/api/mcp", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return _sse_json(resp.text)


@contextlib.contextmanager
def _client(tmp_path):
    from athena.config import Settings

    settings = Settings(data_dir=tmp_path / "data", web_dir=tmp_path / "no-web")
    app = create_app(settings)
    with TestClient(app) as client:
        yield client


def test_mcp_tools_list_with_session(tmp_path):
    with _client(tmp_path) as client:
        signed_in(client)
        sid = _mcp_init(client)
        result = _mcp_call(client, sid, "tools/list")
        tools = result["result"]["tools"]
        names = {t["name"] for t in tools}
        assert {
            "list_apps",
            "list_capabilities",
            "host_stats",
            "app_action",
            "list_automation_triggers",
        } <= names


def test_mcp_requires_auth(tmp_path):
    # Unauthenticated (no session cookie, no bearer token) is rejected.
    with _client(tmp_path) as client:
        resp = client.post("/api/mcp", json=MCP_INIT, headers=ACCEPT)
        assert resp.status_code == 401


def test_mcp_call_tool_with_session(tmp_path):
    with _client(tmp_path) as client:
        signed_in(client)
        sid = _mcp_init(client)

        result = _mcp_call(client, sid, "tools/call", {"name": "list_apps", "arguments": {}})
        assert "structuredContent" in result["result"]

        result = _mcp_call(
            client,
            sid,
            "tools/call",
            {"name": "list_capabilities", "arguments": {}},
        )
        content = result["result"]["structuredContent"]["result"]
        assert isinstance(content, list) and len(content) > 0


def test_mcp_call_tool_with_bearer_token(tmp_path):
    os.environ["ATHENA_MCP_TOKEN"] = "test-secret-token-123"
    try:
        settings = Settings(
            data_dir=Path("/tmp/mcpbearer") / "data", web_dir=Path("/tmp/mcpbearer") / "no-web"
        )
        app = create_app(settings)
        with TestClient(app) as client:
            headers = {**ACCEPT, "Authorization": "Bearer test-secret-token-123"}
            resp = client.post("/api/mcp", json=MCP_INIT, headers=headers)
            assert resp.status_code == 200, resp.text
            sid = resp.headers.get("Mcp-Session-Id")
            assert sid is not None

            result = _mcp_call(
                client,
                sid,
                "tools/list",
                extra_headers={"Authorization": "Bearer test-secret-token-123"},
            )
            assert len(result["result"]["tools"]) > 0
    finally:
        del os.environ["ATHENA_MCP_TOKEN"]
