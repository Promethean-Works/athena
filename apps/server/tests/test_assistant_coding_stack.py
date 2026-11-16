"""Coding stack (`coding_stack.py`, M7 part D stage 3)."""

import sys

import pytest
from pydantic_ai_harness.filesystem import FileSystem
from pydantic_ai_harness.permissions import Permissions
from pydantic_ai_harness.repo_context import RepoContext

from athena.assistant.coding_stack import coding_stack_capabilities


def test_coding_stack_is_off_by_default(tmp_path):
    assert coding_stack_capabilities(False, tmp_path) == []


@pytest.mark.skipif(sys.platform == "win32", reason="LocalWorkspace is POSIX-only")
def test_coding_stack_offers_repo_context_when_on(tmp_path):
    caps = coding_stack_capabilities(True, tmp_path)
    assert any(isinstance(c, RepoContext) for c in caps)


@pytest.mark.skipif(sys.platform == "win32", reason="LocalWorkspace is POSIX-only")
def test_coding_stack_offers_filesystem_and_permissions_when_on(tmp_path):
    caps = coding_stack_capabilities(True, tmp_path)
    assert any(isinstance(c, FileSystem) for c in caps)
    assert any(isinstance(c, Permissions) for c in caps)


@pytest.mark.skipif(sys.platform != "win32", reason="only Windows lacks a POSIX workspace")
def test_coding_stack_is_off_on_windows(tmp_path):
    assert coding_stack_capabilities(True, tmp_path) == []
