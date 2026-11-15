"""Double-checked answers (docs/mvp-design.md §4.5, part D stage 2).

When "Double-check answers" is on in Settings → AI, the harness `RefineOutput` sends the
model back once per run to review its answer and write it again, revised. It costs at least
one more model request per turn, which is why it's off by default. A run that pauses for an
approval or a question isn't reviewed (the harness skips `DeferredToolRequests`).

The first answer stays in the history. The stream sends a `draft` event when the review
starts, and `chat.ui_messages` marks the reply's text before the review instruction as a
draft, so the UI can fold it away and show only the revised answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability, AgentNode, NodeResult
from pydantic_ai.messages import ModelRequest, SystemPromptPart
from pydantic_ai_harness import RefineOutput

from athena.assistant.tools import Deps

REVIEW_ORIGIN = "pydantic-ai-harness.refine_output.v1"
"""How the harness tags the system prompt part that starts a review round."""

REVIEW_INSTRUCTIONS = (
    "Review your last answer against the admin's request. Look for mistakes, gaps, guesses "
    "and anything unclear. To check a fact, use a read-only tool; don't start an action or "
    "ask the admin anything during the review. Then give the complete answer again, revised "
    "(or unchanged if it was right). Leave the review itself out of the answer."
)


@dataclass(kw_only=True)
class DoubleCheck(RefineOutput[Deps]):
    """`RefineOutput` that tells the stream when a review round starts."""

    async def after_node_run(
        self, ctx: RunContext[Deps], *, node: AgentNode[Deps], result: NodeResult[Deps]
    ) -> NodeResult[Deps]:
        before = self._rounds_started
        result = await super().after_node_run(ctx, node=node, result=result)
        if self._rounds_started > before:
            ctx.deps.emit("draft", {})
        return result


def review_capabilities(enabled: bool) -> list[AbstractCapability[Any]]:
    return [DoubleCheck(rounds=1, instructions=REVIEW_INSTRUCTIONS)] if enabled else []


def starts_review(msg: ModelRequest) -> bool:
    """A request carrying the review instruction: the reply's text before it is a draft."""
    return any(
        isinstance(part, SystemPromptPart) and (part.metadata or {}).get("origin") == REVIEW_ORIGIN
        for part in msg.parts
    )
