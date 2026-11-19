"""Step persistence, conversation search and media externalization (docs/design/assistant.md,
part D stage 2).

- `StepPersistence` saves each turn's full history to `<data-dir>/assistant/steps.db`
  (`SqliteStepStore`, one file). Compaction may blank or summarize old messages in the live
  context, but the persisted snapshots keep the originals, so they can be recalled later.
- `ConversationSearch` (scope `conversation`) gives the model `search_conversation_history`,
  a BM25 tool that recalls exact details from earlier turns of this chat — including what
  compaction dropped — and from past runs in the same conversation.
- `media`: the step store externalizes large payloads (big tool returns, long text) into a
  `media` table inside the same database (`SqliteMediaStore`, 64 KiB threshold), so snapshots
  stay small and identical bytes are stored once. This is the "media (stores for large parts)"
  half of stage 2; it comes free with the store and needs no separate capability.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai_harness.conversation_search import ConversationSearch, SnapshotHistorySource
from pydantic_ai_harness.step_persistence import SqliteStepStore, StepPersistence

STEPS_DB = "steps.db"


def steps_db(data_dir: Path) -> Path:
    return data_dir / "assistant" / STEPS_DB


def persistence_capabilities(data_dir: Path) -> list[AbstractCapability[Any]]:
    """Persist each turn and let the model search this conversation's persisted history.

    Both capabilities share one `SqliteStepStore`, which also holds the externalized media
    (`SqliteMediaStore`, a sibling `media` table in the same file).
    """
    store = SqliteStepStore(database=steps_db(data_dir))
    return [
        StepPersistence(store=store),
        ConversationSearch(
            SnapshotHistorySource(store),
            scope="conversation",
            add_instructions=False,
        ),
    ]
