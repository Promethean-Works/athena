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
    "anthropic": ModelsDevProvider(
        id="anthropic",
        name="Anthropic (models.dev)",
        models={"claude-x": {"id": "claude-x"}},
        env=["ANTHROPIC_API_KEY"],
        api="",
        npm="@ai-sdk/anthropic",
        doc="",
    ),
    "mini-max": ModelsDevProvider(
        id="mini-max",
        name="MiniMax",
        models={"m2": {"id": "m2"}},
        env=["MINIMAX_API_KEY"],
        api="https://api.minimax.example/anthropic/v1",
        npm="@ai-sdk/anthropic",
        doc="",
    ),
    "studio": ModelsDevProvider(
        id="studio",
        name="Studio",
        models={"s1": {"id": "s1"}},
        env=[],
        api="http://127.0.0.1:1234/v1",
        npm="@ai-sdk/openai-compatible",
        doc="",
    ),
    "templated": ModelsDevProvider(
        id="templated",
        name="Templated",
        models={"t1": {"id": "t1"}},
        env=[],
        api="https://${HOST}/v1",
        npm="@ai-sdk/openai-compatible",
        doc="",
    ),
    "cerebras": ModelsDevProvider(
        id="cerebras",
        name="Cerebras",
        models={"c1": {"id": "c1"}},
        env=[],
        api="",
        npm="@ai-sdk/cerebras",
        doc="",
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
    assert asyncio.run(service.ensure_cache_fresh()) == len(FAKE)
    ids = {k.id for k in service.get_kinds()}
    # Only providers pydantic-ai can't reach stay out.
    assert ids == {"acme-ai", "anthropic", "mini-max", "studio", "templated", "cerebras"}
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
    assert asyncio.run(service.ensure_cache_fresh(force=True)) == len(FAKE)
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
    assert "acme-ai" in {k.id for k in restarted.get_kinds()}  # offline host
    assert asyncio.run(restarted.ensure_cache_fresh()) == len(FAKE)


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


def _kinds(tmp_path, fake_fetch) -> dict:
    service = ModelsDevService(_db(tmp_path).session)
    asyncio.run(service.ensure_cache_fresh())
    return {k.id: k for k in service.get_kinds()}


def test_native_kinds_keep_their_form_but_take_the_models_dev_name(tmp_path, fake_fetch):
    claude = _kinds(tmp_path, fake_fetch)["anthropic"]
    assert claude.label == "Anthropic (models.dev)"
    assert [f.key for f in claude.fields] == ["api_key", "base_url"]


def test_local_and_templated_urls(tmp_path, fake_fetch):
    kinds = _kinds(tmp_path, fake_fetch)
    studio = kinds["studio"]
    assert studio.group == "local"
    assert not next(f for f in studio.fields if f.key == "api_key").required
    url = next(f for f in kinds["templated"].fields if f.key == "base_url")
    assert url.required and url.default is None and url.placeholder == "https://${HOST}/v1"
    cerebras = next(f for f in kinds["cerebras"].fields if f.key == "base_url")
    assert cerebras.default == "https://api.cerebras.ai/v1"


def test_the_kinds_list_fills_an_empty_cache_and_always_has_local_and_custom(tmp_path, fake_fetch):
    with TestClient(make_app(tmp_path)) as client:
        signed_in(client)
        for session in client.app.state.db.session():  # type: ignore[attr-defined]
            for row in session.exec(select(ModelsDevCache)).all():
                session.delete(row)
            session.commit()
        models_dev._service._last_fetch = 0  # type: ignore[union-attr]
        kinds = [k["id"] for k in client.get("/api/assistant/kinds").json()]
        assert "acme-ai" in kinds and "anthropic" in kinds and "ollama" in kinds
        assert kinds[-2:] == ["openai-compatible", "anthropic-compatible"]
        assert "closed-ai" not in kinds


def test_anthropic_compatible_and_own_base_url_build_the_right_model(tmp_path, fake_fetch):
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.models.openai import OpenAIChatModel

    from athena.assistant.providers import ProviderConfig, build_model

    kinds = _kinds(tmp_path, fake_fetch)
    models_dev._service = ModelsDevService(_db(tmp_path / "x").session)
    try:
        asyncio.run(models_dev._service.ensure_cache_fresh())
        mm = ProviderConfig(id="p", kind=kinds["mini-max"], name="M", values={"api_key": "k"})
        model = build_model(mm, "m2")
        assert isinstance(model, AnthropicModel)
        assert str(model.base_url).rstrip("/") == "https://api.minimax.example/anthropic"
        acme = ProviderConfig(
            id="a",
            kind=kinds["acme-ai"],
            name="A",
            values={"api_key": "k", "base_url": "https://proxy.example/v1"},
        )
        model = build_model(acme, "acme-1")
        assert isinstance(model, OpenAIChatModel)
        assert str(model.base_url).rstrip("/") == "https://proxy.example/v1"
    finally:
        models_dev._service = None
