"""Durable execution (`durable_execution.py`, M7 part D stage 3)."""

import asyncio
import socket

import pytest
from pgtask import Client, TaskRegistry
from pydantic_ai_harness.pgtask import PGTaskDurability

from athena.assistant.durable_execution import durable_execution_capabilities
from athena.assistant.turns import Turns


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


# -------------------------------------------------------------------- real Postgres

_DATABASE_URL = "postgresql://postgres:athena@localhost:5433/athena"


def _postgres_available() -> bool:
    try:
        with socket.create_connection(("localhost", 5433), timeout=2):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _postgres_available(), reason="Postgres not available on localhost:5433")
def test_pgtask_client_connects_to_real_postgres(tmp_path, monkeypatch):
    """The app wires a pgtask client and registry when the database URL is configured,
    and pgtask migrates its tables into the database."""
    monkeypatch.setenv("ATHENA_DURABLE_EXECUTION_DATABASE_URL", _DATABASE_URL)

    from fastapi.testclient import TestClient

    from athena.config import Settings
    from athena.main import create_app

    settings = Settings(data_dir=tmp_path / "data")
    app = create_app(settings)

    with TestClient(app):
        assert app.state.assistant_turns.pgtask_client is not None
        assert app.state.assistant_turns.pgtask_registry is not None

        # pgtask should have migrated its tables into the database during lifespan.
        async def check_migrate():
            client = await Client.connect(_DATABASE_URL)
            await client.migrate()

        asyncio.run(check_migrate())
