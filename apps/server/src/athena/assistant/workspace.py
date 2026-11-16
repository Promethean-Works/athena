"""Where the assistant's shell runs, built on pydantic-ai-harness (docs/mvp-design.md §4.5).

- Linux and macOS: the harness `Shell` in a `LocalWorkspace` (the service user's home).
- Windows with a WSL distro: the same `Shell` in `WSLWorkspace`, which runs every command in
  the default distro through `wsl.exe` (the harness's local workspace is POSIX-only).
- Windows without WSL: no harness shell; `actions.run_command` runs PowerShell instead.

`ShellGuard` checks the allowlist (every program in a pipe or chain) after the arguments are
validated and before `Permissions` asks the admin, so a refused command never makes a card,
and writes the audit row once a command has run.
"""

import asyncio
import contextlib
import re
import secrets
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import KW_ONLY, dataclass, field
from typing import Any

from pydantic_ai import RunContext, ToolFailed
from pydantic_ai.capabilities import AbstractCapability, LocalWorkspace
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.workspaces import (
    CommandResult,
    SupportsCommands,
    WorkspaceBackend,
    WorkspaceCommand,
    WorkspaceOutputLimitError,
    WorkspaceRef,
    WorkspaceTimeoutError,
    WorkspaceUnavailableError,
)
from pydantic_ai_harness import Shell
from pydantic_ai_harness.permissions import Permissions

from athena import audit
from athena.assistant import shell
from athena.terminal import shells

COMMAND_TOOLS = frozenset({"run_command", "start_command", "shell"})
"""The harness Shell tools that take a command line (check/stop take a job id)."""
OUTPUT_LIMIT = 10 * 1024 * 1024
"""Bytes per stream before a WSL command is stopped, like the harness's own limit."""
DEFAULT_TIMEOUT = 60.0
SHELL_ENV = {"TERM": "dumb", "NO_COLOR": "1", "PAGER": "cat", "SYSTEMD_PAGER": ""}
"""No colors and no pagers: the output goes to a model."""

_READY = "__athena_wsl_ready__\n"


class WSLWorkspaceBackend(WorkspaceBackend, SupportsCommands):
    """Runs commands in the default WSL distro: `wsl.exe -e /bin/sh -c <script>`.

    The script reports that it started (so wsl.exe's own failures aren't taken for the
    command's exit code), runs the command as a job in its own process group (`set -m`),
    reports that group, and reports the command's status. On a timeout or cancellation a
    second wsl.exe call kills the group, since killing wsl.exe on Windows leaves the Linux
    side running. `launcher` is `()` in tests, which runs the same script with the local sh.
    """

    def __init__(
        self, *, launcher: Sequence[str] = ("wsl.exe", "-e"), env: Mapping[str, str] | None = None
    ) -> None:
        self._launcher = list(launcher)
        self._env = dict(env or {})
        self._dir: str | None = None
        self._ref = WorkspaceRef(provider="wsl", id="default")

    @property
    def ref(self) -> WorkspaceRef:
        return self._ref

    async def working_dir(self) -> str:
        if self._dir is None:
            result = await self._remote(None, "/bin/sh -c 'pwd -P'", env={}, timeout=30)
            self._dir = result.stdout.strip()
        return self._dir

    async def run(
        self,
        command: WorkspaceCommand,
        *,
        shell: bool = False,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        if isinstance(command, str):
            if not shell:
                raise TypeError("a string command requires shell=True")
            job = f"/bin/sh -c {shlex.quote(command)}"
        elif shell:
            raise TypeError("an argv sequence cannot be combined with shell=True")
        elif not command:
            raise ValueError("command must not be empty")
        else:
            job = shlex.join(command)
        directory = await self.working_dir()
        merged = {**self._env, **(env or {})}
        return await self._remote(directory, job, env=merged, timeout=timeout)

    async def _remote(
        self, directory: str | None, job: str, *, env: Mapping[str, str], timeout: float | None
    ) -> CommandResult:
        nonce = secrets.token_hex(12)
        done = f"__athena_done_{nonce}_"
        group = f"__athena_group_{nonce}_"
        pattern = re.compile(rf"\n(?:{done}\d+|{group}(?:group|pid)_\d+)\n")
        exports = "".join(
            f"export {name}={shlex.quote(value)}\n"
            for name, value in env.items()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
        )
        cd = f"cd {shlex.quote(directory)}" if directory else 'cd "$HOME"'
        script = (
            "{\n"
            f"{cd} || exit 1\n"
            f"printf '%s' {shlex.quote(_READY)} >&2\n"
            f"{exports}"
            # The job gets a process group of its own, so a stop kills everything it started:
            # setsid where it exists (dash, /bin/sh on Debian and Ubuntu, refuses `set -m`
            # without a terminal), else job control, checked with ps. When neither worked,
            # only the job's pid is reported, so a stop never kills the script's own group.
            "if command -v setsid >/dev/null 2>&1; then\n"
            f"  setsid {job} &\n"
            "  __athena_job=$!; __athena_kind=group\n"
            "else\n"
            "  set -m 2>/dev/null\n"
            f"  {job} &\n"
            "  __athena_job=$!\n"
            "  set +m 2>/dev/null\n"  # no "[1]+ Done" notices in the command's stderr
            '  __athena_pg=$(ps -o pgid= -p "$__athena_job" 2>/dev/null | tr -d " ")\n'
            '  if [ "$__athena_pg" = "$__athena_job" ]; then __athena_kind=group; '
            "else __athena_kind=pid; fi\n"
            "fi\n"
            f'printf \'\\n{group}%s_%d\\n\' "$__athena_kind" "$__athena_job" >&2\n'
            'wait "$__athena_job"\n'
            "__athena_status=$?\n"
            f"printf '\\n{done}%d\\n' \"$__athena_status\" >&2\n"
            'exit "$__athena_status"\n'
            "} < /dev/null\n"
        )
        argv = [*self._launcher, "/bin/sh", "-c", script, "athena-wsl"]
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = bytearray(), bytearray()
        over = False

        async def pump(stream: asyncio.StreamReader | None, buf: bytearray) -> None:
            nonlocal over
            assert stream is not None
            while chunk := await stream.read(65536):
                if over:
                    continue  # keep draining, so the command never blocks on a full pipe
                buf.extend(chunk)
                if len(buf) > OUTPUT_LIMIT:
                    over = True

        def text(buf: bytearray) -> str:
            return bytes(buf).decode("utf-8", errors="replace")

        async def stop() -> None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            found = re.search(rf"\n{group}(group|pid)_(\d+)\n", text(err))
            if found:  # kill the command (its group when it has one) on the Linux side
                target = f"-- -{found[2]}" if found[1] == "group" else found[2]
                kill = f"kill -s KILL {target} 2>/dev/null; exit 0"
                with contextlib.suppress(Exception):
                    killer = await asyncio.create_subprocess_exec(
                        *self._launcher, "/bin/sh", "-c", kill,
                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                    )  # fmt: skip
                    await asyncio.wait_for(killer.wait(), 5)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), 5)

        reading = asyncio.gather(pump(proc.stdout, out), pump(proc.stderr, err))
        try:
            await asyncio.wait_for(asyncio.shield(reading), timeout)
            if over:
                await stop()
                raise WorkspaceOutputLimitError(
                    "WSL command output passed 10 MiB; redirect it to a file and read part of it",
                    limit=OUTPUT_LIMIT,
                    stdout=text(out)[-50_000:],
                    stderr=pattern.sub("", text(err).partition(_READY)[2])[-50_000:],
                )
            code = await proc.wait()
        except TimeoutError:
            await asyncio.shield(stop())
            reading.cancel()
            stderr = pattern.sub("", text(err).partition(_READY)[2])
            raise WorkspaceTimeoutError(
                f"command timed out after {timeout:g}s", stdout=text(out), stderr=stderr
            ) from None
        except asyncio.CancelledError:
            await asyncio.shield(stop())
            reading.cancel()
            raise
        before, ready, after = text(err).partition(_READY)
        if not ready:
            raise WorkspaceUnavailableError(f"WSL is unavailable: {_wsl_message(err) or before}")
        status = re.search(rf"\n{done}(\d+)\n", after)
        if status is None:
            raise WorkspaceUnavailableError("WSL stopped during the command")
        del code  # wsl.exe's own code; the marker carries the command's
        return CommandResult(
            exit_code=int(status[1]), stdout=text(out), stderr=pattern.sub("", after)
        )


def _wsl_message(err: bytearray) -> str:
    """wsl.exe writes its own errors in UTF-16."""
    raw = bytes(err)
    if b"\x00" in raw:
        return raw.decode("utf-16-le", errors="replace").replace("\x00", "").strip()
    return ""


@dataclass
class WSLWorkspace(AbstractCapability[Any]):
    """Gives runs a workspace in the default WSL distro (see `WSLWorkspaceBackend`)."""

    _: KW_ONLY
    launcher: Sequence[str] = ("wsl.exe", "-e")
    env: Mapping[str, str] | None = field(default=None, repr=False)
    id: str | None = "wsl_workspace"

    def get_workspace(self, ctx: RunContext[Any], *, ref: WorkspaceRef | None) -> Any:
        backend = WSLWorkspaceBackend(launcher=self.launcher, env=self.env)
        if ref is not None and ref != backend.ref:
            return None
        return backend


@dataclass
class ShellGuard(AbstractCapability[Any]):
    """The allowlist check before the approval card, and the audit row after a command ran."""

    commands: tuple[str, ...]
    _: KW_ONLY
    id: str | None = "athena_shell_guard"

    async def after_tool_validate(
        self, ctx: RunContext[Any], *, call: ToolCallPart, tool_def: ToolDefinition, args: Any
    ) -> Any:
        if call.tool_name in COMMAND_TOOLS and isinstance(args, dict):
            problem = shell.check(str(args.get("command", "")), self.commands)
            if problem:
                raise ToolFailed(problem)
        return args

    async def after_tool_execute(
        self,
        ctx: RunContext[Any],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: Any,
        result: Any,
    ) -> Any:
        if call.tool_name in COMMAND_TOOLS and isinstance(args, dict):
            deps = ctx.deps
            command = str(args.get("command", ""))[:500]
            outcome = _outcome(call.tool_name, result)
            audit.record(deps.db, deps.username, "assistant.shell", command, outcome)
        return result


def _outcome(tool: str, result: Any) -> str:
    if tool == "start_command":
        return "started in the background"
    # The harness adds "[exit code: N]" only when N isn't 0, and a trailer on a timeout; the
    # last match wins, in case the command printed the same text.
    text = str(result)
    if "[Command timed out after" in text:
        return "timed out"
    found = re.findall(r"\[exit code: (-?\d+)\]", text)
    return f"exit {found[-1]}" if found else "exit 0"


def shell_capabilities(provider: str | None, commands: tuple[str, ...]) -> list[Any]:
    """The capabilities that give a run the harness shell, or [] when it uses PowerShell
    (`actions.run_command`) or is off."""
    if not commands or provider not in ("posix", "wsl"):
        return []
    workspace: Any = (
        WSLWorkspace(env=SHELL_ENV)
        if provider == "wsl"
        else LocalWorkspace(shells.home(), env=SHELL_ENV)
    )
    return [
        workspace,
        Shell(
            allowed_commands=list(commands),
            default_timeout=DEFAULT_TIMEOUT,
            max_output_chars=shell.MAX_OUTPUT,
        ),
        Permissions(mode="read-only"),
        ShellGuard(commands),
    ]
