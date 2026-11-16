"""Code Mode (docs/mvp-design.md §4.5, part D stage 3, item 7).

When "Code mode" is on in Settings → AI, the assistant gets the harness `CodeMode`
capability: read-only tools are wrapped behind a single `run_code` tool so the model
can write Python that loops, branches, aggregates, and parallelizes multiple tool calls
inside a Monty sandbox. Approval-gated tools stay as regular deferred calls needing the
admin's Approve/Deny card.

Code runs in a restricted Python subset with no third-party imports. Read-only tools are
tagged with `code_mode=True` in `assistant/tools.py` so only they move behind `run_code`;
change tools remain regular tool calls that go through approval cards.
"""

from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai_harness import CodeMode


def code_mode_capabilities(enabled: bool) -> list[AbstractCapability[Any]]:
    """A `CodeMode` capability, or none when the setting is off.

    `CodeMode(tools={'code_mode': True})` wraps only read-only tools (those tagged
    with `code_mode=True` metadata in `assistant/tools.py`) behind `run_code`.
    Approval-gated tools stay as regular deferred calls.
    """
    if not enabled:
        return []
    return [CodeMode(tools={"code_mode": True})]
