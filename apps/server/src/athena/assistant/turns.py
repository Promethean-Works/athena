"""Running assistant turns, by conversation id.

Kept apart from `chat` so the app can create `Turns` at startup without importing
pydantic-ai: `chat` (and the whole agent stack) loads when the first turn starts.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

if TYPE_CHECKING:
    from pgtask import Client, Task, TaskRegistry
    from pydantic_ai import CancellationToken
    from pydantic_ai.models import Model

    from athena.assistant.chat import Resume, Window

log = logging.getLogger(__name__)


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _new_token() -> CancellationToken:
    from pydantic_ai import CancellationToken

    return CancellationToken()


@dataclass
class Turn:
    """One running reply. Events go to whoever is listening; the task saves the result."""

    conversation_id: str
    token: CancellationToken = field(default_factory=_new_token)
    queue: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)
    task: asyncio.Task[None] | None = None
    name_with: tuple[Model, str, str] | None = None
    """Set when the turn saved: the title model, the first message and the stand-in title."""

    def emit(self, event: str, data: Any) -> None:
        self.queue.put_nowait(sse(event, data))

    async def stream(self) -> AsyncIterator[str]:
        while (item := await self.queue.get()) is not None:
            yield item


class Turns:
    """Running turns by conversation id: one at a time per chat."""

    def __init__(self) -> None:
        self._turns: dict[str, Turn] = {}
        # Set by `create_app` when a pgtask/Postgres database URL is configured: turns are
        # then enqueued as pgtask tasks so they're durable (checkpointed) across crashes.
        self.pgtask_client: Client | None = None
        self.pgtask_registry: TaskRegistry | None = None
        self._pgtask_executors: dict[str, Callable[[Task], Awaitable[None]]] = {}
        self._titles: dict[str, asyncio.Task[None]] = {}
        """Titles being generated, by conversation id: they run after their turn ends."""

    def naming(self, conversation_id: str) -> bool:
        """Whether a title model is still naming this chat."""
        task = self._titles.get(conversation_id)
        return task is not None and not task.done()

    def _name(self, app: FastAPI, conversation_id: str, job: tuple[Model, str, str]) -> None:
        from athena.assistant import chat

        model, text, stand_in = job

        async def run() -> None:
            try:
                generated = await asyncio.wait_for(
                    chat.generate_title(model, text), chat.TITLE_TIMEOUT
                )
                if generated:
                    chat.rename(app, conversation_id, stand_in, generated)
            except Exception as exc:  # the first line stays the title
                log.info("couldn't generate a chat title: %s", chat.readable(exc))
            finally:
                self._titles.pop(conversation_id, None)

        self._titles[conversation_id] = asyncio.create_task(run())

    def get(self, conversation_id: str) -> Turn | None:
        turn = self._turns.get(conversation_id)
        if turn and turn.task and turn.task.done():
            self._turns.pop(conversation_id, None)
            return None
        return turn

    def register_pgtask_handlers(self) -> None:
        """Register the pgtask task that runs each durable assistant turn.

        The handler runs inside a pgtask task, so `current_task_steps()` is not None and
        the `PGTaskDurability` capability checkpoints every model request and tool call.
        """
        if self.pgtask_registry is None:
            return

        @self.pgtask_registry.task("athena.assistant.turn")
        async def handle_turn(task: Task, payload: dict[str, Any]) -> None:
            cid = payload.get("conversation_id") if isinstance(payload, dict) else None
            executor = self._pgtask_executors.pop(cid, None) if cid else None
            if executor is None:
                log.warning("pgtask turn %s has no executor to run", task.id)
                return
            await executor(task)

    def _run_durable(self, conversation_id: str) -> Awaitable[None]:
        """Enqueue this turn as a pgtask task and wait for it to complete.

        `turn.task` is this awaitable, so stopping/shutdown can cancel it and the turn
        stays "live" while its events stream to the browser.
        """
        from pgtask import EnqueueRequest

        client = self.pgtask_client
        assert client is not None

        async def run() -> None:
            handle = await client.enqueue(
                EnqueueRequest(
                    task_name="athena.assistant.turn",
                    payload={"conversation_id": conversation_id},
                )
            )
            try:
                await handle.result()
            finally:
                self._pgtask_executors.pop(conversation_id, None)

        return run()

    def start(
        self,
        conversation_id: str,
        *,
        app: FastAPI,
        model: Model,
        text: str | None,
        spend_limit: float | None,
        user_id: int,
        window: Window,
        resume: Resume | None = None,
        title_model: Model | None = None,
        advisor_model: Model | None = None,
        review_model: Model | None = None,
        durable: bool = False,
    ) -> Turn:
        """Start one turn. When `durable` and a pgtask client are configured, the turn is
        run inside a pgtask task (checkpointed, resumable); otherwise it runs inline."""
        from athena.assistant import chat

        turn = Turn(conversation_id)

        async def body() -> None:
            try:
                await chat.run_turn(
                    turn,
                    app=app,
                    model=model,
                    text=text,
                    resume=resume,
                    spend_limit=spend_limit,
                    user_id=user_id,
                    title_model=title_model,
                    advisor_model=advisor_model,
                    review_model=review_model,
                    window=window,
                )
            except Exception:
                log.exception("assistant turn crashed")
                turn.emit("error", {"message": "The assistant failed. See the server log."})
                turn.emit("done", {})
            finally:
                turn.queue.put_nowait(None)
                self._turns.pop(conversation_id, None)
                if turn.name_with is not None:
                    self._name(app, conversation_id, turn.name_with)

        self._turns[conversation_id] = turn
        if durable and self.pgtask_client is not None and self.pgtask_registry is not None:
            self._pgtask_executors[conversation_id] = body
            turn.task = asyncio.create_task(self._run_durable(conversation_id))
        else:
            turn.task = asyncio.create_task(body())
        return turn

    async def stop_all(self) -> None:
        for title in list(self._titles.values()):
            title.cancel()
        for turn in list(self._turns.values()):
            turn.token.cancel()
            if turn.task:
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await asyncio.wait_for(turn.task, 5)
