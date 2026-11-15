"""The always-on harness capabilities (`assistant/robustness.py`), through the chat API."""

import warnings
from collections.abc import AsyncIterator

from conftest import signed_in
from fastapi.testclient import TestClient
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.usage import RequestUsage
from test_assistant import add_provider, chat_app, read_events

from athena.assistant import chat, robustness


def run_turn(client: TestClient, text: str = "Check the server") -> list[tuple[str, dict]]:
    pid = add_provider(client)["id"]
    conv = client.post(
        "/api/assistant/conversations",
        json={"model": {"provider_id": pid, "model": "m"}},
    ).json()
    url = f"/api/assistant/conversations/{conv['id']}/messages"
    with client.stream("POST", url, json={"text": text}) as res:
        assert res.status_code == 200
        return read_events(res)


def tool_returns(messages: list[ModelMessage]) -> list[ToolReturnPart]:
    return [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]


def test_malformed_tool_arguments_are_repaired(tmp_path, monkeypatch):
    """A small model's broken JSON ("{") runs the tool instead of costing a retry."""

    async def reply(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator:
        if not tool_returns(messages):
            yield {0: DeltaToolCall(name="get_capabilities", json_args="{", tool_call_id="c1")}
        else:
            yield "done"

    with TestClient(chat_app(tmp_path, monkeypatch, FunctionModel(stream_function=reply))) as c:
        signed_in(c)
        events = run_turn(c)
    results = [d for e, d in events if e == "tool-result"]
    assert len(results) == 1 and results[0]["error"] is None
    assert '"os": "darwin"' in results[0]["result"]


def test_a_repeated_call_gets_a_nudge(tmp_path, monkeypatch):
    """The same call with the same result three times: the next request tells the model."""
    seen_nudge = []

    async def reply(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator:
        # FunctionModel has no inline system prompts, so the nudge arrives as <system> text.
        nudges = [
            p.content
            for m in messages
            for p in m.parts
            if isinstance(p, SystemPromptPart | UserPromptPart)
            and "Change your approach" in str(p.content)
        ]
        if nudges:
            seen_nudge.append(nudges[0])
            yield "I keep getting the same answer, so I'll stop."
        else:
            n = len(tool_returns(messages))
            yield {0: DeltaToolCall(name="get_capabilities", json_args="{}", tool_call_id=f"c{n}")}

    with TestClient(chat_app(tmp_path, monkeypatch, FunctionModel(stream_function=reply))) as c:
        signed_in(c)
        events = run_turn(c)
    assert seen_nudge and "get_capabilities" in seen_nudge[0]
    assert len([e for e, _ in events if e == "tool-call"]) == 3
    assert events[-1][0] == "done" and not [d for e, d in events if e == "error"]


def test_a_big_tool_result_is_spilled_and_can_be_read_back(tmp_path, monkeypatch):
    monkeypatch.setattr(robustness, "SPILL_OVER", 300)
    read_back = []

    async def reply(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator:
        assert "read_tool_result" in {t.name for t in info.function_tools}
        returns = tool_returns(messages)
        if not returns:
            yield {0: DeltaToolCall(name="get_capabilities", json_args="{}", tool_call_id="c1")}
        elif len(returns) == 1:
            handle = (returns[0].metadata or {})["overflow_handle"]
            args = f'{{"handle": "{handle}", "pattern": "darwin"}}'
            yield {0: DeltaToolCall(name="read_tool_result", json_args=args, tool_call_id="c2")}
        else:
            read_back.append(returns[1].model_response_str())
            yield "done"

    with TestClient(chat_app(tmp_path, monkeypatch, FunctionModel(stream_function=reply))) as c:
        signed_in(c)
        events = run_turn(c)
    first = next(d for e, d in events if e == "tool-result")
    assert '"os": "darwin"' not in first["result"]  # a preview and a handle instead
    spilled = list(robustness.spill_dir(tmp_path / "data").rglob("*"))
    assert any(p.is_file() and b'"darwin"' in p.read_bytes() for p in spilled)
    assert read_back and "darwin" in read_back[0]


def system_notes(messages: list[ModelMessage], text: str) -> list[str]:
    """Notes containing `text`: FunctionModel shows system prompts as parts of the request."""
    return [
        str(p.content)
        for m in messages
        for p in m.parts
        if isinstance(p, SystemPromptPart | UserPromptPart) and text in str(p.content)
    ]


def test_a_long_reply_gets_a_stay_on_task_note(tmp_path, monkeypatch):
    monkeypatch.setattr(robustness, "REMIND_EVERY", 3)
    noted_at = []

    async def reply(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator:
        n = len(tool_returns(messages))
        # Request-scoped: the note is in the request it fires on only.
        if system_notes(messages[-1:], "admin's latest message"):
            noted_at.append(n + 1)
        if n < 6:
            # Repeats get a loop nudge too; that doesn't matter here.
            yield {0: DeltaToolCall(name="get_capabilities", json_args="{}", tool_call_id=f"c{n}")}
        else:
            yield "done"

    with TestClient(chat_app(tmp_path, monkeypatch, FunctionModel(stream_function=reply))) as c:
        signed_in(c)
        events = run_turn(c)
    assert noted_at == [3, 6]
    assert events[-1][0] == "done"


def test_the_model_is_told_when_the_turn_limit_is_close(tmp_path, monkeypatch):
    """With 5 requests a turn, the model hears it's nearly out and answers instead of
    being stopped (a stopped turn is dropped)."""
    monkeypatch.setattr(chat, "TURN_REQUESTS", 5)
    warned = []

    async def reply(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator:
        notes = system_notes(messages[-1:], "left in this reply")
        if notes:
            warned.append(notes[0])
            yield "Here's what I found so far."
        else:
            n = len(tool_returns(messages))
            yield {0: DeltaToolCall(name="get_capabilities", json_args="{}", tool_call_id=f"c{n}")}

    with TestClient(chat_app(tmp_path, monkeypatch, FunctionModel(stream_function=reply))) as c:
        signed_in(c)
        events = run_turn(c)
    assert warned and "Only 3 model requests left" in warned[0]
    assert events[-1][0] == "done" and not [d for e, d in events if e == "error"]


def test_a_cache_bust_is_logged_not_warned(caplog):
    """The second request reads back nothing of the 10,000 tokens the first one cached."""
    usages = [
        RequestUsage(input_tokens=10_100, cache_write_tokens=10_000),
        RequestUsage(input_tokens=10_200, cache_write_tokens=10_000),
    ]

    def reply(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("ok")], usage=usages.pop(0))

    agent = Agent(FunctionModel(reply), capabilities=[robustness.CACHE_BUSTS])

    with warnings.catch_warnings():
        warnings.simplefilter("error")  # a warning that escapes fails the test
        first = agent.run_sync("hi")
        caplog.set_level("WARNING", logger=robustness.__name__)
        agent.run_sync("again", message_history=first.all_messages())
    assert "prompt cache missed 10000 of 10000 cached tokens" in caplog.text
