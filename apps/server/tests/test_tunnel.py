"""Tunnel API: admin-only routes and tunnel secrets encrypted at rest, never returned."""

import json
from pathlib import Path

import pytest
from conftest import make_app, signed_in
from fastapi.testclient import TestClient
from sqlmodel import Session

from athena import system_settings
from athena.db.models import SystemSetting
from athena.system_settings import ENCRYPTED

TOKEN = "cf-super-secret-token"
NGROK = "ngrok-super-secret-token"


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(make_app(tmp_path)) as c:
        yield signed_in(c)


def _stored(client: TestClient) -> dict:
    with Session(client.app.state.db.engine) as db:
        row = db.get(SystemSetting, system_settings.KEY)
        assert row is not None
        return json.loads(row.value)


def _write_raw(client: TestClient, value: dict) -> None:
    with Session(client.app.state.db.engine) as db:
        db.merge(SystemSetting(key=system_settings.KEY, value=json.dumps(value)))
        db.commit()


def _demote(client: TestClient) -> None:
    with client.app.state.db.engine.begin() as conn:
        conn.exec_driver_sql("UPDATE users SET is_admin = 0")


def test_mutating_routes_need_an_admin(client: TestClient) -> None:
    _demote(client)
    calls = [
        client.put("/api/tunnel/config", json={"provider": "ngrok"}),
        client.post("/api/tunnel/install", json={"provider": "ngrok"}),
        client.put("/api/tunnel/service", params={"enabled": True}),
        client.post("/api/tunnel/start"),
        client.post("/api/tunnel/stop"),
    ]
    for res in calls:
        assert res.status_code == 403, (res.request.url, res.text)
    # Reading the status is still fine for everyone signed in.
    assert client.get("/api/tunnel/status").status_code == 200


def test_secrets_are_encrypted_and_never_returned(client: TestClient) -> None:
    config = {"quick_tunnel": False, "tunnel_name": "home", "api_token": TOKEN}
    res = client.put("/api/tunnel/config", json={"provider": "cloudflare", "config": config})
    assert res.status_code == 200, res.text
    assert TOKEN not in res.text
    body = res.json()["settings"]
    assert body["tunnel_config"] == {"quick_tunnel": False, "tunnel_name": "home"}
    assert body["tunnel_secrets_set"] == ["api_token"]

    got = client.get("/api/settings/system")
    assert TOKEN not in got.text
    assert got.json()["tunnel_secrets_set"] == ["api_token"]
    assert "api_token" not in got.json()["tunnel_config"]

    stored = _stored(client)
    assert TOKEN not in json.dumps(stored)
    assert stored["tunnel_config"]["api_token"].startswith(ENCRYPTED)
    assert "tunnel_secrets_set" not in stored

    settings = system_settings.SystemSettings.model_validate(stored)
    box = client.app.state.secret_box
    assert system_settings.provider_config(settings, box)["api_token"] == TOKEN


def test_system_settings_put_keeps_and_encrypts_secrets(client: TestClient) -> None:
    settings = client.get("/api/settings/system").json()
    settings |= {"tunnel_provider": "ngrok", "tunnel_config": {"auth_token": NGROK}}
    res = client.put("/api/settings/system", json=settings)
    assert res.status_code == 200, res.text
    assert NGROK not in res.text
    assert res.json()["tunnel_secrets_set"] == ["auth_token"]
    assert NGROK not in json.dumps(_stored(client))

    # What the UI sends back (no secret) keeps the stored one.
    again = res.json() | {"terminal_enabled": False, "tunnel_config": {"domain": "x.dev"}}
    res = client.put("/api/settings/system", json=again)
    assert res.json()["tunnel_secrets_set"] == ["auth_token"]
    assert res.json()["tunnel_config"] == {"domain": "x.dev"}
    stored = _stored(client)["tunnel_config"]
    box = client.app.state.secret_box
    assert box.decrypt(stored["auth_token"].removeprefix(ENCRYPTED)) == NGROK

    # An explicit null clears it.
    res = client.put("/api/settings/system", json=again | {"tunnel_config": {"auth_token": None}})
    assert res.json()["tunnel_secrets_set"] == []
    assert "auth_token" not in _stored(client)["tunnel_config"]


def test_plaintext_secrets_from_older_servers_still_work(client: TestClient) -> None:
    _write_raw(
        client,
        {"tunnel_provider": "ngrok", "tunnel_config": {"auth_token": NGROK, "domain": "a.dev"}},
    )
    got = client.get("/api/settings/system")
    assert NGROK not in got.text
    assert got.json()["tunnel_secrets_set"] == ["auth_token"]

    box = client.app.state.secret_box
    with Session(client.app.state.db.engine) as db:
        settings = system_settings.load(db)
    assert system_settings.provider_config(settings, box)["auth_token"] == NGROK

    # The next save encrypts it.
    res = client.put("/api/tunnel/config", json={"port": 9000})
    assert res.status_code == 200, res.text
    res = client.put("/api/tunnel/config", json={"config": {"domain": "b.dev"}})
    assert res.status_code == 200, res.text
    stored = _stored(client)
    assert NGROK not in json.dumps(stored)
    assert stored["tunnel_port"] == 9000
    assert box.decrypt(stored["tunnel_config"]["auth_token"].removeprefix(ENCRYPTED)) == NGROK
