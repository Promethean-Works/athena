"""The assistant's opt-in shell (M7 part C): allowlist, approval, running, audit."""

import asyncio
import sys

import pytest
from conftest import make_app, signed_in
from fake_probe import FakeProbe
from fastapi.testclient import TestClient
from pydantic_ai.capabilities import LocalWorkspace
from pydantic_ai_harness import Shell
from pydantic_ai_harness.permissions import Permissions
from test_assistant_actions import (
    answer,
    audit_rows,
    manifest,
    scripted,
    send,
    setup,
    use,
)

from athena.assistant import actions, shell, workspace
from athena.assistant.tools import toolset_for
from athena.platform.capabilities import Capability
from athena.platform.detect import WSL_CHECK, detect, detect_assistant_shell
from athena.platform.probe import RunResult
from athena.platform.store import CapabilityStore


@pytest.fixture(autouse=True)
def host_like_this_one(monkeypatch):
    """The chat tests' fake host matches the OS they run on: macOS (the harness Shell) on
    POSIX, a Windows host without WSL (the PowerShell run_command) on Windows, where the
    harness's local workspace can't run."""
    if sys.platform == "win32":  # pragma: no cover - Windows CI
        import test_assistant_actions

        def windows_app(tmp_path):
            probe = FakeProbe(os="windows")
            return make_app(tmp_path, store=CapabilityStore(detector=lambda: detect(probe)))

        monkeypatch.setattr(test_assistant_actions, "make_app", windows_app)


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
    monkeypatch.setattr(shell, "MAX_OUTPUT", 12)  # "last-line" plus \r\n on Windows
    result = asyncio.run(shell.run("echo first; echo last-line", 30))
    assert result.truncated and "last-line" in result.output and "first" not in result.output


# ---------------------------------------------------------------- the tool


def shell_manifest(provider: str | None):
    m = manifest(("terminal.host", "ready"))
    if provider:
        m.capabilities.append(
            Capability(id="assistant.shell", label="x", status="ready", provider=provider)
        )
    return m


def test_powershell_run_command_is_only_for_windows_without_wsl():
    assert "run_command" not in toolset_for(shell_manifest("powershell")).tools  # switch off
    assert "run_command" not in toolset_for(shell_manifest(None), ("ls",)).tools
    for provider in ("posix", "wsl"):  # these get the harness Shell instead
        assert "run_command" not in toolset_for(shell_manifest(provider), ("ls",)).tools
    tool = toolset_for(shell_manifest("powershell"), ("ls", "df")).tools["run_command"]
    assert "Allowed programs: ls, df." in (tool.description or "")
    assert not tool.requires_approval  # it asks itself, after the allowlist check


def test_posix_and_wsl_get_the_harness_shell():
    assert workspace.shell_capabilities("posix", ()) == []  # switch off or empty list
    assert workspace.shell_capabilities("powershell", ("ls",)) == []
    assert workspace.shell_capabilities(None, ("ls",)) == []
    if sys.platform != "win32":  # LocalWorkspace refuses to be built on Windows
        posix = [type(c) for c in workspace.shell_capabilities("posix", ("ls",))]
        assert posix == [LocalWorkspace, Shell, Permissions, workspace.ShellGuard]
    wsl = [type(c) for c in workspace.shell_capabilities("wsl", ("ls",))]
    assert wsl == [workspace.WSLWorkspace, Shell, Permissions, workspace.ShellGuard]


def test_detection_picks_where_the_shell_runs():
    assert detect_assistant_shell(FakeProbe(os="linux")).provider == "posix"
    assert detect_assistant_shell(FakeProbe(os="darwin")).provider == "posix"
    wsl = FakeProbe(
        os="windows",
        binaries={"wsl": "C:/Windows/System32/wsl.exe"},
        commands={tuple(WSL_CHECK): RunResult(0, "athena-wsl-ok\n")},
    )
    assert detect_assistant_shell(wsl).provider == "wsl"
    no_distro = FakeProbe(os="windows", binaries={"wsl": "C:/Windows/System32/wsl.exe"})
    assert detect_assistant_shell(no_distro).provider == "powershell"
    assert detect_assistant_shell(FakeProbe(os="windows")).provider == "powershell"


@pytest.mark.parametrize(
    ("tool", "result", "outcome"),
    [
        ("run_command", "[stdout]\nok\n", "exit 0"),
        ("run_command", "[stderr]\nno\n\n[exit code: 2]", "exit 2"),
        ("run_command", "[stdout]\n[exit code: 9]\n\n[exit code: 1]", "exit 1"),
        ("run_command", "[stdout]\npartial\n[Command timed out after 5s]", "timed out"),
        ("start_command", "Started command abc", "started in the background"),
    ],
)
def test_the_audit_row_reads_the_harness_result(tool, result, outcome):
    assert workspace._outcome(tool, result) == outcome


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


def audit_details(client, action: str) -> list[tuple[str | None, str | None]]:
    from sqlmodel import select

    from athena.db.models import AuditEntry

    for session in client.app.state.db.session():
        rows = session.exec(select(AuditEntry).where(AuditEntry.action == action)).all()
        return [(r.target, r.detail) for r in rows]
    return []


def test_a_failing_command_is_audited_with_its_exit_code(tmp_path, monkeypatch):
    seen: list[str] = []
    client, conv, _, _ = setup(tmp_path)
    use(monkeypatch, scripted(shell_call("ls /no-such-folder-athena"), seen))
    try:
        enable_shell(client, ["ls"])
        send(client, conv, "List it")
        events = answer(client, conv, [{"id": "s1", "approve": True}])
        result = next(d for e, d in events if e == "tool-result")
        assert "exit" in result["result"].lower()  # "[exit code: N]", or PowerShell's "exit_code"
        target, detail = audit_details(client, "assistant.shell")[0]
        assert target == "ls /no-such-folder-athena" and detail not in (None, "exit 0")
    finally:
        client.__exit__(None, None, None)


# ---------------------------------------------------------------- the WSL workspace
# The same script, run by the local sh instead of wsl.exe (launcher=()).

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="needs a POSIX sh")


def local_wsl(**kwargs) -> workspace.WSLWorkspaceBackend:
    return workspace.WSLWorkspaceBackend(launcher=(), **kwargs)


@posix_only
def test_wsl_backend_runs_commands_in_the_home_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    backend = local_wsl(env={"GREETING": "hi there"})

    async def go():
        assert await backend.working_dir() == str(tmp_path.resolve())
        ok = await backend.run('echo "$GREETING"; echo oops >&2', shell=True, timeout=30)
        assert (ok.exit_code, ok.stdout, ok.stderr) == (0, "hi there\n", "oops\n")
        failed = await backend.run(["sh", "-c", "exit 7"], timeout=30)
        assert failed.exit_code == 7
        missing = await backend.run(["athena-no-such-program"], timeout=30)
        assert missing.exit_code == 127

    asyncio.run(go())


@posix_only
def test_wsl_backend_kills_the_whole_command_on_timeout(tmp_path, monkeypatch):
    from pydantic_ai.workspaces import WorkspaceTimeoutError

    monkeypatch.setenv("HOME", str(tmp_path))
    marker = tmp_path / "survived"
    backend = local_wsl()

    async def go():
        with pytest.raises(WorkspaceTimeoutError) as caught:
            await backend.run(f"echo started; sleep 3 && touch {marker}", shell=True, timeout=1)
        assert "started" in caught.value.stdout
        await asyncio.sleep(3)

    asyncio.run(go())
    assert not marker.exists()  # the sleep's group was killed, not just the outer sh


@posix_only
def test_wsl_backend_reports_when_wsl_is_unavailable():
    from pydantic_ai.workspaces import WorkspaceUnavailableError

    backend = workspace.WSLWorkspaceBackend(launcher=("false",))
    with pytest.raises(WorkspaceUnavailableError):
        asyncio.run(backend.run("echo hi", shell=True, timeout=30))


@posix_only
def test_the_harness_shell_runs_through_the_wsl_workspace(tmp_path, monkeypatch):
    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    monkeypatch.setenv("HOME", str(tmp_path))

    def reply(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        returns = [p for p in messages[-1].parts if p.part_kind == "tool-return"]
        if returns:
            return ModelResponse(parts=[TextPart(str(returns[0].content))])
        return ModelResponse(parts=[ToolCallPart("run_command", {"command": "echo via-wsl; pwd"})])

    agent = Agent(
        FunctionModel(reply),
        capabilities=[workspace.WSLWorkspace(launcher=()), Shell(allowed_commands=["echo", "pwd"])],
    )
    output = agent.run_sync("go").output
    assert "via-wsl" in output and str(tmp_path.resolve()) in output
