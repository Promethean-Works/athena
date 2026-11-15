"""Harness capabilities that keep every assistant run on track (docs/mvp-design.md §4.5,
part D stage 1). They're always on and have no settings.

- `RepairToolArguments`: fixes the malformed JSON small local models write for tool calls
  (trailing commas, single quotes, a missing brace) before validation.
- `DetectLoops`: when the model repeats the same call or result, the next request tells it
  to change approach. A nudge, not a stop: the per-turn request and tool-call limits are
  the hard stop.
- `ToolOutputLimits`: a tool result bigger than `SPILL_OVER` characters is saved to
  `<data-dir>/assistant/tool-output` and the model gets a preview plus a handle it can
  read back with `read_tool_result`. Athena's own tools cap their output below that; the
  shell keeps up to `shell.MAX_OUTPUT` characters, so a long command output reaches the model
  as a preview and stays whole on disk instead of being cut.
"""

from datetime import timedelta
from pathlib import Path
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai_harness import DetectLoops, ToolOutputLimits
from pydantic_ai_harness.repair_tool_arguments import RepairToolArguments
from pydantic_ai_harness.tool_output_limits import Band, LocalFileStore, Spill, Truncate

SPILL_OVER = 24_000
"""Characters. Above the 20,000 that `app_logs` and `read_text_file` return at most."""

SPILL_KEPT = timedelta(days=7)
"""How long spilled results stay readable; older files are pruned after a later write."""


def spill_dir(data_dir: Path) -> Path:
    return data_dir / "assistant" / "tool-output"


def robustness_capabilities(data_dir: Path) -> list[AbstractCapability[Any]]:
    return [
        RepairToolArguments(),
        DetectLoops(),
        ToolOutputLimits(
            bands=[Band(over=SPILL_OVER, action=Spill(then=Truncate()))],
            store=LocalFileStore(base_dir=spill_dir(data_dir), cleanup_after=SPILL_KEPT),
        ),
    ]
