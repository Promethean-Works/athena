"""Step persistence, conversation search and media externalization (part D stage 2).

- `StepPersistence` saves each turn's full history to `<data-dir>/assistant/steps.db`.
- `ConversationSearch` (scope `conversation`) gives the model `search_conversation_history`,
  a BM25 tool that recalls details from earlier turns and past runs in this chat.
- `media`: large payloads are externalized into the `media` table of the same database.
"""

import json
import sqlite3
from collections.abc import AsyncIterator

from conftest import make_app, signed_in
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from test_assistant import add_provider, read_events

from athena.assistant.persistence import steps_db


def searcher(past_detail: str) -> FunctionModel:
    """On a follow-up prompt asking about the past, calls search_conversation_history
    with the detail to recall, then answers with what it found."""

    async def reply(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator:
        last = messages[-1]
        returns = [p for p in last.parts if getattr(p, "part_kind", "") == "tool-return"]
        if returns:
            yield f"Found: {returns[0].content}"
            return
        if any(getattr(p, "part_kind", "") == "user-prompt" for p in last.parts) and not returns:
            yield {
                0: DeltaToolCall(
                    name="search_conversation_history",
                    json_args=json.dumps({"query": past_detail}),
                    tool_call_id="s1",
                )
            }
        else:
            yield "Not sure."

    return FunctionModel(stream_function=reply)


def new_chat(client: TestClient) -> str:
    pid = add_provider(client)["id"]
    conv = client.post(
        "/api/assistant/conversations", json={"model": {"provider_id": pid, "model": "m"}}
    ).json()
    client.patch(f"/api/assistant/conversations/{conv['id']}", json={"title": "Notes"})
    return conv["id"]


def send(client: TestClient, conv_id: str, text: str) -> list[tuple[str, dict]]:
    url = f"/api/assistant/conversations/{conv_id}/messages"
    with client.stream("POST", url, json={"text": text}) as res:
        assert res.status_code == 200, res.read()
        return read_events(res)


def steps_rows(app) -> list[dict]:
    db_path = steps_db(app.state.settings.data_dir)
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(r)
            for r in conn.execute("SELECT run_id, conversation_id, kind FROM events ORDER BY seq")
        ]


def media_count(app) -> int:
    db_path = steps_db(app.state.settings.data_dir)
    if not db_path.exists():
        return 0
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM media").fetchone()
        return row[0] if row else 0


# ---------------------------------------------------------------- persistence


async def ok_only(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator:
    yield "ok"


def test_steps_db_is_created_and_persists_runs(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    monkeypatch.setattr(
        "athena.api.assistant.build_model",
        lambda cfg, model_id: FunctionModel(stream_function=ok_only),
    )
    with TestClient(app) as client:
        signed_in(client)
        conv_id = new_chat(client)
        send(client, conv_id, "The server has two disks, sda and sdb.")
        send(client, conv_id, "Thanks.")

    rows = steps_rows(app)
    assert any(r["kind"] == "run_started" for r in rows), rows
    assert any(r["kind"] == "run_completed" for r in rows), rows
    # Runs of one conversation share a conversation_id.
    ids = {r["conversation_id"] for r in rows if r["conversation_id"]}
    assert len(ids) == 1, rows


def test_search_conversation_history_recalls_a_past_detail(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    monkeypatch.setattr(
        "athena.api.assistant.build_model",
        lambda cfg, model_id: searcher("disks"),
    )
    with TestClient(app) as client:
        signed_in(client)
        conv_id = new_chat(client)
        send(client, conv_id, "The server has two disks, sda and sdb.")
        events = send(client, conv_id, "What disks did I mention earlier?")
        assert any(
            e == "tool-call" and d["name"] == "search_conversation_history" for e, d in events
        ), events
        result = next(d for e, d in events if e == "tool-result")
        assert "disks" in result["result"], result
        texts = [d["delta"] for e, d in events if e == "text"]
        assert "".join(texts).startswith("Found:"), texts


def test_steps_db_has_core_tables(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    monkeypatch.setattr(
        "athena.api.assistant.build_model",
        lambda cfg, model_id: FunctionModel(stream_function=ok_only),
    )
    with TestClient(app) as client:
        signed_in(client)
        conv_id = new_chat(client)
        send(client, conv_id, "Hello.")

    db_path = steps_db(app.state.settings.data_dir)
    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    # Core step-persistence tables are created on the first turn.
    for table in ("runs", "events", "snapshots", "tool_effects"):
        assert table in tables, tables


def test_large_text_is_externalized_to_media(tmp_path, monkeypatch):
    """A reply bigger than the 64 KiB media threshold is stored in the media
    table and replaced by a URI in the snapshots."""
    big = "x" * 100_000

    async def reply(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator:
        yield big

    app = make_app(tmp_path)
    monkeypatch.setattr(
        "athena.api.assistant.build_model",
        lambda cfg, model_id: FunctionModel(stream_function=reply),
    )
    with TestClient(app) as client:
        signed_in(client)
        conv_id = new_chat(client)
        send(client, conv_id, "Say something long.")

    assert media_count(app) > 0, "expected a large payload to be externalized to media"
