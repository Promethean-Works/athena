"""The advisor: a second model the chat's model may consult (`delegation.advisor_capabilities`,
M7 part D stage 2)."""

import json
from collections.abc import AsyncIterator

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from test_assistant_actions import audit_rows, send, setup

from athena.api import assistant as assistant_api

QUESTION = "Is restic or borg better for a 2 TB photo backup?"
PRIVATE = "my-private-chat-detail"


def models(seen: dict) -> dict[str, FunctionModel]:
    """Model "m" asks the advisor twice in one request; "adv" answers and records it."""

    async def chat(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator:
        seen["chat_tools"] = {t.name for t in info.function_tools}
        returns = [p for p in messages[-1].parts if isinstance(p, ToolReturnPart)]
        if returns:
            seen["results"] = [str(p.content) for p in returns]
            yield "Done."
        elif "advisor" in seen["chat_tools"]:
            for i in range(2):
                args = json.dumps({"prompt": QUESTION})
                yield {i: DeltaToolCall(name="advisor", json_args=args, tool_call_id=f"a{i}")}
        else:
            yield "No advisor."

    def advisor(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.setdefault("advisor_saw", []).append(messages)
        seen["advisor_tools"] = {t.name for t in info.function_tools}
        return ModelResponse(parts=[TextPart("Use restic.")])

    async def no_stream(messages, info) -> AsyncIterator[str]:
        raise AssertionError("the advisor doesn't stream")
        yield ""

    def no_plain(messages, info) -> ModelResponse:
        raise AssertionError("the chat streams")

    return {
        "m": FunctionModel(no_plain, stream_function=chat),
        "adv": FunctionModel(advisor, stream_function=no_stream),
    }


def with_models(monkeypatch, seen: dict) -> None:
    by_id = models(seen)
    monkeypatch.setattr(assistant_api, "build_model", lambda cfg, model_id: by_id[model_id])


def provider_of(client) -> str:
    return client.get("/api/assistant/providers").json()[0]["id"]


def test_no_advisor_tool_until_one_is_set(tmp_path, monkeypatch):
    seen: dict = {}
    client, conv, _, _ = setup(tmp_path)
    with_models(monkeypatch, seen)
    send(client, conv, "Hello")
    assert "advisor" not in seen["chat_tools"]


def test_the_advisor_sees_only_the_question_once_per_request(tmp_path, monkeypatch):
    seen: dict = {}
    client, conv, _, _ = setup(tmp_path)
    with_models(monkeypatch, seen)
    ref = {"provider_id": provider_of(client), "model": "adv"}
    assert client.put("/api/settings/ai", json={"advisor_model": ref}).status_code == 200
    events = send(client, conv, f"{PRIVATE}: which backup tool?")
    assert events[-1][0] == "done"
    assert "advisor" in seen["chat_tools"]
    # Two calls in one request: one is answered, the other told the limit is reached.
    [saw] = seen["advisor_saw"]
    assert QUESTION in str(saw) and PRIVATE not in str(saw)
    assert not seen["advisor_tools"]
    assert sorted(seen["results"]) == [
        "Advisor consultation limit reached for this model request. "
        "Continue without further advice.",
        "Use restic.",
    ]


def test_the_advisor_setting_is_audited_and_cleared_with_its_provider(tmp_path, monkeypatch):
    client, _, _, _ = setup(tmp_path)
    pid = provider_of(client)
    ref = {"provider_id": pid, "model": "adv"}
    assert client.put("/api/settings/ai", json={"advisor_model": ref}).status_code == 200
    assert client.put("/api/settings/ai", json={"advisor_model": ref}).status_code == 200
    assert client.put("/api/settings/ai", json={"advisor_model": None}).status_code == 200
    rows = [r for r in audit_rows(client) if r[0] == "settings.assistant_advisor"]
    assert [target for _, target in rows] == [f"{pid}/adv", "off"]
    bad = {"advisor_model": {"provider_id": "0" * 16, "model": "x"}}
    assert client.put("/api/settings/ai", json=bad).status_code == 422

    client.put("/api/settings/ai", json={"advisor_model": ref}).raise_for_status()
    assert client.delete(f"/api/assistant/providers/{pid}").status_code == 204
    assert client.get("/api/settings/ai").json()["advisor_model"] is None
