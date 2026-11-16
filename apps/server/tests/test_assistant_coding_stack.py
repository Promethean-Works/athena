"""Coding stack (`coding_stack.py`, M7 part D stage 3)."""

from datetime import UTC, datetime

from pydantic_ai_harness.repo_context import RepoContext

from athena.assistant.coding_stack import coding_stack_capabilities
from athena.platform.capabilities import Capability, CapabilityManifest


def manifest(*caps: tuple[str, str, str | None]) -> CapabilityManifest:
    return CapabilityManifest(
        os="linux",
        os_version="Test",
        arch="x86_64",
        detected_at=datetime.now(UTC),
        capabilities=[
            Capability(id=cid, label=cid, status=status, provider=provider)
            for cid, status, provider in caps
        ],
    )


def test_coding_stack_is_off_by_default(tmp_path):
    assert coding_stack_capabilities(False, manifest(), tmp_path) == []


def test_coding_stack_offers_repo_context_when_on(tmp_path):
    caps = coding_stack_capabilities(
        True, manifest(("assistant.shell", "ready", "posix")), tmp_path
    )
    assert any(isinstance(c, RepoContext) for c in caps)


def test_coding_stack_needs_a_posix_workspace(tmp_path):
    # `LocalWorkspace` is POSIX-only; Windows without WSL uses PowerShell.
    for provider in ("powershell", None):
        caps = coding_stack_capabilities(
            True, manifest(("assistant.shell", "ready", provider)), tmp_path
        )
        assert caps == []
    assert coding_stack_capabilities(True, manifest(), tmp_path) == []
