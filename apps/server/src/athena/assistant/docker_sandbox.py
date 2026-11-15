"""Local Docker sandbox (docs/mvp-design.md §4.5, part D stage 3).

When "Docker sandbox" is on in Settings → AI, the assistant gets a `DockerSandbox`
capability: a local Docker (or Podman) container it can use as an isolated workspace
for commands and file edits. It's only offered when the `containers` capability is
ready, so it never appears on a host without a container engine.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai_harness.docker_sandbox import DockerSandbox

from athena.platform.capabilities import CapabilityManifest

DEFAULT_IMAGE = "python:3.13-slim"
"""Image for a new sandbox container; needs POSIX `sh` and the usual file utilities."""


def docker_sandbox_capabilities(
    enabled: bool, manifest: CapabilityManifest
) -> list[AbstractCapability[Any]]:
    """A `DockerSandbox` over the host's container engine, or none.

    Only offered when the setting is on and the `containers` capability is ready;
    otherwise the assistant has no sandbox.
    """
    if not enabled:
        return []
    containers = manifest.get("containers")
    if containers is None or containers.status != "ready":
        return []
    return [DockerSandbox(image=DEFAULT_IMAGE)]
