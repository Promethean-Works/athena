"""Browser agent (docs/design/assistant.md, part D stage 3).

When "Browser" is on in Settings → AI, the assistant gets a `browse_web` tool that
hands an open-ended web task to an autonomous
[browser-use](https://github.com/browser-use/browser-use) agent: it drives a real
Chromium (navigating, reading, clicking, extracting) and returns a text result.

The `pydantic_ai_harness.browser_use` module imports `browser-use`, whose current
release pins `google-genai==1.65.0` and conflicts with `pydantic-ai-slim[google]>=2.68.0`
(`google-genai>=2.30.0`). So the import is lazy: until the harness publishes a
`browser-use` extra compatible with `pydantic-ai-slim>=2.68.0`, the setting is
accepted but no tool is offered.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai.capabilities import AbstractCapability


def _browser_use_capability() -> AbstractCapability[Any] | None:
    """Build the `BrowserUse` capability, or None when browser-use isn't installable."""
    try:
        from pydantic_ai_harness.browser_use import BrowserUse
    except ImportError:
        return None
    return BrowserUse()


def browser_use_capabilities(enabled: bool) -> list[AbstractCapability[Any]]:
    """The `browse_web` tool, or none when the setting is off or browser-use is missing."""
    if not enabled:
        return []
    capability = _browser_use_capability()
    return [capability] if capability is not None else []
