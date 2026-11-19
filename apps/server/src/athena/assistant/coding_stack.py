"""Coding stack (docs/design/assistant.md, part D stage 3, item 7).

When "Coding stack" is on in Settings → AI, the assistant gets
coding-assistant capabilities in `<data-dir>/assistant/code-workspace`:

- `RepoContext` loads AGENTS.md / CLAUDE.md instruction files into each
  reply's instructions (read-only, no approval).
- `FileSystem` gives `read_file`, `write_file`, `edit_file`,
  `list_directory`, `create_directory` and friends, bounded to the
  code-workspace. Writes go through an Approve/Deny card like the shell,
  via the harness `Permissions` in read-only mode; reads run free.
- `Shell` runs commands in the code-workspace, gated by `ShellGuard`'s
  allowlist check and an `Permissions` approval card, and audited like
  the assistant's own shell. It's only offered when the shell allowlist
  isn't empty, so no commands are available until the admin explicitly
  allows them.

`LocalWorkspace` is POSIX-only (it raises on Windows, with or without WSL),
so the whole stack is only offered on POSIX hosts. The workspace is created
on first use and holds only what the admin puts there.

`Coder` from pydantic-ai-harness is intentionally **not** used: its bundled
`Shell` is unrestricted and bypasses `ShellGuard` / approval cards. The
coding stack composes `FileSystem`, `Shell`, `RepoContext` and `Permissions`
itself so every command goes through the same allowlist and approval as the
assistant shell (`assistant/workspace.py`).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic_ai.capabilities import AbstractCapability, LocalWorkspace
from pydantic_ai_harness.filesystem import FileSystem
from pydantic_ai_harness.permissions import Permissions
from pydantic_ai_harness.repo_context import RepoContext
from pydantic_ai_harness.shell import Shell

from athena.assistant import shell
from athena.assistant.workspace import DEFAULT_TIMEOUT, ShellGuard

CODING_INSTRUCTIONS = (
    "Work inside the code-workspace only. Prefer reads and edits over "
    "rewrites, run tests or linting before declaring a change done, and "
    "never commit or push — ask the admin instead."
)
"""Instructions added to the agent when the coding stack is on."""


def coding_stack_capabilities(
    enabled: bool, data_dir: Path, shell_commands: tuple[str, ...] = ()
) -> list[AbstractCapability[Any]]:
    """Coding-assistant capabilities, or none when the setting is off or no
    POSIX workspace is available.

    `LocalWorkspace` anchors the run at `<data-dir>/assistant/code-workspace`
    (created on first use). `RepoContext` reads instruction files from it and
    `FileSystem` bounds every file operation to it, so the host outside the
    workspace is unaffected. `Permissions` (read-only mode) makes the model
    ask before each write, so `write_file`, `edit_file` and
    `create_directory` show an Approve/Deny card while reads run freely.

    When `shell_commands` is non-empty, `Shell` runs commands in the
    code-workspace, gated by `ShellGuard`'s allowlist check and an
    `Permissions` approval card, and audited as `assistant.shell`.
    """
    if not enabled:
        return []
    if os.name != "posix":
        return []  # LocalWorkspace is POSIX-only; Windows uses PowerShell instead
    workspace = data_dir / "assistant" / "code-workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    caps: list[AbstractCapability[Any]] = [
        LocalWorkspace(workspace),
        RepoContext(),
        FileSystem(
            root_dir=workspace,
            tools=[
                "read_file",
                "write_file",
                "edit_file",
                "list_directory",
                "create_directory",
                "file_info",
                "list_files",
                "grep",
            ],
        ),
        Permissions(mode="read-only"),
    ]
    if shell_commands:
        caps += [
            Shell(
                allowed_commands=list(shell_commands),
                default_timeout=DEFAULT_TIMEOUT,
                max_output_chars=shell.MAX_OUTPUT,
            ),
            ShellGuard(commands=shell_commands),
        ]
    return caps
