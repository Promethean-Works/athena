"""Web research (docs/design/assistant.md, part D stage 3).

When "Web research" is on in Settings → AI, the assistant can search the web
with Exa (`web_search`) and read pages (`get_page`). The Exa API key is read
from the `EXA_API_KEY` environment variable; the setting only gates whether the
tools are offered to the model.
"""

from __future__ import annotations

import os
from typing import Any

from exa_py import AsyncExa
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai_harness.exa import ExaSearch

EXA_API_KEY_ENV = "EXA_API_KEY"
"""Environment variable holding the Exa API key."""


def web_research_capabilities(
    enabled: bool, api_key: str | None = None
) -> list[AbstractCapability[Any]]:
    """The Exa web research tools, or none when the setting is off.

    `api_key` defaults to the `EXA_API_KEY` environment variable. Without a key
    the tools are still offered, but any search fails with a clear error until
    the key is set.
    """
    if not enabled:
        return []
    key = api_key or os.environ.get(EXA_API_KEY_ENV)
    client = AsyncExa(api_key=key) if key else None
    return [ExaSearch(client=client)]
