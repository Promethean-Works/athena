"""Keeping long chats inside the model's context window (docs/design/assistant.md, part D
stage 1).

Before each model request, once the history passes `TRIGGER` of the window:

1. old tool results are blanked (the newest `KEEP_TOOL_PAIRS` stay), which costs nothing;
2. if that isn't enough, older messages are summarized by the chat's own model, keeping
   the newest `KEEP_RECENT` of the window as they are;
3. if summarizing fails (the model errors or writes nothing), the oldest messages are
   dropped instead, so the turn still goes out.

Each pass stops once the history is under `TARGET` of the window. The harness rewrites
the chat's stored history in place, which is what the model sees from then on. The admin
should still see the whole chat, so `TranscriptRecorder` notes every message the turn
added before compaction touched it, and `chat.py` keeps that full transcript next to the
history once a chat has been compacted.
"""

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.exceptions import (
    FallbackExceptionGroup,
    ModelAPIError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import ModelRequestContext
from pydantic_ai_harness import (
    ClearToolResults,
    FallbackCompaction,
    SlidingWindowCompaction,
    SummarizingCompaction,
    TieredCompaction,
)

TRIGGER = 0.75
"""Of the window. The rest is room for the reply and for the token estimate being off."""
TARGET = 0.5
KEEP_RECENT = 0.2
KEEP_TOOL_PAIRS = 4

SUMMARY_FAILURES = (
    ModelAPIError,
    FallbackExceptionGroup,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
"""When summarizing raises one of these, the oldest messages are dropped instead. A summary
that hits the turn's limits falls back too; the turn's own request then reports the limit."""


@dataclass
class TranscriptRecorder:
    """What one turn added to the chat, as it was before any compaction.

    `before` must run ahead of the compaction capability and `after` behind it. At each
    request, `before` takes the messages appended since the last request (the newest are
    always at the end, after whatever compaction left), and `after` remembers where the
    history ends once compaction is done.

    The turn's first message is found by its `run_id`, like pydantic-ai's own
    `new_messages()`: the stored count can't be used, because loading a compacted history
    merges the summary's request with the requests next to it.
    """

    start: int
    """Messages the run started with. Only used when no request was made (stopped first)."""
    added: list[ModelMessage] = field(default_factory=list)
    compacted: bool = False
    _mark: int | None = None
    _seen: list[ModelMessage] = field(default_factory=list)

    def before(self, messages: list[ModelMessage], run_id: str | None) -> None:
        if self._mark is None:
            start = next(
                (i for i, m in enumerate(messages) if run_id and m.run_id == run_id),
                min(self.start, len(messages)),
            )
        else:
            start = self._mark
        self.added.extend(messages[start:])
        self._seen = list(messages)

    def after(self, messages: list[ModelMessage]) -> None:
        if len(messages) != len(self._seen) or any(
            a is not b for a, b in zip(messages, self._seen, strict=False)
        ):
            self.compacted = True
        self._mark = len(messages)

    def finish(self, final: list[ModelMessage]) -> list[ModelMessage]:
        """Every message the turn added: those seen at requests, then what came after the
        last request (the final reply)."""
        start = min(self.start, len(final)) if self._mark is None else self._mark
        return [*self.added, *final[start:]]


@dataclass
class _Before(AbstractCapability[Any]):
    recorder: TranscriptRecorder

    async def before_model_request(
        self, ctx: RunContext[Any], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        self.recorder.before(ctx.messages, ctx.run_id)
        return request_context


@dataclass
class _After(AbstractCapability[Any]):
    recorder: TranscriptRecorder

    async def before_model_request(
        self, ctx: RunContext[Any], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        self.recorder.after(ctx.messages)
        return request_context


def strategy(window: int) -> FallbackCompaction[Any]:
    """The compaction capability for a model with `window` tokens of context."""
    keep = max(int(window * KEEP_RECENT), 512)
    return FallbackCompaction(
        fallback_chain=[
            TieredCompaction(
                tiers=[
                    ClearToolResults(max_tokens=1, keep_pairs=KEEP_TOOL_PAIRS),
                    SummarizingCompaction(max_messages=1, keep_tokens=keep),
                ],
                target_fraction=TARGET,
                context_window=window,
            ),
            SlidingWindowCompaction(max_messages=1, keep_tokens=keep),
        ],
        fallback_on=SUMMARY_FAILURES,
        max_fraction=TRIGGER,
        context_window=window,
    )


def compaction_capabilities(
    window: int, recorder: TranscriptRecorder
) -> list[AbstractCapability[Any]]:
    """The recorder around the compaction, in the order they must run."""
    return [_Before(recorder), strategy(window), _After(recorder)]
