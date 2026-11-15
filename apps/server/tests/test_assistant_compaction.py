"""Compaction (`assistant/compaction.py`) and the context window it's measured against
(`assistant/context.py`)."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from conftest import make_app, signed_in
from fastapi.testclient import TestClient
from pydantic_ai.messages import (
    CompactionPart,
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import function
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from test_assistant import add_provider, chat_app, mock_transport, read_events

from athena.api import assistant as assistant_api
from athena.assistant import context
from athena.assistant.context import ContextWindow, window_for
from athena.assistant.kinds import BY_ID
from athena.assistant.providers import ModelCache, ProviderConfig, build_model
from athena.db.models import AiConversation

# ---------------------------------------------------------------- the window


def cfg(kind: str, **values: str) -> ProviderConfig:
    return ProviderConfig(id="p1", kind=BY_ID[kind], name=kind, values={"api_key": "k", **values})


def window(c: ProviderConfig, model_id: str, routes: dict | None = None) -> ContextWindow:
    model = build_model(c, model_id)
    return asyncio.run(window_for(c, model_id, model, ModelCache(), mock_transport(routes or {})))


OLLAMA = {"base_url": "http://127.0.0.1:11434"}


def test_a_typed_window_wins():
    c = cfg("ollama", context_window="32768", **OLLAMA)
    assert window(c, "qwen3:8b") == ContextWindow(32768, "provider-field")


def test_ollama_reports_the_size_it_runs_a_loaded_model_at():
    ps = {"/api/ps": {"models": [{"name": "qwen3:8b", "context_length": 16384}]}}
    assert window(cfg("ollama", **OLLAMA), "qwen3:8b", ps) == ContextWindow(16384, "provider")
    latest = {"/api/ps": {"models": [{"name": "llama3.2:latest", "context_length": 8192}]}}
    assert window(cfg("ollama", **OLLAMA), "llama3.2", latest).tokens == 8192


def test_an_unloaded_ollama_model_gets_ollamas_default():
    empty = {"/api/ps": {"models": []}}
    got = window(cfg("ollama", **OLLAMA), "qwen3:8b", empty)
    assert got == ContextWindow(context.OLLAMA_UNLOADED, "guess")
    # An unreachable Ollama costs only the guess.
    assert window(cfg("ollama", **OLLAMA), "qwen3:8b").tokens == context.OLLAMA_UNLOADED


def test_model_lists_carry_windows():
    groq = {"/openai/v1/models": {"data": [{"id": "llama-x", "context_window": 131072}]}}
    assert window(cfg("groq"), "llama-x", groq) == ContextWindow(131072, "provider")
    vllm = {"/v1/models": {"data": [{"id": "qwen", "max_model_len": 40960}]}}
    local = cfg("openai-compatible", base_url="http://127.0.0.1:8000/v1")
    assert window(local, "qwen", vllm).tokens == 40960


def test_well_known_models_use_their_profile():
    assert window(cfg("anthropic"), "claude-sonnet-4-5") == ContextWindow(200_000, "profile")
    assert window(cfg("openai"), "gpt-4o").tokens == 128_000


def test_unknown_models_get_a_cautious_guess():
    local = cfg("openai-compatible", base_url="http://127.0.0.1:1234/v1")
    assert window(local, "mystery") == ContextWindow(context.UNKNOWN_LOCAL, "guess")
    assert window(cfg("mistral"), "mystery") == ContextWindow(context.UNKNOWN_CLOUD, "guess")


def test_the_window_field_is_checked(tmp_path):
    with TestClient(make_app(tmp_path)) as client:
        signed_in(client)
        bad = client.post(
            "/api/assistant/providers",
            json={"kind": "ollama", "name": "O", "values": {"context_window": "lots"}},
        )
        assert bad.status_code == 422, bad.text
        assert "Context window" in bad.text
        add_provider(client, "ollama", "O", {"context_window": "32768"})


# ---------------------------------------------------------------- compaction in a chat

WINDOW = 8_192
SUMMARY = "SUMMARY: the admin sent long notes about the server."


def is_summary_request(info: AgentInfo) -> bool:
    return not info.function_tools and "summar" in (info.instructions or "").lower()


def summarize(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    assert is_summary_request(info)
    return ModelResponse(parts=[TextPart(SUMMARY)])


def prompts(messages: list[ModelMessage]) -> list[str]:
    return [
        str(p.content)
        for m in messages
        for p in m.parts
        if isinstance(p, UserPromptPart) and isinstance(p.content, str)
    ]


def has_summary(messages: list[ModelMessage]) -> bool:
    return any(isinstance(p, CompactionPart) for m in messages for p in m.parts)


@pytest.fixture(autouse=True)
def unmeasured_streams(monkeypatch):
    """FunctionModel's streams report a flat 50 input tokens, which the harness would
    trust over its own estimate (it anchors on provider usage). Report none instead, so
    the history is measured from its text, like a provider that sends no usage."""
    monkeypatch.setattr(function.FunctionStreamedResponse, "__post_init__", lambda self: None)


def small_window(monkeypatch, tokens: int = WINDOW) -> None:
    async def fixed(*args, **kwargs) -> ContextWindow:
        return ContextWindow(tokens, "provider-field")

    monkeypatch.setattr(assistant_api, "window_for", fixed)


def new_chat(client: TestClient) -> str:
    pid = add_provider(client)["id"]
    conv = client.post(
        "/api/assistant/conversations", json={"model": {"provider_id": pid, "model": "m"}}
    ).json()
    # A titled chat skips the title agent, which would also use the function model.
    client.patch(f"/api/assistant/conversations/{conv['id']}", json={"title": "Notes"})
    return conv["id"]


def send(client: TestClient, conv_id: str, text: str) -> list[tuple[str, dict]]:
    url = f"/api/assistant/conversations/{conv_id}/messages"
    with client.stream("POST", url, json={"text": text}) as res:
        assert res.status_code == 200
        return read_events(res)


def note(n: int) -> str:
    return f"note {n}: " + "the disks are fine. " * 500  # ~10,000 characters


def test_a_long_chat_is_summarized_and_the_admin_still_sees_all_of_it(tmp_path, monkeypatch):
    small_window(monkeypatch)
    seen: list[list[ModelMessage]] = []

    async def reply(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator:
        seen.append(messages)
        yield f"Noted ({len(prompts(messages))} notes in view)."

    app = chat_app(tmp_path, monkeypatch, FunctionModel(summarize, stream_function=reply))
    with TestClient(app) as client:
        signed_in(client)
        conv_id = new_chat(client)
        for n in range(1, 5):
            events = send(client, conv_id, note(n))
            assert not [d for e, d in events if e == "error"], events

        # The first turns fit; later ones went out with a summary instead of the oldest notes.
        assert not has_summary(seen[0])
        assert has_summary(seen[-1])
        assert not any(p.startswith("note 2:") for p in prompts(seen[-1]))
        assert prompts(seen[-1])[-1].startswith("note 4:")

        detail = client.get(f"/api/assistant/conversations/{conv_id}").json()
        users = [m["parts"][0]["text"][:7] for m in detail["messages"] if m["role"] == "user"]
        assert users == ["note 1:", "note 2:", "note 3:", "note 4:"]
        replies = [m for m in detail["messages"] if m["role"] == "assistant"]
        assert len(replies) == 4 and all(SUMMARY not in str(r) for r in replies)

        for db in app.state.db.session():
            row = db.get(AiConversation, conv_id)
            assert row is not None and row.transcript is not None and row.history is not None
            assert len(row.history) < len(row.transcript)


def test_a_short_chat_keeps_no_separate_transcript(tmp_path, monkeypatch):
    small_window(monkeypatch, 200_000)

    async def reply(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator:
        yield "ok"

    app = chat_app(tmp_path, monkeypatch, FunctionModel(summarize, stream_function=reply))
    with TestClient(app) as client:
        signed_in(client)
        conv_id = new_chat(client)
        send(client, conv_id, note(1))
        send(client, conv_id, note(2))
        for db in app.state.db.session():
            row = db.get(AiConversation, conv_id)
            assert row is not None and row.transcript is None


def test_results_cleared_mid_turn_stay_whole_in_the_transcript(tmp_path, monkeypatch):
    """A long tool loop: old results are blanked for the model within the same turn, and
    the admin still sees every one."""
    small_window(monkeypatch, 4_000)  # each result is ~230 tokens; tool schemas count too
    calls = 10
    cleared_seen = []

    async def reply(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator:
        returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
        cleared_seen.append(sum(p.content == "[tool result cleared]" for p in returns))
        if len(returns) < calls:
            yield {
                0: DeltaToolCall(
                    name="get_capabilities", json_args="{}", tool_call_id=f"c{len(returns)}"
                )
            }
        else:
            yield "All checked."

    app = chat_app(tmp_path, monkeypatch, FunctionModel(summarize, stream_function=reply))
    with TestClient(app) as client:
        signed_in(client)
        conv_id = new_chat(client)
        events = send(client, conv_id, "Check the capabilities over and over")
        assert not [d for e, d in events if e == "error"], events
        assert max(cleared_seen) > 0  # compaction really ran within the turn

        detail = client.get(f"/api/assistant/conversations/{conv_id}").json()
        tools = [p for m in detail["messages"] for p in m["parts"] if p["type"] == "tool"]
        assert len(tools) == calls
        assert all(t["state"] == "done" and '"os": "darwin"' in t["result"] for t in tools)
        texts = [p["text"] for m in detail["messages"] for p in m["parts"] if p["type"] == "text"]
        assert texts[-1] == "All checked."


@pytest.mark.parametrize("failure", ["error", "empty"])
def test_a_failed_summary_drops_the_oldest_messages_instead(tmp_path, monkeypatch, failure):
    small_window(monkeypatch)
    seen: list[list[ModelMessage]] = []

    def broken(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if failure == "error":
            from pydantic_ai.exceptions import ModelHTTPError

            raise ModelHTTPError(500, "m", "summarizer down")
        return ModelResponse(parts=[TextPart("")])

    async def reply(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator:
        seen.append(messages)
        yield "ok"

    app = chat_app(tmp_path, monkeypatch, FunctionModel(broken, stream_function=reply))
    with TestClient(app) as client:
        signed_in(client)
        conv_id = new_chat(client)
        for n in range(1, 5):
            events = send(client, conv_id, note(n))
            assert not [d for e, d in events if e == "error"], events
        assert not has_summary(seen[-1])
        assert len(prompts(seen[-1])) < 4  # older notes were dropped
        detail = client.get(f"/api/assistant/conversations/{conv_id}").json()
        assert len([m for m in detail["messages"] if m["role"] == "user"]) == 4


def test_a_compacted_chat_still_pauses_for_approval_and_resumes(tmp_path, monkeypatch):
    """Long notes force compaction; then an action waits for approval, is approved, and
    the transcript shows one card that ends done, after every note."""
    small_window(monkeypatch)
    seen: list[list[ModelMessage]] = []
    share = tmp_path / "share"
    share.mkdir()

    async def reply(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator:
        seen.append(messages)
        last = messages[-1]
        if any(isinstance(p, ToolReturnPart) for p in last.parts):
            yield "Made it."
        elif prompts([last]) and prompts([last])[-1].startswith("make"):
            args = f'{{"location_id": {loc}, "path": "", "name": "photos"}}'
            yield {0: DeltaToolCall(name="create_folder", json_args=args, tool_call_id="f1")}
        else:
            yield "Noted."

    app = chat_app(tmp_path, monkeypatch, FunctionModel(summarize, stream_function=reply))
    with TestClient(app) as client:
        signed_in(client)
        conv_id = new_chat(client)
        loc = client.post("/api/files/locations", json={"name": "S", "path": str(share)}).json()[
            "id"
        ]
        for n in range(1, 5):
            send(client, conv_id, note(n))
        assert has_summary(seen[-1])

        events = send(client, conv_id, "make a photos folder")
        assert any(e == "approval" for e, _ in events)
        url = f"/api/assistant/conversations/{conv_id}/approvals"
        with client.stream("POST", url, json={"decisions": [{"id": "f1", "approve": True}]}) as r:
            events = read_events(r)
        assert not [d for e, d in events if e == "error"], events
        assert (share / "photos").is_dir()

        detail = client.get(f"/api/assistant/conversations/{conv_id}").json()
        users = [m["parts"][0]["text"][:7] for m in detail["messages"] if m["role"] == "user"]
        assert users == ["note 1:", "note 2:", "note 3:", "note 4:", "make a "]
        tools = [p for m in detail["messages"] for p in m["parts"] if p["type"] == "tool"]
        assert [(t["tool_call_id"], t["state"]) for t in tools] == [("f1", "done")]
        texts = [p["text"] for m in detail["messages"] for p in m["parts"] if p["type"] == "text"]
        assert texts[-1] == "Made it." and texts.count("Made it.") == 1
