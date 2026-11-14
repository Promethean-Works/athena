"""The assistant's opt-in shell (M7 part C): allowlist, approval, running, audit."""

import asyncio
import sys

import pytest
from conftest import make_app, signed_in
from fastapi.testclient import TestClient
from test_assistant_actions import (
    answer,
    audit_rows,
    manifest,
    scripted,
    send,
    setup,
    use,
)

from athena.assistant import actions, shell
from athena.assistant.tools import toolset_for

# ---------------------------------------------------------------- the allowlist


@pytest.mark.parametrize(
    ("line", "words"),
    [
        ("df -h", ["df"]),
        ("docker ps | grep web", ["docker", "grep"]),
        ("ls /tmp && cat a.txt; uptime", ["ls", "cat", "uptime"]),
        ("cat a || echo none &", ["cat", "echo"]),
        ("ls\nuptime", ["ls", "uptime"]),
        ("grep 'a | b' file.txt", ["grep"]),  # operators inside quotes are text
        ('grep "x;rm" f > out.txt', ["grep"]),  # a redirect's target isn't a command
    ],
)
def test_every_command_in_a_line_is_found(line, words):
    assert shell.commands_in(line) == words


@pytest.mark.parametrize(
    "line", ["echo $(rm -rf ~)", "echo `id`", "diff <(ls a) <(ls b)", "(cd /; rm x)", "", "  "]
)
def test_lines_that_cant_be_checked_are_refused(line):
    with pytest.raises(ValueError):
        shell.commands_in(line)


def test_an_unclosed_quote_is_refused():
    with pytest.raises(ValueError, match="Can't read"):
        shell.commands_in("echo 'oops")


def test_check_names_what_is_not_allowed():
    allowed = ["ls", "grep"]
    assert shell.check("ls -la | grep x", allowed) is None
    problem = shell.check("ls | xargs rm; rm x", allowed)
    assert problem is not None
    assert "allowlist: rm, xargs." in problem and "Allowed: ls, grep" in problem
    assert shell.check("/bin/ls", allowed) is not None  # a path is its own entry


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ignores case")
def test_windows_ignores_case_and_exe():  # pragma: no cover - Windows CI
    assert shell.check("get-process | WHOAMI.EXE", ["Get-Process", "whoami"]) is None


# ---------------------------------------------------------------- running


def test_run_returns_exit_code_and_output():
    result = asyncio.run(shell.run("echo hello", 30))
    assert result.exit_code == 0 and "hello" in result.output
    assert not result.timed_out and not result.truncated
    assert asyncio.run(shell.run("exit 3", 30)).exit_code == 3


def test_run_stops_a_command_that_takes_too_long():
    result = asyncio.run(shell.run("sleep 30", 1))
    assert result.timed_out and result.exit_code is None


def test_run_keeps_the_end_of_long_output(monkeypatch):
    monkeypatch.setattr(shell, "MAX_OUTPUT", 10)
    result = asyncio.run(shell.run("echo first; echo last-line", 30))
    assert result.truncated and "last-line" in result.output and "first" not in result.output


# ---------------------------------------------------------------- the tool


def test_run_command_needs_the_switch_and_a_shell():
    term = ("terminal.host", "ready")
    assert "run_command" not in toolset_for(manifest(term)).tools
    assert "run_command" not in toolset_for(manifest(), ("ls",)).tools
    assert (
        "run_command" not in toolset_for(manifest(("terminal.host", "unsupported")), ("ls",)).tools
    )
    tool = toolset_for(manifest(term), ("ls", "df")).tools["run_command"]
    assert "Allowed programs: ls, df." in (tool.description or "")
    # It asks for approval itself, after the allowlist check.
    assert not tool.requires_approval


def test_the_card_names_the_command():
    text = actions.summarize(None, "run_command", {"command": "df   -h\n"})  # type: ignore[arg-type]
    assert text == "Run on the server: df -h"
    assert actions.is_destructive("run_command", {"command": "df -h"})


def shell_call(command: str) -> dict:
    return {"head": {"name": "run_command", "tool_call_id": "s1"}, "args": {"command": command}}


def enable_shell(client, commands: list[str]) -> None:
    res = client.put("/api/settings/ai", json={"shell_enabled": True, "shell_commands": commands})
    assert res.status_code == 200, res.text


def test_the_shell_is_off_by_default(tmp_path, monkeypatch):
    seen: list[str] = []
    client, conv, _, _ = setup(tmp_path)
    use(monkeypatch, scripted(shell_call("echo hi"), seen))
    try:
        assert client.get("/api/settings/ai").json()["shell_enabled"] is False
        events = send(client, conv, "Run echo")
        assert not [e for e, _ in events if e == "approval"]
        assert seen and "Unknown tool name" in seen[0]
    finally:
        client.__exit__(None, None, None)


def test_a_command_off_the_allowlist_never_reaches_the_admin(tmp_path, monkeypatch):
    seen: list[str] = []
    client, conv, _, _ = setup(tmp_path)
    use(monkeypatch, scripted(shell_call("echo hi | rm x"), seen))
    try:
        enable_shell(client, ["echo"])
        events = send(client, conv, "Run it")
        assert not [e for e, _ in events if e == "approval"]
        assert any("Not on the shell allowlist: rm" in s for s in seen), seen
        assert not [a for a in audit_rows(client) if a[0] == "assistant.shell"]
    finally:
        client.__exit__(None, None, None)


def test_an_approved_command_runs_and_is_audited(tmp_path, monkeypatch):
    seen: list[str] = []
    client, conv, _, _ = setup(tmp_path)
    use(monkeypatch, scripted(shell_call("echo athena-shell"), seen))
    try:
        enable_shell(client, ["echo"])
        events = send(client, conv, "Say it")
        approval = next(d for e, d in events if e == "approval")
        call = approval["calls"][0]
        assert call["name"] == "run_command" and call["destructive"] is True
        assert call["summary"] == "Run on the server: echo athena-shell"

        events = answer(client, conv, [{"id": "s1", "approve": True}])
        result = next(d for e, d in events if e == "tool-result")
        assert result["error"] is None and "athena-shell" in result["result"]
        assert '"exit_code": 0' in result["result"]
        rows = audit_rows(client)
        assert ("assistant.approve", "Run on the server: echo athena-shell") in rows
        assert ("assistant.shell", "echo athena-shell") in rows
    finally:
        client.__exit__(None, None, None)


def test_the_allowlist_is_checked_again_after_approval(tmp_path, monkeypatch):
    seen: list[str] = []
    client, conv, _, _ = setup(tmp_path)
    use(monkeypatch, scripted(shell_call("echo late"), seen))
    try:
        enable_shell(client, ["echo"])
        send(client, conv, "Say it")
        enable_shell(client, ["ls"])  # the admin narrows the list while the card waits
        events = answer(client, conv, [{"id": "s1", "approve": True}])
        result = next(d for e, d in events if e == "tool-result")
        assert "Not on the shell allowlist: echo" in (result["error"] or result["result"])
        assert not [a for a in audit_rows(client) if a[0] == "assistant.shell"]
    finally:
        client.__exit__(None, None, None)


def test_the_allowlist_rejects_operators(tmp_path):
    with TestClient(make_app(tmp_path)) as client:
        signed_in(client)
        bad = {"shell_enabled": True, "shell_commands": ["ls; rm"]}
        assert client.put("/api/settings/ai", json=bad).status_code == 422
