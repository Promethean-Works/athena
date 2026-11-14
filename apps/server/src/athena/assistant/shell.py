"""The assistant's opt-in shell (docs/mvp-design.md §4.5, part C).

Off by default (Settings → AI). Every command needs the admin's approval, and before it
even gets a card, each command in it (the first word of every part of a pipe or chain)
must be on the allowlist. The allowlist is a guard against mistakes, not a sandbox: an
allowed program can start others, which is why the approval stays.
"""

import asyncio
import shlex
from dataclasses import dataclass

from athena.terminal import shells

MAX_OUTPUT = 20_000
"""Characters of output kept, from the end (where errors and results usually are)."""
SEPARATORS = {"|", "||", "&", "&&", ";", ";;", "|&"}
REFUSED = {"`": "backticks", "$(": "$( )", "<(": "<( )", ">(": ">( )"}


def _key(word: str) -> str:
    if shells.CASE_INSENSITIVE:
        word = word.lower()
        return word.removesuffix(".exe")
    return word


def commands_in(command: str) -> list[str]:
    """The program each part of a command line runs: the first word, and the first word
    after every |, &&, ; and the like. Raises ValueError for what can't be checked."""
    for text, name in REFUSED.items():
        if text in command:
            raise ValueError(f"Commands inside {name} can't be checked against the allowlist")
    lexer = shlex.shlex(command.replace("\n", ";"), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError as exc:  # an unclosed quote
        raise ValueError(f"Can't read the command: {exc}") from exc
    words: list[str] = []
    expect = True
    for token in tokens:
        if token in SEPARATORS:
            expect = True
        elif token in ("(", ")"):
            raise ValueError("Subshells ( ) can't be checked against the allowlist")
        elif expect:
            words.append(token)
            expect = False
    if not words:
        raise ValueError("The command is empty")
    return words


def check(command: str, allowed: list[str] | tuple[str, ...]) -> str | None:
    """Why the command can't run, or None when every program in it is allowed."""
    try:
        words = commands_in(command)
    except ValueError as exc:
        return str(exc)
    ok = {_key(a) for a in allowed}
    refused = sorted({w for w in words if _key(w) not in ok})
    if refused:
        return (
            f"Not on the shell allowlist: {', '.join(refused)}. Allowed: {', '.join(allowed)}. "
            "The admin can change the list in Settings → AI."
        )
    return None


@dataclass
class Result:
    exit_code: int | None
    """None when the command was stopped for taking too long."""
    output: str
    truncated: bool
    timed_out: bool


async def run(command: str, timeout: float) -> Result:
    """Runs the command with the host's shell, stdout and stderr together, no input."""
    proc = await asyncio.create_subprocess_exec(
        *shells.command_argv(command),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=shells.home(),
        env=shells.command_env(),
        start_new_session=True,
    )
    assert proc.stdout is not None
    buf = bytearray()
    dropped = False

    async def collect() -> None:
        nonlocal dropped
        assert proc.stdout is not None
        while chunk := await proc.stdout.read(65536):
            buf.extend(chunk)
            if len(buf) > MAX_OUTPUT * 4:  # bytes; up to 4 per character
                del buf[: len(buf) - MAX_OUTPUT * 4]
                dropped = True
        await proc.wait()

    timed_out = False
    try:
        await asyncio.wait_for(collect(), timeout)
    except TimeoutError:
        timed_out = True
        shells.kill_tree(proc.pid)
        await proc.wait()
    text = bytes(buf).decode("utf-8", errors="replace")
    truncated = dropped or len(text) > MAX_OUTPUT
    return Result(
        exit_code=None if timed_out else proc.returncode,
        output=text[-MAX_OUTPUT:],
        truncated=truncated,
        timed_out=timed_out,
    )
