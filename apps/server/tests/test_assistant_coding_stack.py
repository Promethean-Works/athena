"""Coding stack (`coding_stack.py`, M7 part D stage 3)."""

from pydantic_ai_harness.repo_context import RepoContext

from athena.assistant.coding_stack import coding_stack_capabilities


def test_coding_stack_is_off_by_default(tmp_path):
    assert coding_stack_capabilities(False, tmp_path) == []


def test_coding_stack_offers_repo_context_when_on(tmp_path):
    caps = coding_stack_capabilities(True, tmp_path)
    assert len(caps) == 2
    assert any(isinstance(c, RepoContext) for c in caps)
