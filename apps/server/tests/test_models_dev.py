"""models.dev provider kinds: the cache refresh, the kinds list and dynamic providers."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from conftest import make_app, signed_in
from fastapi.testclient import TestClient
from sqlmodel import select

from athena.assistant import models_dev
from athena.assistant.models_dev import ModelsDevProvider, ModelsDevService
from athena.db.engine import Database
from athena.db.models import ModelsDevCache

FAKE = {
    "acme-ai": ModelsDevProvider(
        id="acme-ai",
        name="Acme AI",
        models={"acme-1": {"id": "acme-1", "name": "Acme 1", "limit": {"context": 8192}}},
        env=["ACME_API_KEY"],
        api="https://api.acme.example/v1",
        npm="@ai-sdk/openai-compatible",
        doc="https://acme.example/docs",
    ),
    "closed-ai": ModelsDevProvider(
        id="closed-ai",
        name="Closed AI",
        models={"c-1": {"id": "c-1"}},
        env=[],
        api="",
        npm="@closed/sdk",
        doc="",
    ),
}


@pytest.fixture
def fake_fetch(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []

    async def fetch(self: ModelsDevService) -> dict:
        calls.append(1)
        return FAKE

    monkeypatch.setattr(ModelsDevService, "_fetch_models_dev", fetch)
    return calls


def _db(tmp_path) -> Database:
    db = Database(tmp_path / "athena.db")
    db.migrate()
    return db


def test_refresh_fills_the_cache_with_a_generator_session(tmp_path, fake_fetch):
    # Database.session is a generator function, which is what the app passes in.
    service = ModelsDevService(_db(tmp_path).session)
    assert asyncio.run(service.ensure_cache_fresh()) == 2
    ids = [k.id for k in service.get_dynamic_kinds()]
    assert ids == ["acme-ai"]  # not OpenAI-compatible providers stay out
    kind = service.get_kind("acme-ai")
    assert kind is not None
    assert kind.label == "Acme AI"
    base = next(f for f in kind.fields if f.key == "base_url")
    assert base.default == "https://api.acme.example/v1"
    assert "ACME_API_KEY" in (kind.fields[0].help or "")
    assert service.get_models("acme-ai")[0]["id"] == "acme-1"


def test_fresh_cache_is_not_refetched_but_force_is(tmp_path, fake_fetch):
    db = _db(tmp_path)
    asyncio.run(ModelsDevService(db.session).ensure_cache_fresh())
    # A new service (a restart) reads the fresh cache from SQLite (naive datetimes).
    service = ModelsDevService(db.session)
    assert asyncio.run(service.ensure_cache_fresh()) == 0
    assert asyncio.run(service.ensure_cache_fresh(force=True)) == 2
    assert len(fake_fetch) == 2


def test_expired_cache_is_still_served_and_refetched(tmp_path, fake_fetch):
    db = _db(tmp_path)
    service = ModelsDevService(db.session)
    asyncio.run(service.ensure_cache_fresh())
    for session in db.session():
        for row in session.exec(select(ModelsDevCache)).all():
            row.expires_at = datetime.now(UTC) - timedelta(hours=1)
            session.add(row)
        session.commit()
    restarted = ModelsDevService(db.session)
    assert [k.id for k in restarted.get_dynamic_kinds()] == ["acme-ai"]  # offline host
    assert asyncio.run(restarted.ensure_cache_fresh()) == 2


def test_app_start_fills_kinds_and_a_dynamic_provider_survives_a_restart(tmp_path, fake_fetch):
    with TestClient(make_app(tmp_path)) as client:
        signed_in(client)
        # The startup refresh runs in the background; force one to be deterministic.
        res = client.post("/api/assistant/kinds/refresh")
        assert res.status_code == 202, res.text
        kinds = [k["id"] for k in client.get("/api/assistant/kinds").json()]
        assert "acme-ai" in kinds and "anthropic" in kinds
        res = client.post(
            "/api/assistant/providers",
            json={"kind": "acme-ai", "name": "Acme", "values": {"api_key": "sk-test"}},
        )
        assert res.status_code == 201, res.text
        provider_id = res.json()["id"]

    # Restart: nothing in memory remembers the kind, only the cache table.
    models_dev._service = None
    with TestClient(make_app(tmp_path)) as client:
        client.headers["X-CSRF-Token"] = ""
        res = client.post(
            "/api/auth/login", json={"username": "admin", "password": "correct horse battery"}
        )
        assert res.status_code == 200, res.text
        client.headers["X-CSRF-Token"] = res.json()["csrf_token"]
        listed = client.get("/api/assistant/providers").json()
        assert [p["id"] for p in listed] == [provider_id]
        res = client.put(
            f"/api/assistant/providers/{provider_id}",
            json={"name": "Acme 2", "values": {}},
        )
        assert res.status_code == 200, res.text


def test_unknown_kind_is_refused(tmp_path):
    with TestClient(make_app(tmp_path)) as client:
        signed_in(client)
        res = client.post(
            "/api/assistant/providers",
            json={"kind": "nope", "name": "x", "values": {}},
        )
        assert res.status_code == 422
