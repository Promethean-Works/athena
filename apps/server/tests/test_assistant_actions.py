"""The assistant's actions: tools that need the admin's approval (M7 part B)."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import make_app, signed_in
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from sqlmodel import select
from test_assistant import add_provider, read_events

from athena.api import assistant as assistant_api
from athena.assistant import actions
from athena.assistant.tools import toolset_for
from athena.db.models import AuditEntry
from athena.platform.capabilities import Capability, CapabilityManifest


def scripted(call: dict, seen: list[str]) -> FunctionModel:
    """Calls `call` once per user prompt, then describes the tool's answer in text.
    `seen` collects what the model was told."""

    async def reply(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator:
        last = messages[-1]
        returns = [p for p in last.parts if p.part_kind in ("tool-return", "retry-prompt")]
        if returns:
            for p in returns:
                seen.append(f"{getattr(p, 'outcome', 'retry')}: {p.content}")
        if any(p.part_kind == "user-prompt" for p in last.parts) and not returns:
            yield {0: DeltaToolCall(json_args=json.dumps(call["args"]), **call["head"])}
        else:
            yield "Done."

    return FunctionModel(stream_function=reply)


def folder_call(location: int, name: str, call_id: str = "c1") -> dict:
    return {
        "head": {"name": "create_folder", "tool_call_id": call_id},
        "args": {"location_id": location, "path": "", "name": name},
    }


def use(monkeypatch, model: FunctionModel) -> None:
    monkeypatch.setattr(assistant_api, "build_model", lambda cfg, model_id: model)


def setup(tmp_path):
    client = TestClient(make_app(tmp_path))
    client.__enter__()
    signed_in(client)
    pid = add_provider(client)["id"]
    conv = client.post(
        "/api/assistant/conversations", json={"model": {"provider_id": pid, "model": "m"}}
    ).json()
    share = tmp_path / "share"
    share.mkdir()
    loc = client.post("/api/files/locations", json={"name": "Share", "path": str(share)}).json()
    return client, conv["id"], loc["id"], share


def send(client, conv_id, text):
    url = f"/api/assistant/conversations/{conv_id}/messages"
    with client.stream("POST", url, json={"text": text}) as res:
        assert res.status_code == 200, res.read()
        return read_events(res)


def answer(client, conv_id, decisions):
    url = f"/api/assistant/conversations/{conv_id}/approvals"
    with client.stream("POST", url, json={"decisions": decisions}) as res:
        if res.status_code != 200:
            res.read()
            return res
        return read_events(res)


def audit_rows(client):
    db = client.app.state.db
    for session in db.session():
        return [(r.action, r.target) for r in session.exec(select(AuditEntry)).all()]


def detail(client, conv_id):
    return client.get(f"/api/assistant/conversations/{conv_id}").json()


def tool_part(client, conv_id):
    parts = [p for m in detail(client, conv_id)["messages"] for p in m["parts"]]
    return next(p for p in parts if p["type"] == "tool")


# ---------------------------------------------------------------- approve and deny


def test_an_action_waits_for_approval_then_runs(tmp_path, monkeypatch):
    seen: list[str] = []
    client, conv, loc, share = setup(tmp_path)
    use(monkeypatch, scripted(folder_call(loc, "photos"), seen))
    try:
        events = send(client, conv, "Make a photos folder")
        approval = next(d for e, d in events if e == "approval")
        assert approval["calls"] == [
            {
                "id": "c1",
                "name": "create_folder",
                "args": {"location_id": loc, "path": "", "name": "photos"},
                "summary": "Create the folder photos in Share",
                "destructive": False,
            }
        ]
        assert not (share / "photos").exists()  # nothing ran yet
        assert events[-1][0] == "done"

        # A reload shows the card again.
        part = tool_part(client, conv)
        assert part["state"] == "approval"
        assert part["summary"] == "Create the folder photos in Share"

        events = answer(client, conv, [{"id": "c1", "approve": True}])
        result = next(d for e, d in events if e == "tool-result")
        assert result["error"] is None and '"name": "photos"' in result["result"]
        assert (share / "photos").is_dir()
        assert "".join(d["delta"] for e, d in events if e == "text") == "Done."
        assert tool_part(client, conv)["state"] == "done"
        assert ("assistant.approve", "Create the folder photos in Share") in audit_rows(client)

        # Nothing is waiting any more.
        res = answer(client, conv, [{"id": "c1", "approve": True}])
        assert res.status_code == 409
    finally:
        client.__exit__(None, None, None)


def test_a_denied_action_does_not_run(tmp_path, monkeypatch):
    seen: list[str] = []
    client, conv, loc, share = setup(tmp_path)
    use(monkeypatch, scripted(folder_call(loc, "junk"), seen))
    try:
        send(client, conv, "Make a junk folder")
        events = answer(client, conv, [{"id": "c1", "approve": False, "reason": "not now"}])
        assert not (share / "junk").exists()
        assert seen == ["denied: The admin denied this: not now"]
        result = next(d for e, d in events if e == "tool-result")
        assert "not now" in result["result"] and result["denied"] is True
        assert tool_part(client, conv)["state"] == "denied"
        assert ("assistant.deny", "Create the folder junk in Share") in audit_rows(client)
    finally:
        client.__exit__(None, None, None)


def test_a_new_message_denies_waiting_actions(tmp_path, monkeypatch):
    seen: list[str] = []
    client, conv, loc, share = setup(tmp_path)
    use(monkeypatch, scripted(folder_call(loc, "a"), seen))
    try:
        send(client, conv, "Make folder a")
        events = send(client, conv, "Actually, never mind")
        assert not (share / "a").exists()
        assert seen[0] == f"denied: {assistant_api.chat.DENIED_BY_NEW_MESSAGE}"
        assert ("assistant.deny", "Create the folder a in Share") in audit_rows(client)
        assert events[-1][0] == "done"
        roles = [m["role"] for m in detail(client, conv)["messages"]]
        assert roles == ["user", "assistant", "user", "assistant"]
    finally:
        client.__exit__(None, None, None)


def test_answers_must_match_the_waiting_actions(tmp_path, monkeypatch):
    client, conv, loc, _ = setup(tmp_path)
    use(monkeypatch, scripted(folder_call(loc, "x"), []))
    try:
        assert answer(client, conv, [{"id": "c1", "approve": True}]).status_code == 409
        send(client, conv, "Make folder x")
        res = answer(client, conv, [{"id": "other", "approve": True}])
        assert res.status_code == 422
        assert tool_part(client, conv)["state"] == "approval"
    finally:
        client.__exit__(None, None, None)


def test_a_failing_action_reports_its_error(tmp_path, monkeypatch):
    seen: list[str] = []
    client, conv, loc, share = setup(tmp_path)
    (share / "taken").mkdir()
    use(monkeypatch, scripted(folder_call(loc, "taken"), seen))
    try:
        send(client, conv, "Make folder taken")
        events = answer(client, conv, [{"id": "c1", "approve": True}])
        result = next(d for e, d in events if e == "tool-result")
        assert "already exists" in (result["error"] or "")
        assert tool_part(client, conv)["state"] == "error"
    finally:
        client.__exit__(None, None, None)


def test_an_action_that_starts_a_job_waits_for_it(tmp_path, monkeypatch):
    client, conv, loc, share = setup(tmp_path)
    (share / "a.txt").write_bytes(b"hello")
    (share / "dest").mkdir()
    call = {
        "head": {"name": "copy_or_move_files", "tool_call_id": "c1"},
        "args": {
            "op": "copy",
            "location_id": loc,
            "paths": ["a.txt"],
            "dest_location_id": loc,
            "dest_path": "dest",
        },
    }
    use(monkeypatch, scripted(call, []))
    try:
        events = send(client, conv, "Copy a.txt into dest")
        summary = next(d for e, d in events if e == "approval")["calls"][0]["summary"]
        assert summary == "Copy a.txt from Share to Share/dest"
        events = answer(client, conv, [{"id": "c1", "approve": True}])
        job = next(d for e, d in events if e == "job")
        assert job["id"] == "c1" and job["title"].startswith("Copy a.txt")
        result = json.loads(next(d for e, d in events if e == "tool-result")["result"])
        assert result["status"] == "succeeded" and result["job_id"] == job["job_id"]
        assert (share / "dest" / "a.txt").read_bytes() == b"hello"
        assert tool_part(client, conv)["job_id"] == job["job_id"]
    finally:
        client.__exit__(None, None, None)


# ---------------------------------------------------------------- tools and cards


def manifest(*caps: tuple[str, str]) -> CapabilityManifest:
    return CapabilityManifest(
        os="linux",
        os_version="Test",
        arch="x86_64",
        detected_at=datetime.now(UTC),
        capabilities=[
            Capability(id=cid, label=cid, status=status, provider="test") for cid, status in caps
        ],
    )


def names(m: CapabilityManifest) -> set[str]:
    result: set[str] = set()
    for ts in toolset_for(m):
        result.update(ts.tools.keys())
    return result


def test_actions_follow_the_capabilities():
    bare = names(manifest())
    assert not bare & actions.NAMES
    files = names(manifest(("files", "ready")))
    assert {"create_folder", "delete_files"} <= files and "install_package" not in files
    everything = names(
        manifest(("files", "ready"), ("containers", "ready"), ("packages.apt", "ready"))
    )
    assert everything >= actions.NAMES
    assert {"search_store", "get_store_app", "search_packages"} <= everything
    stopped = names(manifest(("containers", "stopped"), ("packages.apt", "needs_privilege")))
    assert not stopped & actions.NAMES


def test_every_action_needs_approval():
    toolsets = toolset_for(
        manifest(("files", "ready"), ("containers", "ready"), ("packages.apt", "ready"))
    )
    tools: dict[str, Any] = {}
    for ts in toolsets:
        tools.update(ts.tools)
    for name, tool in tools.items():
        assert tool.requires_approval == (name in actions.NAMES), name


@pytest.mark.parametrize("name", sorted(actions.NAMES))
def test_every_action_has_a_summary(name, tmp_path: Path):
    args = {
        "name": "x",
        "catalog": "builtin",
        "app_id": "x",
        "action": "stop",
        "manager": "apt",
        "location_id": 999,
        "path": "a",
        "paths": ["a"],
        "new_name": "b",
        "op": "copy",
        "dest_location_id": 999,
    }
    with TestClient(make_app(tmp_path)) as client:
        for session in client.app.state.db.session():
            text = actions.summarize(session, name, args)
            assert text and "None" not in text, text
    assert actions.summarize(None, "list_files", {}) is None  # type: ignore[arg-type]


def test_install_form_errors_reach_the_model_readably():
    from fastapi import HTTPException

    from athena.assistant.tools import http_detail

    exc = HTTPException(422, {"message": "Some values need fixing", "errors": {"PORT": "Taken"}})
    assert http_detail(exc) == "Some values need fixing\n- PORT: Taken"
    assert http_detail(HTTPException(409, "jellyfin is busy")) == "jellyfin is busy"
