"""Durable execution (docs/mvp-design.md §4.5, part D stage 3, item 6).

When "Durable execution" is on in Settings → AI, the assistant gets a `PGTaskDurability`
capability: every model request and tool call is checkpointed as a pgtask step, so a
run interrupted mid-turn resumes from the last completed step instead of repeating the
work already paid for.

The capability is transparent outside a pgtask task: turns are durable only when the
server runs them inside pgtask tasks against a Postgres database (run Postgres as a
compose app on this server and point pgtask at it). The setting only turns the
capability on; wiring turns into pgtask tasks is the next step.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai_harness.pgtask import PGTaskDurability


def durable_execution_capabilities(
    enabled: bool,
) -> list[AbstractCapability[Any]]:
    """A `PGTaskDurability` capability, or none when the setting is off.

    Only offered when the setting is on. Outside a pgtask task the capability does
    nothing, so a host without pgtask + Postgres is unaffected.
    """
    if not enabled:
        return []
    return [PGTaskDurability(name="athena")]
