"""Coding stack (docs/mvp-design.md §4.5, part D stage 3, item 7).

When "Coding stack" is on in Settings → AI, the assistant gets
coding-assistant capabilities in `<data-dir>/assistant/code-workspace`:

- `RepoContext` loads AGENTS.md / CLAUDE.md instruction files into each
  reply's instructions (read-only, no approval).
- `FileSystem` gives `read_file`, `write_file`, `edit_file`,
  `list_directory`, `create_directory` and friends, bounded to the
  code-workspace. Writes go through an Approve/Deny card like the shell,
  via the harness `Permissions` in read-only mode; reads run free.
- `Coder` (the harness combined capability) adds coding-specific guidance,
  `grep`/`list_files` search tools, a persistent `shell` tool, and result
  truncation (ClearToolResults / ToolOutputLimits). Its shell is
  **unrestricted** — it does not go through Athena's shell allowlist or
  approval cards — so enabling the coding stack also gives the model a way
  to run arbitrary commands in the workspace. This is a known tension with
  `ShellGuard` (see `assistant/workspace.py`) and is resolved by the
  deferred-flow auto-approve follow-up.

`LocalWorkspace` is POSIX-only (it raises on Windows, with or without WSL),
so the whole stack is only offered on POSIX hosts. The workspace is created
on first use and holds only what the admin puts there.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic_ai.capabilities import AbstractCapability, LocalWorkspace
from pydantic_ai_harness.coder import Coder
from pydantic_ai_harness.filesystem import FileSystem
from pydantic_ai_harness.permissions import Permissions
from pydantic_ai_harness.repo_context import RepoContext


def coding_stack_capabilities(enabled: bool, data_dir: Path) -> list[AbstractCapability[Any]]:
    """Coding-assistant capabilities, or none when the setting is off or no
    POSIX workspace is available.

    `LocalWorkspace` anchors the run at `<data-dir>/assistant/code-workspace`
    (created on first use). `RepoContext` reads instruction files from it and
    `FileSystem` bounds every file operation to it, so the host outside the
    workspace is unaffected. `Permissions` (read-only mode) makes the model
    ask before each write, so `write_file`, `edit_file` and
    `create_directory` show an Approve/Deny card while reads run freely.

    `Coder` is bound on the agent (not passed to `run()`) so its `delegate_task`
    works with Athena's own `SubAgents`. It's added with `repo_context=False`,
    `sub_agents=False` and `caching=False` because Athena already wires
    `RepoContext`, `SubAgents` (via `assistant/delegation.py`) and `Caching()`
    on the agent — Coder then contributes coding-specific guidance, search
    tools and result truncation without duplicating them.
    """
    if not enabled:
        return []
    if os.name != "posix":
        return []  # LocalWorkspace is POSIX-only; Windows uses PowerShell instead
    workspace = data_dir / "assistant" / "code-workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return [
        LocalWorkspace(workspace),
        RepoContext(),
        FileSystem(root_dir=workspace),
        Permissions(mode="read-only"),
        Coder(
            instructions=(
                "Work inside the code-workspace only. Prefer reads and edits over "
                "rewrites, run tests or linting before declaring a change done, and "
                "never commit or push — ask the admin instead."
            ),
            repo_context=False,
            sub_agents=False,
            caching=False,
        ),
    ]
