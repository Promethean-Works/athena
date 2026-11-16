"""Code Mode (`code_mode.py`, M7 part D stage 3, item 7)."""

from pydantic_ai_harness import CodeMode

from athena.assistant.code_mode import code_mode_capabilities


def test_code_mode_is_off_by_default():
    assert code_mode_capabilities(False) == []


def test_code_mode_offers_code_mode_when_on():
    caps = code_mode_capabilities(True)
    assert len(caps) == 1
    assert isinstance(caps[0], CodeMode)
