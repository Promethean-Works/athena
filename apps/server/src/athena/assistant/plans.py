"""The assistant's plan for a chat (docs/design/assistant.md, part D stage 2).

The harness `Planning` with only its `write_plan` tool: the model restates the whole plan to
add a step or change a status, so there are no step ids to track (or guess) and the tool
schemas cost ~3,000 characters per request instead of ~6,500 for all six plan tools. Each
chat has its own plan in `<data-dir>/assistant/plans.db` (`SqlitePlanStore`, session
`conv-<id>`), so it lasts between turns and after compaction: when `write_plan`'s results are
gone from the model's view, the harness adds the plan back from the store. The chat UI shows
the plan as a checklist above the prompt bar, read from the same store, and hides
`write_plan`'s own rows.
"""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai_harness import Planning
from pydantic_ai_harness.planning import SqlitePlanStore

PLAN_TOOL = "write_plan"
"""The one plan tool; a `plan` event follows each call."""


class PlanStep(BaseModel):
    id: str
    content: str
    status: Literal["pending", "in_progress", "completed", "cancelled", "blocked"]
    active_form: str = ""
    """What the step says while it runs ("Installing Jellyfin")."""


def plans_db(data_dir: Path) -> Path:
    return data_dir / "assistant" / "plans.db"


def plan_store(data_dir: Path, conversation_id: str) -> SqlitePlanStore:
    db = plans_db(data_dir)
    db.parent.mkdir(parents=True, exist_ok=True)
    return SqlitePlanStore(str(db), session=f"conv-{conversation_id}")


async def plan_of(data_dir: Path, conversation_id: str) -> list[PlanStep]:
    """The chat's plan, or nothing before the model has written one."""
    if not plans_db(data_dir).exists():
        return []
    return steps(await plan_store(data_dir, conversation_id).get_items())


def steps(items: list[Any]) -> list[PlanStep]:
    return [
        PlanStep(id=i.id, content=i.content, status=i.status.value, active_form=i.active_form or "")
        for i in items
    ]


async def delete_plan(data_dir: Path, conversation_id: str) -> None:
    if plans_db(data_dir).exists():
        await plan_store(data_dir, conversation_id).set_items([])


def planning_capabilities(data_dir: Path, conversation_id: str) -> list[AbstractCapability[Any]]:
    # One tool and no subtasks: every tool schema is paid for on every request, and small
    # local models run in small contexts.
    return [Planning(store=plan_store(data_dir, conversation_id), tools=[PLAN_TOOL])]
