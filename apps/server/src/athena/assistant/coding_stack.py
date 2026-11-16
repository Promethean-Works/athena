"""Coding stack (docs/mvp-design.md §4.5, part D stage 3, item 7).

When "Coding stack" is on in Settings → AI, the assistant gets read-only
coding-assistant capabilities: `RepoContext` loads AGENTS.md / CLAUDE.md
instruction files from a code-workspace directory into each reply's
instructions.

`RepoContext` needs a POSIX workspace (`LocalWorkspace` is POSIX-only, and
Windows without WSL uses PowerShell instead), so it's only offered when the
assistant shell's provider is `posix` or `wsl`. Turns run against
`<data-dir>/assistant/code-workspace` (created on first use). Nothing mutates
files here, so nothing needs approval; file-system write/edit/delete
capabilities (FileSystem, code_mode, …) join later, each with its own
Approve/Deny card like the shell.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic_ai.capabilities import AbstractCapability, LocalWorkspace
from pydantic_ai_harness.repo_context import RepoContext

from athena.assistant.tools import shell_provider


def coding_stack_capabilities(
    enabled: bool, manifest: Any, data_dir: Path
) -> list[AbstractCapability[Any]]:
    """Read-only coding-assistant capabilities, or none when the setting is off
    or no POSIX workspace is available.

    `RepoContext` needs a workspace, so runs get one rooted at
    `<data-dir>/assistant/code-workspace`; it's created on first use. The
    workspace holds only what the admin puts there, and RepoContext only reads
    instruction files from it, so the host is unaffected.
    """
    if not enabled:
        return []
    if shell_provider(manifest) not in ("posix", "wsl"):
        return []  # LocalWorkspace is POSIX-only; Windows without WSL uses PowerShell
    workspace = data_dir / "assistant" / "code-workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return [
        LocalWorkspace(workspace),
        RepoContext(),
    ]
