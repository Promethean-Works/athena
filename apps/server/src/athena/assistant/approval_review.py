"""Second-model review of action approvals (docs/mvp-design.md §4.5, part D stage 3).

When "Review tool calls" is on in Settings → AI, an `ApprovalReviewer` asks a second model
about each action awaiting the admin's Approve/Deny card. Low-risk calls are auto-approved
and run in the same step; risky or unclear ones are left for the person. It never denies a
call and never runs one itself — it only decides which approvals the admin no longer sees.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.models import Model
from pydantic_ai_harness.approval_reviewer import ApprovalReviewer

from athena.assistant import actions

REVIEW_QUESTION = (
    "Would running this tool change, delete, install, or expose something on this "
    "server that the admin hasn't clearly asked about? Answer no only for clearly safe, "
    "routine calls; answer yes or unsure for anything destructive, costly, or revealing."
)
"""The risk question the review model answers per approval: `no` auto-approves it."""


def review_capabilities(review_model: Model | None, enabled: bool) -> list[AbstractCapability[Any]]:
    """An `ApprovalReviewer` over the action tools, or none when the setting is off or the
    model is unavailable."""
    if not enabled or review_model is None:
        return []
    tools = [*actions.NAMES, *actions.SHELL_TOOLS]
    return [
        ApprovalReviewer(
            review_model,
            question=REVIEW_QUESTION,
            tools=tools,
        )
    ]
