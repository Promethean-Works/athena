"""Durable execution (`durable_execution.py`, M7 part D stage 3)."""

import asyncio

from pgtask import TaskRegistry
from pydantic_ai_harness.pgtask import PGTaskDurability

from athena.assistant.chat import Turns
from athena.assistant.durable_execution import durable_execution_capabilities


class _FakeTask:
    """A minimal stand-in for a pgtask `Task`: the handler only reads `.id` on the error path."""

    def __init__(self, task_id: str = "t1") -> None:
        self.id = task_id


def test_durable_execution_is_off_by_default():
    assert durable_execution_capabilities(False) == []


def test_durable_execution_offers_pgtask_durability_when_on():
    caps = durable_execution_capabilities(True)
    assert len(caps) == 1
    assert isinstance(caps[0], PGTaskDurability)
    assert caps[0].name == "athena"


def test_register_pgtask_handlers_registers_one_task():
    turns = Turns()
    turns.pgtask_registry = TaskRegistry(queue_name="athena-assistant")
    turns.register_pgtask_handlers()
    defs = turns.pgtask_registry.definitions
    assert len(defs) == 1
    assert defs[0].name == "athena.assistant.turn"


def test_pgtask_handler_runs_the_registered_executor():
    turns = Turns()
    turns.pgtask_registry = TaskRegistry(queue_name="athena-assistant")
    turns.register_pgtask_handlers()

    ran: list[bool] = []

    async def executor(task: object) -> None:
        ran.append(True)

    turns._pgtask_executors["conv-1"] = executor
    handler = turns.pgtask_registry.definitions[0].handler
    asyncio.run(handler(_FakeTask(), {"conversation_id": "conv-1"}))

    assert ran == [True]
    # The executor is consumed (popped) by the handler.
    assert "conv-1" not in turns._pgtask_executors


def test_pgtask_handler_without_executor_is_a_noop():
    turns = Turns()
    turns.pgtask_registry = TaskRegistry(queue_name="athena-assistant")
    turns.register_pgtask_handlers()
    handler = turns.pgtask_registry.definitions[0].handler
    # Should not raise even though nothing was registered.
    asyncio.run(handler(_FakeTask(), {"conversation_id": "missing"}))
