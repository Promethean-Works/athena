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


# ---------------------------------------------------------------- token clients act as the admin

TOKEN = "test-secret-token-456"
TOKEN_HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@contextlib.contextmanager
def _token_client(tmp_path, monkeypatch, *, with_admin: bool, store=None):
    """A client that talks MCP with only the bearer token (no session cookie)."""
    from conftest import ADMIN, make_app

    monkeypatch.setenv("ATHENA_MCP_TOKEN", TOKEN)
    with TestClient(make_app(tmp_path, store=store)) as client:
        if with_admin:
            assert client.post("/api/auth/setup", json=ADMIN).status_code == 201
            client.cookies.clear()
        yield client


def _token_init(client: TestClient) -> str:
    resp = client.post("/api/mcp", json=MCP_INIT, headers={**ACCEPT, **TOKEN_HEADERS})
    assert resp.status_code == 200, resp.text
    return resp.headers["Mcp-Session-Id"]


def _token_tool(client: TestClient, sid: str, name: str, arguments: dict) -> dict:
    return _mcp_call(
        client,
        sid,
        "tools/call",
        {"name": name, "arguments": arguments},
        extra_headers=TOKEN_HEADERS,
    )["result"]


def _audit_rows(client: TestClient) -> list[tuple]:
    with client.app.state.db.engine.connect() as conn:
        return list(
            conn.exec_driver_sql(
                "SELECT username, action, target, detail FROM audit_log ORDER BY id"
            )
        )


def test_mcp_token_creates_trigger_as_admin(tmp_path, monkeypatch):
    with _token_client(tmp_path, monkeypatch, with_admin=True) as client:
        sid = _token_init(client)
        result = _token_tool(
            client,
            sid,
            "create_automation_trigger",
            {
                "kind": "cron",
                "name": "nightly",
                "cron_expression": "0 2 * * *",
                "action": {"kind": "app", "name": "site", "verb": "restart"},
            },
        )
        assert not result.get("isError"), result
        assert result["structuredContent"]["id"]
        assert (
            "admin",
            "automation.trigger.create",
            "nightly",
            "cron:nightly (via MCP token)",
        ) in (_audit_rows(client))

        # list_apps also resolves the user; it must not 404 for token clients.
        assert not _token_tool(client, sid, "list_apps", {}).get("isError")


def test_mcp_token_without_admin_fails_clearly(tmp_path, monkeypatch):
    with _token_client(tmp_path, monkeypatch, with_admin=False) as client:
        sid = _token_init(client)
        result = _token_tool(
            client,
            sid,
            "create_automation_trigger",
            {
                "kind": "http",
                "name": "hook",
                "action": {"kind": "app", "name": "site", "verb": "start"},
            },
        )
        assert result.get("isError"), result
        assert "no admin account" in result["content"][0]["text"]
        assert _audit_rows(client) == []


def test_mcp_token_app_action_runs_as_admin(tmp_path, monkeypatch):
    import sys

    from conftest import ADMIN
    from test_apps import COMPOSE, wait
    from test_containers import SAMPLE, ready_store

    import athena.api.apps as apps_api
    from athena.containers import service as containers_service

    monkeypatch.setattr("athena.containers.runtime.shutil.which", lambda b: f"/usr/bin/{b}")
    monkeypatch.setattr(containers_service, "list_containers", lambda rt: [SAMPLE])
    monkeypatch.setattr(
        apps_api,
        "compose",
        lambda runtime, name, path, *args: [sys.executable, "-c", f"print('compose {args[0]}')"],
    )
    with _token_client(tmp_path, monkeypatch, with_admin=False, store=ready_store()) as client:
        signed_in(client)
        wait(
            client, client.post("/api/apps", json={"name": "site", "compose": COMPOSE}).json()["id"]
        )
        client.cookies.clear()

        sid = _token_init(client)
        result = _token_tool(client, sid, "app_action", {"name": "site", "verb": "restart"})
        assert not result.get("isError"), result
        job_id = result["structuredContent"]["job_id"]

        # Sign back in only to read the job's result.
        res = client.post("/api/auth/login", json=ADMIN)
        assert res.status_code == 200, res.text
        assert wait(client, job_id)["status"] == "succeeded"
        assert ("admin", "app.restart", "site", "via MCP token") in _audit_rows(client)


def test_mcp_reached_when_web_ui_is_bundled(tmp_path: Path) -> None:
    """The web UI's "/" mount must not swallow /api/mcp (it answered 405 before)."""
    from conftest import make_app

    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_bytes(b"<html></html>")
    with TestClient(make_app(tmp_path, web_dir=web)) as client:
        signed_in(client)
        resp = client.post("/api/mcp", json=MCP_INIT, headers=ACCEPT, follow_redirects=False)
        assert resp.status_code == 200, resp.text
        assert resp.headers.get("Mcp-Session-Id")
        assert client.get("/").status_code == 200  # the UI still serves
