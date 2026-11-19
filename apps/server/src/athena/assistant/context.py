"""How many tokens a chat's model accepts, so compaction knows when to shorten the history
(docs/mvp-design.md §4.5, part D stage 1).

The window is looked up once per turn, in this order:

1. The provider's own "Context window" field, for the kinds that have one (local servers
   and Azure deployments, whose names say nothing about the model).
2. What the provider reports: the size Ollama really runs the model at (`/api/ps`), or the
   window in the provider's model list (OpenRouter, Groq, Mistral, vLLM).
3. pydantic-ai's model profile, which fills it from `genai-prices` for well-known models.
4. A conservative guess: `UNKNOWN_LOCAL` for local servers, `UNKNOWN_CLOUD` otherwise.

Compacting too early costs one summary; guessing too high costs the whole request (or,
on Ollama, silently drops the start of the prompt).
"""

import logging
from dataclasses import dataclass
from typing import Literal

import httpx2
from pydantic_ai.models import Model
from pydantic_ai_harness.compaction import resolve_context_window

from athena.assistant.models_dev import get_models_dev_service
from athena.assistant.providers import (
    ModelCache,
    ProviderConfig,
    ProviderError,
    fetch_models,
)

log = logging.getLogger(__name__)

UNKNOWN_CLOUD = 128_000
UNKNOWN_LOCAL = 8_192
OLLAMA_UNLOADED = 4_096
"""Ollama's default context on most machines, used until the model is loaded and `/api/ps`
says. Its OpenAI-style API (which pydantic-ai uses) ignores a per-request `num_ctx`; the
admin raises it with `OLLAMA_CONTEXT_LENGTH` on the Ollama server."""

LISTS_WINDOWS = {"openrouter", "groq", "mistral"}
"""Native kinds whose model list can carry each model's window."""

PROBE_TIMEOUT = 5.0

Source = Literal["provider-field", "provider", "profile", "guess"]


@dataclass(frozen=True)
class ContextWindow:
    tokens: int
    source: Source


def field_value(cfg: ProviderConfig) -> int | None:
    raw = (cfg.get("context_window") or "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else None


async def window_for(
    cfg: ProviderConfig,
    model_id: str,
    model: Model,
    cache: ModelCache,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> ContextWindow:
    if (typed := field_value(cfg)) is not None:
        return ContextWindow(typed, "provider-field")
    reported = await _reported(cfg, model_id, cache, transport)
    if reported is not None:
        return ContextWindow(reported, "provider")
    if (known := resolve_context_window(model)) is not None:
        return ContextWindow(known, "profile")
    if cfg.kind.id == "ollama":
        return ContextWindow(OLLAMA_UNLOADED, "guess")
    local = cfg.kind.group == "local"
    return ContextWindow(UNKNOWN_LOCAL if local else UNKNOWN_CLOUD, "guess")


async def _reported(
    cfg: ProviderConfig,
    model_id: str,
    cache: ModelCache,
    transport: httpx2.AsyncBaseTransport | None,
) -> int | None:
    """The provider's own number, or None. Failures only cost the guess."""
    try:
        if cfg.kind.id == "ollama":
            return await _ollama_loaded(cfg, model_id, transport)
        if cfg.kind.id in LISTS_WINDOWS:
            models = cache.get(cfg.id)
            if models is None:
                models = await fetch_models(cfg, transport)
                cache.put(cfg.id, models)
            return next((m.context_window for m in models if m.id == model_id), None)

        # For dynamic providers from models.dev, check if they're OpenAI-compatible
        # and if their model list has the window
        service = get_models_dev_service()
        if service:
            entry = service.get_provider(cfg.kind.id)
            if entry and entry.is_openai_compatible:
                models = cache.get(cfg.id)
                if models is None:
                    models = await fetch_models(cfg, transport)
                    cache.put(cfg.id, models)
                return next((m.context_window for m in models if m.id == model_id), None)
    except (ProviderError, httpx2.HTTPError, ValueError, TypeError, AttributeError) as exc:
        log.info("couldn't read %s's context window: %s", cfg.name, exc)
    return None


async def _ollama_loaded(
    cfg: ProviderConfig, model_id: str, transport: httpx2.AsyncBaseTransport | None
) -> int | None:
    """The context Ollama runs the model with, while it's loaded."""
    base = (cfg.get("base_url") or "").rstrip("/")
    key = cfg.get("api_key")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    async with httpx2.AsyncClient(timeout=PROBE_TIMEOUT, transport=transport) as client:
        res = await client.get(f"{base}/api/ps", headers=headers)
        res.raise_for_status()
        names = {model_id, f"{model_id}:latest"}
        for m in res.json().get("models") or []:
            if m.get("name") in names or m.get("model") in names:
                size = m.get("context_length")
                return size if isinstance(size, int) and size > 0 else None
    return None
