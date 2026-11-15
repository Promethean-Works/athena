"""The assistant's questions (`ask_user_question`) and its plan per chat (M7 part D stage 2)."""

import asyncio
import json
from collections.abc import AsyncIterator

from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from test_assistant import read_events
from test_assistant_actions import answer, audit_rows, detail, folder_call, send, setup, use

from athena.assistant.plans import plan_store

QUESTION = {
    "questions": [
        {
            "header": "Server",
            "question": "Which media server should I install?",
            "options": [
                {"label": "Jellyfin", "description": "Free and open source"},
                {"label": "Plex"},
            ],
        },
        {
            "header": "Extras",
            "question": "Anything else?",
            "options": [{"label": "Subtitles"}, {"label": "Transcoding"}],
            "multi_select": True,
        },
    ]
}


def asking(seen: list[str], also: dict | None = None) -> FunctionModel:
    """Asks QUESTION once per user prompt (with `also`, an action in the same response),
    then says what it was told."""

    async def reply(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator:
        last = messages[-1]
        returns = [p for p in last.parts if p.part_kind in ("tool-return", "retry-prompt")]
        for p in returns:
            seen.append(f"{p.tool_name}: {p.content}")
        if any(p.part_kind == "user-prompt" for p in last.parts) and not returns:
            calls = {
                0: DeltaToolCall(
                    name="ask_user_question", json_args=json.dumps(QUESTION), tool_call_id="q1"
                )
            }
            if also:
                calls[1] = DeltaToolCall(json_args=json.dumps(also["args"]), **also["head"])
            yield calls
        else:
            yield "Done."

    return FunctionModel(stream_function=reply)


def picks(declined: bool = False, **by_header) -> dict:
    return {
        "id": "q1",
        "declined": declined,
        "answers": [
            {"header": h, **({"custom": v} if isinstance(v, str) else {"selected": v})}
            for h, v in by_header.items()
        ],
    }


def reply_to(client, conv, *, decisions=(), answers=()):
    url = f"/api/assistant/conversations/{conv}/approvals"
    body = {"decisions": list(decisions), "answers": list(answers)}
    with client.stream("POST", url, json=body) as res:
        if res.status_code != 200:
            res.read()
            return res
        return read_events(res)


def question_part(client, conv):
    parts = [p for m in detail(client, conv)["messages"] for p in m["parts"]]
    return next(p for p in parts if p.get("tool_name") == "ask_user_question")


# ---------------------------------------------------------------- questions


def test_a_question_pauses_the_chat_until_answered(tmp_path, monkeypatch):
    seen: list[str] = []
    client, conv, _, _ = setup(tmp_path)
    use(monkeypatch, asking(seen))
    try:
        events = send(client, conv, "Set up a media server")
        assert ("question", {"ids": ["q1"]}) in events
        assert not [e for e, _ in events if e == "approval"]
        part = question_part(client, conv)
        assert part["state"] == "question"
        assert part["args"]["questions"][0]["header"] == "Server"

        events = reply_to(
            client, conv, answers=[picks(Server=["Jellyfin"], Extras=["Subtitles", "Transcoding"])]
        )
        assert events[-1][0] == "done"
        told = json.loads(seen[-1].removeprefix("ask_user_question: ").replace("'", '"'))
        assert told == {"Server": ["Jellyfin"], "Extras": ["Subtitles", "Transcoding"]}
        assert question_part(client, conv)["state"] == "done"
        # Answering a question changes nothing on the host, so it isn't audited.
        assert not [a for a, _ in audit_rows(client) if a.startswith("assistant.")]
    finally:
        client.__exit__(None, None, None)


def test_a_typed_answer_and_a_decline(tmp_path, monkeypatch):
    seen: list[str] = []
    client, conv, _, _ = setup(tmp_path)
    use(monkeypatch, asking(seen))
    try:
        send(client, conv, "Set up a media server")
        reply_to(client, conv, answers=[picks(Server="Emby, please", Extras=["Subtitles"])])
        assert "Emby, please" in seen[-1]

        send(client, conv, "Again")
        reply_to(client, conv, answers=[picks(declined=True)])
        assert "declined" in seen[-1]
    finally:
        client.__exit__(None, None, None)


def test_answers_must_fit_the_questions(tmp_path, monkeypatch):
    client, conv, _, _ = setup(tmp_path)
    use(monkeypatch, asking([]))
    try:
        send(client, conv, "Set up a media server")
        # Missing the question entirely, a label it didn't offer, two picks on a single choice.
        assert reply_to(client, conv).status_code == 422
        bad = picks(Server=["Emby"], Extras=["Subtitles"])
        assert reply_to(client, conv, answers=[bad]).status_code == 422
        two = picks(Server=["Jellyfin", "Plex"], Extras=["Subtitles"])
        assert reply_to(client, conv, answers=[two]).status_code == 422
        # Still waiting after the refusals.
        assert question_part(client, conv)["state"] == "question"
    finally:
        client.__exit__(None, None, None)


def test_a_new_message_declines_a_waiting_question(tmp_path, monkeypatch):
    seen: list[str] = []
    client, conv, _, _ = setup(tmp_path)
    use(monkeypatch, asking(seen))
    try:
        send(client, conv, "Set up a media server")
        send(client, conv, "Never mind, list my apps")
        assert any("sent a new message instead" in s for s in seen)
    finally:
        client.__exit__(None, None, None)


def test_a_question_and_an_action_are_answered_together(tmp_path, monkeypatch):
    seen: list[str] = []
    client, conv, loc, share = setup(tmp_path)
    use(monkeypatch, asking(seen, also=folder_call(loc, "media", call_id="c1")))
    try:
        events = send(client, conv, "Set up a media server")
        assert ("question", {"ids": ["q1"]}) in events
        assert next(d for e, d in events if e == "approval")["calls"][0]["id"] == "c1"

        # Both kinds must be answered in one go.
        only_action = answer(client, conv, [{"id": "c1", "approve": True}])
        assert only_action.status_code == 422
        events = reply_to(
            client,
            conv,
            decisions=[{"id": "c1", "approve": True}],
            answers=[picks(Server=["Plex"], Extras=["Subtitles"])],
        )
        assert events[-1][0] == "done"
        assert (share / "media").is_dir()
        assert any("Plex" in s for s in seen)
        assert ("assistant.approve", "Create the folder media in Share") in audit_rows(client)
    finally:
        client.__exit__(None, None, None)


# ---------------------------------------------------------------- plans


def planning(plans_per_prompt: list[list[list[dict]]]) -> FunctionModel:
    """On each user prompt, writes that prompt's plans one after the other (the second
    usually marks a step done), then answers."""
    prompts = iter(plans_per_prompt)
    queue: list[list[dict]] = []

    async def reply(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator:
        last = messages[-1]
        if any(p.part_kind == "user-prompt" for p in last.parts):
            queue[:] = next(prompts)
        if queue:
            items = queue.pop(0)
            yield {
                0: DeltaToolCall(
                    name="write_plan",
                    json_args=json.dumps({"items": items}),
                    tool_call_id=f"p{len(queue)}",
                )
            }
        else:
            yield "Planned."

    return FunctionModel(stream_function=reply)


STEPS = [
    {"content": "Install Jellyfin", "active_form": "Installing Jellyfin"},
    {"content": "Add the media folder"},
]
DONE_FIRST = [{**STEPS[0], "status": "completed"}, STEPS[1]]


def test_the_plan_is_kept_per_chat_and_streamed(tmp_path, monkeypatch):
    client, conv, _, _ = setup(tmp_path)
    use(monkeypatch, planning([[STEPS, DONE_FIRST], [[{"content": "Check the logs"}]]]))
    try:
        assert detail(client, conv)["plan"] == []
        events = send(client, conv, "Set up a media server")
        plans = [d["steps"] for e, d in events if e == "plan"]
        assert len(plans) == 2  # one per write_plan
        assert [(s["content"], s["status"]) for s in plans[0]] == [
            ("Install Jellyfin", "pending"),
            ("Add the media folder", "pending"),
        ]
        assert plans[1][0]["status"] == "completed"

        plan = detail(client, conv)["plan"]
        assert plan == plans[1]
        assert plan[0]["active_form"] == "Installing Jellyfin"

        # Another chat has its own (empty) plan.
        other = client.post("/api/assistant/conversations", json={}).json()["id"]
        assert detail(client, other)["plan"] == []

        # A new plan in the next turn replaces this one.
        send(client, conv, "Now something else")
        assert [s["content"] for s in detail(client, conv)["plan"]] == ["Check the logs"]

        # Deleting the chat deletes its plan.
        assert client.delete(f"/api/assistant/conversations/{conv}").status_code == 204
        store = plan_store(client.app.state.settings.data_dir, conv)
        assert asyncio.run(store.get_items()) == []
    finally:
        client.__exit__(None, None, None)
