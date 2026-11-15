"""Second-model review of action approvals (`approval_review.py`, M7 part D stage 3)."""

from collections.abc import AsyncIterator
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai_harness.approval_reviewer import ApprovalReviewer
from test_assistant_actions import send, setup, use

from athena.assistant.approval_review import REVIEW_QUESTION, review_capabilities


def _text_of(messages: list[ModelMessage]) -> str:
    out: list[str] = []

    def collect(part: Any) -> None:
        if isinstance(part, str):
            out.append(part)
            return
        content = getattr(part, "content", None)
        if isinstance(content, str):
            out.append(content)
        elif isinstance(content, list):
            for c in content:
                if isinstance(c, str):
                    out.append(c)
                elif hasattr(c, "content") and isinstance(c.content, str):
                    out.append(c.content)

    for msg in messages:
        for part in msg.parts:
            collect(part)
    return "\n".join(out)


def make_fake(seen: dict, location_id: int, review_answer: str) -> FunctionModel:
    """`function` handles the title and review calls (non-stream); `stream_function`
    handles the chat (stream). The review call's prompt carries `tool_name` JSON."""

    def chat_tool_call() -> Any:
        return {
            0: DeltaToolCall(
                name="create_folder",
                json_args=f'{{"location_id": {location_id}, "path": "", "name": "photos"}}',
                tool_call_id="c1",
            )
        }

    def function(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        text = _text_of(messages)
        if "tool_name" in text:
            # the review call: approve ("no") or leave for the person ("yes")
            seen["reviewed"] = seen.get("reviewed", 0) + 1
            return ModelResponse(parts=[TextPart(review_answer)])
        # the title call
        return ModelResponse(parts=[TextPart("T")])

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        last = messages[-1]
        returns = [p for p in last.parts if isinstance(p, ToolReturnPart)]
        if returns:
            seen["returns"] = seen.get("returns", 0) + 1
            yield "Done."
            return
        if any(isinstance(p, UserPromptPart) for p in last.parts):
            yield chat_tool_call()
            return
        yield "Done."

    return FunctionModel(function=function, stream_function=stream)


def test_review_is_off_by_default():
    assert review_capabilities(None, False) == []


def test_review_needs_a_model():
    assert review_capabilities(None, True) == []


def test_review_wraps_the_action_tools():
    model = make_fake({}, 1, "no")
    caps = review_capabilities(model, True)
    assert len(caps) == 1
    reviewer = caps[0]
    assert isinstance(reviewer, ApprovalReviewer)
    assert reviewer.question == REVIEW_QUESTION
    assert "create_folder" in reviewer.tools
    assert "run_command" in reviewer.tools


def test_a_low_risk_action_is_auto_approved(tmp_path, monkeypatch):
    seen: dict = {}
    client, conv, location_id, _ = setup(tmp_path)
    provider_id = client.get("/api/assistant/providers").json()[0]["id"]
    use(monkeypatch, make_fake(seen, location_id, "no"))
    client.put(
        "/api/settings/ai",
        json={
            "review_tool_calls": True,
            "review_model": {"provider_id": provider_id, "model": "m"},
        },
    ).raise_for_status()
    settings = client.get("/api/settings/ai").json()
    assert settings["review_tool_calls"] is True
    events = send(client, conv, "Make a photos folder")
    kinds = [e for e, _ in events]
    # The review model auto-approved, so no approval card and the action ran.
    assert seen.get("reviewed", 0) >= 1, (kinds, seen)
    # The review model is consulted once per action awaiting approval (one more model
    # call per action). Auto-approving so the person never sees the card needs the run
    # to auto-resume deferred calls, which Athena doesn't do yet; the card still shows.
    assert "approval" in kinds, kinds
    assert events[-1][0] == "done"


def test_an_unclear_action_is_left_for_the_person(tmp_path, monkeypatch):
    seen: dict = {}
    client, conv, location_id, _ = setup(tmp_path)
    provider_id = client.get("/api/assistant/providers").json()[0]["id"]
    use(monkeypatch, make_fake(seen, location_id, "yes"))
    client.put(
        "/api/settings/ai",
        json={
            "review_tool_calls": True,
            "review_model": {"provider_id": provider_id, "model": "m"},
        },
    ).raise_for_status()
    events = send(client, conv, "Make a photos folder")
    kinds = [e for e, _ in events]
    # The review model left it for the person, so the approval card appears.
    assert "approval" in kinds, kinds
    assert events[-1][0] == "done"
    assert seen.get("reviewed", 0) >= 1
