"""Durable execution (`durable_execution.py`, M7 part D stage 3)."""

from pydantic_ai_harness.pgtask import PGTaskDurability

from athena.assistant.durable_execution import durable_execution_capabilities


def test_durable_execution_is_off_by_default():
    assert durable_execution_capabilities(False) == []


def test_durable_execution_offers_pgtask_durability_when_on():
    caps = durable_execution_capabilities(True)
    assert len(caps) == 1
    assert isinstance(caps[0], PGTaskDurability)
    assert caps[0].name == "athena"
