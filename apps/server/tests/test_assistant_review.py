"""Double-checked answers and workflows of helpers (`review.py`, `delegation.workflow_capabilities`,
M7 part D stage 2)."""

import json
from collections.abc import AsyncIterator

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from test_assistant_actions import audit_rows, detail, send, setup, use
from test_assistant_compaction import small_window

from athena.assistant.delegation import WORKFLOW_MIN_WINDOW, WORKFLOW_TOOL
from athena.assistant.review import REVIEW_INSTRUCTIONS

# ---------------------------------------------------------------- double-check answers


def reviewer(seen: dict) -> FunctionModel:
    """Answers "Draft answer.", then "Final answer." when asked to review."""

    async def reply(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        seen["requests"] = seen.get("requests", 0) + 1
        # FunctionModel gets the review's system prompt merged into the last request's text.
        yield "Final answer." if REVIEW_INSTRUCTIONS in str(messages[-1]) else "Draft answer."

    return FunctionModel(stream_function=reply)


def texts(client, conv) -> list[tuple[str, bool]]:
    [_, reply] = detail(client, conv)["messages"]
    return [(p["text"], p["draft"]) for p in reply["parts"] if p["type"] == "text"]


def test_answers_are_not_reviewed_by_default(tmp_path, monkeypatch):
    seen: dict = {}
    client, conv, _, _ = setup(tmp_path)
    use(monkeypatch, reviewer(seen))
    events = send(client, conv, "How much disk is left?")
    assert "draft" not in [e for e, _ in events]
    assert seen["requests"] == 1
    assert texts(client, conv) == [("Draft answer.", False)]


def test_a_reviewed_answer_folds_the_draft(tmp_path, monkeypatch):
    seen: dict = {}
    client, conv, _, _ = setup(tmp_path)
    use(monkeypatch, reviewer(seen))
    assert client.put("/api/settings/ai", json={"refine_answers": True}).status_code == 200
    events = send(client, conv, "How much disk is left?")
    names = [e for e, _ in events]
    assert names.count("draft") == 1
    assert names.index("draft") < names.index("done")
    assert seen["requests"] == 2  # one review round per turn
    assert texts(client, conv) == [("Draft answer.", True), ("Final answer.", False)]


def test_the_review_setting_is_audited(tmp_path):
    client, _, _, _ = setup(tmp_path)
    for value in (True, True, False):
        client.put("/api/settings/ai", json={"refine_answers": value}).raise_for_status()
    rows = [t for a, t in audit_rows(client) if a == "settings.assistant_refine"]
    assert rows == ["on", "off"]


# ---------------------------------------------------------------- workflows


SCRIPT = """\
import asyncio
found = await asyncio.gather(
    investigator(task="check the disk"),
    investigator(task="check the memory"),
)
" | ".join(found)
"""


def workflow_models(seen: dict) -> FunctionModel:
    """The chat runs SCRIPT once; each investigator answers with its task."""

    async def chat(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator:
        seen["chat_tools"] = {t.name for t in info.function_tools}
        returns = [p for p in messages[-1].parts if isinstance(p, ToolReturnPart)]
        if returns:
            seen["result"] = returns[0].content
            yield "Done."
        elif WORKFLOW_TOOL in seen["chat_tools"]:
            args = json.dumps({"code": SCRIPT})
            yield {0: DeltaToolCall(name=WORKFLOW_TOOL, json_args=args, tool_call_id="w1")}
        else:
            yield "No workflow."

    def helper(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if "You help Athena's assistant" not in (info.instructions or ""):
            return ModelResponse(parts=[TextPart("A title")])  # the chat's title
        task = str(messages[0].parts[-1].content)
        seen.setdefault("tasks", []).append(task)
        seen["helper_tools"] = {t.name for t in info.function_tools}
        return ModelResponse(parts=[TextPart(f"ok: {task}")])

    return FunctionModel(helper, stream_function=chat)


def test_a_workflow_runs_investigators_together(tmp_path, monkeypatch):
    seen: dict = {}
    client, conv, _, _ = setup(tmp_path)
    use(monkeypatch, workflow_models(seen))
    small_window(monkeypatch, WORKFLOW_MIN_WINDOW)
    events = send(client, conv, "Check the server")
    assert events[-1][0] == "done"
    assert sorted(seen["tasks"]) == ["check the disk", "check the memory"]
    assert seen["result"] == "ok: check the disk | ok: check the memory"
    # Helpers only read: no actions, no shell, no workflows of their own.
    assert "create_folder" not in seen["helper_tools"]
    assert WORKFLOW_TOOL not in seen["helper_tools"]
    # The helpers' usage is the chat's (shared counter), so the spend limit counts it: the
    # chat's two streamed requests report 50 input tokens each, the helpers add theirs.
    assert detail(client, conv)["usage"]["input_tokens"] > 100


def test_small_contexts_get_no_workflow_tool(tmp_path, monkeypatch):
    seen: dict = {}
    client, conv, _, _ = setup(tmp_path)
    use(monkeypatch, workflow_models(seen))
    small_window(monkeypatch, WORKFLOW_MIN_WINDOW - 1)
    send(client, conv, "Check the server")
    assert WORKFLOW_TOOL not in seen["chat_tools"]
    assert "tasks" not in seen
