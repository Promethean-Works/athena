"""Local Docker sandbox (`docker_sandbox.py`, M7 part D stage 3)."""

from datetime import UTC, datetime

from pydantic_ai_harness.docker_container import DockerContainer

from athena.assistant.docker_sandbox import DEFAULT_IMAGE, docker_sandbox_capabilities
from athena.platform.capabilities import Capability, CapabilityManifest


def manifest(*caps: tuple[str, str]) -> CapabilityManifest:
    return CapabilityManifest(
        os="linux",
        os_version="Test",
        arch="x86_64",
        detected_at=datetime.now(UTC),
        capabilities=[
            Capability(id=cid, label=cid, status=status, provider="test") for cid, status in caps
        ],
    )


def test_sandbox_is_off_by_default():
    assert docker_sandbox_capabilities(False, manifest(("containers", "ready"))) == []


def test_sandbox_needs_a_ready_container_engine():
    for status in ("missing", "stopped", "unsupported", "needs_privilege"):
        assert docker_sandbox_capabilities(True, manifest(("containers", status))) == []
    assert docker_sandbox_capabilities(True, manifest()) == []


def test_sandbox_offers_docker_sandbox_when_containers_ready():
    caps = docker_sandbox_capabilities(True, manifest(("containers", "ready")))
    assert len(caps) == 1
    sandbox = caps[0]
    assert isinstance(sandbox, DockerContainer)
    assert sandbox.image == DEFAULT_IMAGE
