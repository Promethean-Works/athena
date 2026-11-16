"""Coding stack (`coding_stack.py`, M7 part D stage 3)."""

import sys

import pytest
from pydantic_ai_harness.filesystem import FileSystem
from pydantic_ai_harness.permissions import Permissions
from pydantic_ai_harness.repo_context import RepoContext
from pydantic_ai_harness.shell import Shell

from athena.assistant.coding_stack import coding_stack_capabilities
from athena.assistant.workspace import ShellGuard


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


@pytest.mark.skipif(sys.platform == "win32", reason="LocalWorkspace is POSIX-only")
def test_coding_stack_filesystem_has_grep_and_list_files(tmp_path):
    caps = coding_stack_capabilities(True, tmp_path)
    fs = next(c for c in caps if isinstance(c, FileSystem))
    assert "grep" in fs.tools
    assert "list_files" in fs.tools


@pytest.mark.skipif(sys.platform == "win32", reason="LocalWorkspace is POSIX-only")
def test_coding_stack_offers_guarded_shell_when_commands(tmp_path):
    caps = coding_stack_capabilities(True, tmp_path, ("cat", "ls"))
    assert any(isinstance(c, Shell) for c in caps)
    assert any(isinstance(c, ShellGuard) for c in caps)


@pytest.mark.skipif(sys.platform == "win32", reason="LocalWorkspace is POSIX-only")
def test_coding_stack_no_shell_without_commands(tmp_path):
    caps = coding_stack_capabilities(True, tmp_path, ())
    assert not any(isinstance(c, Shell) for c in caps)
    assert not any(isinstance(c, ShellGuard) for c in caps)


@pytest.mark.skipif(sys.platform == "win32", reason="LocalWorkspace is POSIX-only")
def test_coding_stack_no_coder(tmp_path):
    from pydantic_ai_harness.coder import Coder

    caps = coding_stack_capabilities(True, tmp_path, ("cat",))
    assert not any(isinstance(c, Coder) for c in caps)


@pytest.mark.skipif(sys.platform != "win32", reason="only Windows lacks a POSIX workspace")
def test_coding_stack_is_off_on_windows(tmp_path):
    assert coding_stack_capabilities(True, tmp_path, ("cat",)) == []
