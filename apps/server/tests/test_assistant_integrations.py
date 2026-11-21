"""Hosted integrations (`integrations.py`, M7 part D.5)."""

import json
from datetime import UTC, datetime

from conftest import make_app, signed_in
from fastapi.testclient import TestClient
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport
from pydantic_ai.mcp import MCPToolset
from sqlmodel import select

from athena.assistant.integrations import BY_ID, Integration, integration_toolsets
from athena.crypto import SecretBox
from athena.db.models import AiIntegration, AuditEntry


def app_box(app):
    return SecretBox(app.state.settings.data_dir)


def add_integration(session, box, config: Integration, token="secret-token") -> AiIntegration:
    secret = {}
    key = config.token_env or config.token_header
    if token and key:
        secret = {key: token}
    row = AiIntegration(
        id=config.id,
        kind=config.kind,
        name=config.name,
        config=config.model_dump_json(),
        secrets=box.encrypt(json.dumps(secret)) if secret else None,
        created_at=datetime.now(UTC),
    )
    session.add(row)
    session.commit()
    return row


def transport_of(toolset: MCPToolset):
    return toolset._client_source


def test_kinds_are_curated():
    assert "github" in BY_ID and "linear" in BY_ID and "notion" in BY_ID
    assert len(BY_ID) == 13


def test_kinds_endpoint(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        signed_in(client)
        res = client.get("/api/assistant/integrations/kinds")
        assert res.status_code == 200, res.text
        body = res.json()
        assert len(body) == 13
        assert body[0] == {
            "id": "github",
            "label": "GitHub",
            "description": "Repositories, issues and pull requests.",
        }
        # list is empty by default
        listed = client.get("/api/assistant/integrations").json()
        assert listed == []


def test_integration_toolsets_are_empty_with_none(tmp_path):
    assert integration_toolsets([], app_box(make_app(tmp_path))) == []


def test_toolset_injects_token_into_stdio_env(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        signed_in(client)
    config = Integration(
        id="github",
        kind="github",
        name="GitHub",
        transport={"type": "stdio", "command": "npx", "args": ["-y", "x"]},
        token_env="GITHUB_PERSONAL_ACCESS_TOKEN",
    )
    for session in app.state.db.session():
        add_integration(session, app_box(app), config)
    for session in app.state.db.session():
        rows = session.exec(select(AiIntegration)).all()
    caps = integration_toolsets(rows, app_box(app))
    assert len(caps) == 1
    transport = transport_of(caps[0])
    assert isinstance(transport, StdioTransport)
    assert transport.command == "npx"
    assert transport.args == ["-y", "x"]
    assert transport.env["GITHUB_PERSONAL_ACCESS_TOKEN"] == "secret-token"


def test_integration_without_a_token_gets_no_env(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        signed_in(client)
    config = Integration(
        id="x",
        kind="github",
        name="X",
        transport={"type": "stdio", "command": "npx", "args": []},
    )
    for session in app.state.db.session():
        add_integration(session, app_box(app), config, token=None)
    for session in app.state.db.session():
        rows = session.exec(select(AiIntegration)).all()
    caps = integration_toolsets(rows, app_box(app))
    assert len(caps) == 1
    transport = transport_of(caps[0])
    assert isinstance(transport, StdioTransport)
    assert "GITHUB_PERSONAL_ACCESS_TOKEN" not in transport.env


def test_integration_can_be_http(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        signed_in(client)
    config = Integration(
        id="slack",
        kind="slack",
        name="Slack",
        transport={"type": "http", "url": "https://slack.example/mcp"},
        token_header="Authorization",
    )
    for session in app.state.db.session():
        add_integration(session, app_box(app), config)
    for session in app.state.db.session():
        rows = session.exec(select(AiIntegration)).all()
    caps = integration_toolsets(rows, app_box(app))
    assert len(caps) == 1
    transport = transport_of(caps[0])
    assert isinstance(transport, StreamableHttpTransport)
    assert transport.url == "https://slack.example/mcp"
    assert transport.headers["Authorization"] == "secret-token"


def test_integration_api_round_trip(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        signed_in(client)
        created = client.post(
            "/api/assistant/integrations",
            json={
                "id": "github",
                "kind": "github",
                "name": "GitHub",
                "transport": {"type": "stdio", "command": "npx", "args": ["-y", "x"]},
                "token_env": "GITHUB_PERSONAL_ACCESS_TOKEN",
                "token": "secret-token",
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["id"] == "github"
        assert body["secrets_set"] == ["GITHUB_PERSONAL_ACCESS_TOKEN"]
        # the token is never returned in clear
        assert "secret-token" not in json.dumps(body)
        assert "secret-token" not in client.get("/api/assistant/integrations").text

        # list
        listed = client.get("/api/assistant/integrations").json()
        assert len(listed) == 1
        assert listed[0]["secrets_set"] == ["GITHUB_PERSONAL_ACCESS_TOKEN"]

        # update with an empty token keeps the stored value
        updated = client.put(
            "/api/assistant/integrations/github",
            json={
                "kind": "github",
                "name": "GitHub (work)",
                "transport": {"type": "stdio", "command": "npx", "args": ["-y", "x"]},
                "token_env": "GITHUB_PERSONAL_ACCESS_TOKEN",
                "token": "",
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == "GitHub (work)"
        assert updated.json()["secrets_set"] == ["GITHUB_PERSONAL_ACCESS_TOKEN"]

        # update with a new token replaces it
        rekeyed = client.put(
            "/api/assistant/integrations/github",
            json={
                "kind": "github",
                "name": "GitHub (work)",
                "transport": {"type": "stdio", "command": "npx", "args": ["-y", "x"]},
                "token_env": "GITHUB_PERSONAL_ACCESS_TOKEN",
                "token": "new-token",
            },
        )
        assert rekeyed.status_code == 200, rekeyed.text
        assert "new-token" not in json.dumps(rekeyed.json())

        # delete
        gone = client.delete("/api/assistant/integrations/github")
        assert gone.status_code == 204, gone.text
        assert client.get("/api/assistant/integrations").json() == []

        for session in app.state.db.session():
            assert session.get(AiIntegration, "github") is None


def test_integration_validation(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        signed_in(client)
        # unknown kind
        res = client.post(
            "/api/assistant/integrations",
            json={
                "id": "nope",
                "kind": "nope",
                "name": "Nope",
                "transport": {"type": "stdio", "command": "npx", "args": []},
            },
        )
        assert res.status_code == 422, res.text
        # duplicate id
        client.post(
            "/api/assistant/integrations",
            json={
                "id": "github",
                "kind": "github",
                "name": "GitHub",
                "transport": {"type": "stdio", "command": "npx", "args": []},
                "token_env": "GITHUB_PERSONAL_ACCESS_TOKEN",
                "token": "t",
            },
        )
        res = client.post(
            "/api/assistant/integrations",
            json={
                "id": "github",
                "kind": "github",
                "name": "GitHub",
                "transport": {"type": "stdio", "command": "npx", "args": []},
                "token_env": "GITHUB_PERSONAL_ACCESS_TOKEN",
                "token": "t",
            },
        )
        assert res.status_code == 422, res.text
        # token without an env var/header
        res = client.post(
            "/api/assistant/integrations",
            json={
                "id": "linear",
                "kind": "linear",
                "name": "Linear",
                "transport": {"type": "stdio", "command": "npx", "args": []},
                "token": "t",
            },
        )
        assert res.status_code == 422, res.text
        # not found on update/delete (valid bodies, missing row)
        assert (
            client.put(
                "/api/assistant/integrations/missing",
                json={
                    "kind": "github",
                    "name": "x",
                    "transport": {"type": "stdio", "command": "npx", "args": []},
                },
            ).status_code
            == 404
        )
        assert client.delete("/api/assistant/integrations/missing").status_code == 404


def test_integration_is_audited(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        signed_in(client)
        client.post(
            "/api/assistant/integrations",
            json={
                "id": "github",
                "kind": "github",
                "name": "GitHub",
                "transport": {"type": "stdio", "command": "npx", "args": []},
                "token_env": "GITHUB_PERSONAL_ACCESS_TOKEN",
                "token": "t",
            },
        )
        client.delete("/api/assistant/integrations/github")
    db = app.state.db
    for session in db.session():
        actions = [e.action for e in session.exec(select(AuditEntry)).all()]
        assert "ai.integration.create" in actions
        assert "ai.integration.remove" in actions
