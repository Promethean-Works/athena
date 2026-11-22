"""Delegation to the read-only investigator and background delegations
(`assistant/delegation.py`, M7 part D stage 2)."""

import json
from collections.abc import AsyncIterator

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextContent,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from test_assistant_actions import audit_rows, detail, send, setup, use
from test_assistant_safety import GITHUB_TOKEN, INJECTION

from athena.assistant.delegation import INVESTIGATOR_INSTRUCTIONS


def completion_text(part: object) -> str | None:
    """The result of a background call as the model sees it: a `<tool_result>` frame on the
    user channel (the harness's `BackgroundToolResultPart`, rendered), else None."""
    content = getattr(part, "content", None)
    if not isinstance(part, UserPromptPart) or isinstance(content, str) or not content:
        return None
    texts = [c.content for c in content if isinstance(c, TextContent)]
    if not texts or not texts[0].startswith("<tool_result "):
        return None
    return "\n".join(texts[1:-1])


def is_child(info: AgentInfo) -> bool:
    return INVESTIGATOR_INSTRUCTIONS[:40] in (info.instructions or "")


def delegating(loc: int, path: str, seen: dict, *, background: bool = False) -> FunctionModel:
    """The chat delegates reading `path` once; the investigator reads it and echoes it back.
    `seen` collects what each side was told and which tools each side had."""

    def child(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.setdefault("child_tools", {t.name for t in info.function_tools})
        returns = [p for p in messages[-1].parts if isinstance(p, ToolReturnPart)]
        if returns:
            seen.setdefault("child", []).extend(str(p.content) for p in returns)
            return ModelResponse(parts=[TextPart(f"Found: {returns[0].content}")])
        args = {"location_id": loc, "path": path}
        return ModelResponse(parts=[ToolCallPart("read_text_file", args, tool_call_id="r1")])

    async def reply(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator:
        last = messages[-1]
        returns = [p for p in last.parts if p.part_kind in ("tool-return", "retry-prompt")]
        seen.setdefault("parent_tools", {t.name for t in info.function_tools})
        completions = [text for p in last.parts if (text := completion_text(p)) is not None]
        for p in returns:
            seen.setdefault("parent", []).append(str(p.content))
        for text in completions:
            seen.setdefault("parent", []).append(text)
        prompted = any(
            isinstance(p, UserPromptPart)
            and isinstance(p.content, str)
            and not p.content.startswith("<system>")
            for p in last.parts
        )
        if prompted and not returns:
            args = {"agent_name": "investigator", "task": f"Read {path} in location {loc}"}
            if background:
                args["run_in_background"] = True
            json_args = json.dumps(args)
            call = DeltaToolCall(name="delegate_task", json_args=json_args, tool_call_id="d1")
            yield {0: call}
        elif completions or not background:
            yield "Done."
        else:
            yield "Started; waiting."

    def plain(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert is_child(info), "only the investigator runs without streaming"
        return child(messages, info)

    return FunctionModel(plain, stream_function=reply)


def tools_of(client, conv):
    return [p for m in detail(client, conv)["messages"] for p in m["parts"] if p["type"] == "tool"]


def test_the_investigator_reads_and_reports_back(tmp_path, monkeypatch):
    seen: dict = {}
    client, conv, loc, share = setup(tmp_path)
    (share / "notes.txt").write_bytes(b"Restart the media server on Sundays.\n")
    use(monkeypatch, delegating(loc, "notes.txt", seen))
    events = send(client, conv, "What's in notes.txt?")
    assert events[-1][0] == "done"
    assert "Restart the media server" in seen["child"][0]
    assert "Found:" in seen["parent"][0] and "Restart the media server" in seen["parent"][0]
    # The chat has delegate_task and actions; the helper only reads.
    assert "delegate_task" in seen["parent_tools"] and "write_text_file" in seen["parent_tools"]
    child = seen["child_tools"]
    assert "read_text_file" in child
    assert not child & {"delegate_task", "write_text_file", "delete_files", "ask_user_question"}
    assert not child & {"write_plan", "write_memory", "run_command"}
    [row] = tools_of(client, conv)
    assert row["tool_name"] == "delegate_task" and row["state"] == "done"
    assert "Restart the media server" in row["result"]


def test_the_investigator_screens_its_tool_results(tmp_path, monkeypatch):
    seen: dict = {}
    client, conv, loc, share = setup(tmp_path)
    (share / ".env").write_bytes(f"GITHUB_TOKEN={GITHUB_TOKEN}\n".encode())
    (share / "notes.txt").write_bytes(f"Shopping list\n{INJECTION}\n".encode())
    use(monkeypatch, delegating(loc, ".env", seen))
    send(client, conv, "What's in .env?")
    assert GITHUB_TOKEN not in seen["child"][0] and "[redacted:github_token]" in seen["child"][0]
    assert GITHUB_TOKEN not in seen["parent"][0]

    seen.clear()
    use(monkeypatch, delegating(loc, "notes.txt", seen))
    send(client, conv, "And notes.txt?")
    assert "withheld" in seen["child"][0] and INJECTION not in seen["parent"][0]
    assert ("assistant.injection", "read_text_file") in audit_rows(client)


def test_a_background_delegation_reports_its_real_result(tmp_path, monkeypatch):
    seen: dict = {}
    client, conv, loc, share = setup(tmp_path)
    (share / ".env").write_bytes(f"GITHUB_TOKEN={GITHUB_TOKEN}\nPORT=8080\n".encode())
    use(monkeypatch, delegating(loc, ".env", seen, background=True))
    events = send(client, conv, "What's in .env? Look it up in the background.")
    assert events[-1][0] == "done"
    # The chat's model got the "started" notice, then the real result as a follow-up.
    assert "running in background" in seen["parent"][0]
    assert "PORT=8080" in seen["parent"][1] and GITHUB_TOKEN not in seen["parent"][1]
    # The stream skips the notice and sends the real (screened) result once.
    results = [d for e, d in events if e == "tool-result" and d["id"] == "d1"]
    assert len(results) == 1 and "PORT=8080" in results[0]["result"]
    assert GITHUB_TOKEN not in results[0]["result"]
    # In the saved chat it's the delegate row's result, not a message from the admin.
    [row] = tools_of(client, conv)
    assert row["state"] == "done" and "PORT=8080" in row["result"]
    users = [m for m in detail(client, conv)["messages"] if m["role"] == "user"]
    assert len(users) == 1
    texts = [p["text"] for m in detail(client, conv)["messages"] for p in m["parts"]]
    assert texts[-1] == "Done."


def test_a_background_call_that_never_finished_shows_as_stopped():
    """A pause for an approval cancels background calls; the saved chat says so."""
    from pydantic_ai.messages import ModelRequest

    from athena.assistant.chat import STOPPED_IN_BACKGROUND, ui_messages

    notice = "Tool 'delegate_task' is running in background (task d1). This call is pending."
    messages = [
        ModelRequest(parts=[UserPromptPart("Check the logs")]),
        ModelResponse(parts=[ToolCallPart("delegate_task", {"task": "x"}, tool_call_id="d1")]),
        ModelRequest(parts=[ToolReturnPart("delegate_task", notice, tool_call_id="d1")]),
        ModelResponse(parts=[TextPart("Waiting.")]),
    ]
    [_, reply] = ui_messages(messages)
    row = reply.parts[0]
    assert row.state == "error" and row.error == STOPPED_IN_BACKGROUND and row.result is None
