"""Tunnel API: admin-only routes and tunnel secrets encrypted at rest, never returned."""

import json
from pathlib import Path

import pytest
from conftest import make_app, signed_in
from fastapi.testclient import TestClient

from athena import system_settings
from athena.system_settings import ENCRYPTED

TOKEN = "cf-super-secret-token"
NGROK = "ngrok-super-secret-token"


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(make_app(tmp_path)) as c:
        yield signed_in(c)


def _stored(client: TestClient) -> dict:
    """The system section of athena.json as it is on disk."""
    path = client.app.state.settings_file.path
    return json.loads(path.read_text(encoding="utf-8"))["system"]


def _write_raw(client: TestClient, value: dict) -> None:
    """Hand-edit athena.json's system section, then restart (reload the file)."""
    settings_file = client.app.state.settings_file
    data = json.loads(settings_file.path.read_text(encoding="utf-8"))
    data["system"] = value
    settings_file.path.write_bytes(json.dumps(data).encode())
    settings_file.load()


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


def test_plaintext_secrets_typed_into_the_file_work(client: TestClient) -> None:
    _write_raw(
        client,
        {"tunnel_provider": "ngrok", "tunnel_config": {"auth_token": NGROK, "domain": "a.dev"}},
    )
    got = client.get("/api/settings/system")
    assert NGROK not in got.text
    assert got.json()["tunnel_secrets_set"] == ["auth_token"]

    box = client.app.state.secret_box
    settings = system_settings.load(client.app.state.settings_file)
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


class FakeProvider:
    label = "Fake"

    def __init__(self, running: bool = False) -> None:
        self.running = running
        self.started: list = []

    def status(self):
        from athena.tunnel.base import TunnelStatus

        return TunnelStatus(running=self.running)

    async def start(self, job, config) -> str:
        self.started.append(config)
        return "https://fake.example"

    def shutdown(self) -> None:
        pass


def _boot(
    tmp_path: Path, monkeypatch, system: dict, provider: FakeProvider, wait: bool = False
) -> list:
    """Start the server (its lifespan runs the auto-start) and return the fake's starts."""
    from athena.tunnel import TUNNEL_PROVIDERS

    monkeypatch.setitem(TUNNEL_PROVIDERS, "tunnel.cloudflare", provider)
    app = make_app(tmp_path)
    settings_file = app.state.settings_file
    data = json.loads(settings_file.path.read_text(encoding="utf-8"))
    data["system"] = system
    settings_file.path.write_bytes(json.dumps(data).encode())
    settings_file.load()
    with TestClient(app) as c:
        signed_in(c)
        import time

        for _ in range(50 if wait else 0):
            if provider.started:
                break
            time.sleep(0.1)
    return provider.started


def test_tunnel_starts_at_boot_when_enabled(tmp_path: Path, monkeypatch) -> None:
    fake = FakeProvider()
    started = _boot(
        tmp_path,
        monkeypatch,
        {"tunnel_enabled": True, "tunnel_provider": "cloudflare", "tunnel_port": 9001},
        fake,
        wait=True,
    )
    assert [c.port for c in started] == [9001]


@pytest.mark.parametrize(
    "system",
    [
        {"tunnel_enabled": False, "tunnel_provider": "cloudflare"},
        {"tunnel_enabled": True, "tunnel_provider": "cloudflare", "tunnel_auto_start": False},
        {"tunnel_enabled": True, "tunnel_provider": None},
        {"tunnel_enabled": True, "tunnel_provider": "nope"},
    ],
)
def test_tunnel_does_not_start_at_boot_unless_asked(tmp_path: Path, monkeypatch, system) -> None:
    from athena.tunnel import autostart

    monkeypatch.setattr(autostart, "start_job", lambda *a: pytest.fail("started"))
    assert _boot(tmp_path, monkeypatch, system, FakeProvider()) == []


def test_boot_survives_an_unreadable_secret(tmp_path: Path, monkeypatch) -> None:
    system = {
        "tunnel_enabled": True,
        "tunnel_provider": "cloudflare",
        "tunnel_config": {"api_token": ENCRYPTED + "garbage"},
    }
    assert _boot(tmp_path, monkeypatch, system, FakeProvider()) == []
