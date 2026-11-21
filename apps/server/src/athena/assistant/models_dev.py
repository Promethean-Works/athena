"""Models.dev integration: fetch, cache, and serve provider/model data from models.dev.

This module replaces hardcoded provider lists with dynamic data from models.dev,
cached in the database for fast access and offline resilience.
"""

import asyncio
import json
import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx2
from sqlmodel import Session, col, select

from athena.assistant.kinds import BY_ID, LOCAL_KINDS, NATIVE_KINDS, KindField, ProviderKind
from athena.db.models import ModelsDevCache

log = logging.getLogger(__name__)

MODELS_DEV_API = "https://models.dev/api.json"
CACHE_TTL = timedelta(hours=24)  # Cache for 24 hours
FETCH_TIMEOUT = 30.0

# models.dev ids with their own pydantic-ai provider (kinds.py NATIVE_KINDS).
NATIVE_PROVIDERS = {k.id for k in NATIVE_KINDS}

# AI SDK packages whose API pydantic-ai speaks at any base URL.
OPENAI_SDKS = {"@ai-sdk/openai-compatible", "@ai-sdk/openai"}
ANTHROPIC_SDKS = {"@ai-sdk/anthropic"}

# Providers models.dev lists with their own AI SDK package and no `api` URL, whose
# OpenAI-compatible endpoint is documented (the same defaults pydantic-ai's own
# providers use).
KNOWN_BASE_URLS = {
    "cerebras": "https://api.cerebras.ai/v1",
    "togetherai": "https://api.together.xyz/v1",
    "deepinfra": "https://api.deepinfra.com/v1/openai",
    "perplexity": "https://api.perplexity.ai",
    "vercel": "https://ai-gateway.vercel.sh/v1",
    "venice": "https://api.venice.ai/api/v1",
}

ApiStyle = Literal["native", "openai", "anthropic"]


def api_style(provider_id: str, npm: str | None, api_url: str | None) -> ApiStyle | None:
    """How pydantic-ai talks to a models.dev provider, or None when it can't (its own SDK
    and no OpenAI- or Anthropic-compatible endpoint, e.g. Google Vertex or watsonx)."""
    if provider_id in NATIVE_PROVIDERS:
        return "native"
    if not api_url:
        return None
    if npm in OPENAI_SDKS or npm == "@openrouter/ai-sdk-provider":
        return "openai"
    if npm in ANTHROPIC_SDKS:
        return "anthropic"
    if provider_id in KNOWN_BASE_URLS:
        return "openai"
    return None


def _is_local_url(url: str) -> bool:
    return urlsplit(url).hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1")


@dataclass
class ModelsDevProvider:
    """Normalized provider data from models.dev."""

    id: str
    name: str
    models: dict[str, Any]
    env: list[str]
    api: str
    npm: str
    doc: str

    @classmethod
    def from_json(cls, provider_id: str, data: dict[str, Any]) -> "ModelsDevProvider":
        return cls(
            id=provider_id,
            name=data.get("name", provider_id),
            models=data.get("models", {}),
            env=data.get("env", []),
            api=data.get("api", ""),
            npm=data.get("npm", ""),
            doc=data.get("doc", ""),
        )

    def is_openai_compatible(self) -> bool:
        """Whether pydantic-ai reaches it through its OpenAI-compatible model."""
        return api_style(self.id, self.npm, self.get_base_url()) == "openai"

    def get_base_url(self) -> str | None:
        """The API's base URL: models.dev's `api`, or a documented one (KNOWN_BASE_URLS)."""
        if not self.api:
            return KNOWN_BASE_URLS.get(self.id)
        if self.api:
            url = self.api.rstrip("/")
            for suffix in ["/models", "/v1/models", "/v2/models", "/api/v1/models"]:
                if url.endswith(suffix):
                    url = url[: -len(suffix)]
                    break
            return url
        return None


def _aware(value: datetime) -> datetime:
    """SQLite hands back naive datetimes even for timezone=True columns; they're UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _env_vars(entry: ModelsDevCache) -> list[str]:
    raw = entry.env_vars
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    return [str(v) for v in raw or []]


def style_of(entry: ModelsDevCache) -> ApiStyle | None:
    return api_style(entry.provider_id, entry.npm_package, entry.api_url)


def kind_from_entry(entry: ModelsDevCache) -> ProviderKind | None:
    """The ProviderKind the UI shows for a cached models.dev provider, or None when
    pydantic-ai can't use it."""
    style = style_of(entry)
    if style is None:
        return None
    if style == "native":
        return BY_ID[entry.provider_id].model_copy(update={"label": entry.name})
    env_vars = _env_vars(entry)
    env_var = env_vars[0] if env_vars else f"{entry.provider_id.upper().replace('-', '_')}_API_KEY"
    url = entry.api_url or ""
    local = _is_local_url(url)
    if "${" in url:
        # e.g. https://${DATABRICKS_HOST}/ai-gateway/mlflow/v1: the admin fills it in.
        base_url = KindField(
            key="base_url",
            label="Base URL",
            required=True,
            placeholder=url,
            help="Replace the ${...} parts with your own values.",
        )
    else:
        base_url = KindField(
            key="base_url",
            label="Base URL",
            default=url,
            placeholder=url,
            help=entry.doc_url or None,
        )
    return ProviderKind(
        id=entry.provider_id,
        label=entry.name,
        group="local" if local else "cloud",
        fields=[
            KindField(
                key="api_key",
                label="API key",
                secret=True,
                required=not local,
                help=f"From {env_var} in the provider's docs.",
            ),
            base_url,
            KindField(
                key="context_window",
                label="Context window",
                placeholder="e.g. 32768",
                help="Tokens the model accepts. Leave empty to detect it.",
            ),
        ],
        lists_models=True,
    )


class ModelsDevService:
    """Service for fetching and caching models.dev data."""

    def __init__(self, session_factory: Callable[[], Iterator[Session]]):
        # Database.session is a generator function; wrap it so `with` works.
        self._session = contextmanager(session_factory)
        self._fetch_lock = asyncio.Lock()
        self._last_fetch: float = 0
        self._min_fetch_interval = 300  # Minimum 5 minutes between fetches

    async def ensure_cache_fresh(self, force: bool = False) -> int:
        """Fetch and cache models.dev data if stale. Returns number of providers cached."""
        async with self._fetch_lock:
            # Rate limiting: don't fetch more than once per 5 minutes unless forced
            now = time.monotonic()
            if not force and self._last_fetch and now - self._last_fetch < self._min_fetch_interval:
                log.debug("models.dev cache fetch rate limited")
                return 0

            with self._session() as db:
                latest = db.exec(
                    select(ModelsDevCache.expires_at)
                    .order_by(col(ModelsDevCache.expires_at).desc())
                    .limit(1)
                ).first()
                if not force and latest and _aware(latest) > datetime.now(UTC):
                    log.debug("models.dev cache is fresh")
                    return 0

            log.info("Fetching fresh models.dev data...")
            # Counted before the fetch, so an offline host doesn't retry on every request.
            self._last_fetch = time.monotonic()
            providers = await self._fetch_models_dev()
            with self._session() as db:
                return self._store_cache(db, providers)

    async def _fetch_models_dev(self) -> dict[str, ModelsDevProvider]:
        """Fetch all providers from models.dev API."""
        async with httpx2.AsyncClient(timeout=FETCH_TIMEOUT) as client:
            resp = await client.get(MODELS_DEV_API)
            resp.raise_for_status()
            data = resp.json()

        providers = {}
        for provider_id, provider_data in data.items():
            providers[provider_id] = ModelsDevProvider.from_json(provider_id, provider_data)
        log.info(f"Fetched {len(providers)} providers from models.dev")
        return providers

    def _store_cache(self, db: Session, providers: dict[str, ModelsDevProvider]) -> int:
        """Store providers in database cache."""
        now = datetime.now(UTC)
        expires_at = now + CACHE_TTL
        count = 0

        for provider in providers.values():
            if not provider.models:
                continue

            cache_entry = ModelsDevCache(
                provider_id=provider.id,
                name=provider.name,
                api_url=provider.get_base_url(),
                npm_package=provider.npm or None,
                doc_url=provider.doc or None,
                env_vars=list(provider.env),
                models=provider.models,
                model_count=len(provider.models),
                is_openai_compatible=provider.is_openai_compatible(),
                fetched_at=now,
                expires_at=expires_at,
            )
            db.merge(cache_entry)
            count += 1

        db.commit()
        log.info(f"Cached {count} providers in database")
        return count

    def get_cached_providers(self) -> list[ModelsDevCache]:
        """Every cached provider, most models first.

        Expired rows are still served: they're only refreshed when models.dev answers,
        and an offline host keeps the providers it last saw.
        """
        with self._session() as db:
            return list(
                db.exec(
                    select(ModelsDevCache).order_by(col(ModelsDevCache.model_count).desc())
                ).all()
            )

    def get_provider(self, provider_id: str) -> ModelsDevCache | None:
        """Get a single cached provider."""
        with self._session() as db:
            return db.get(ModelsDevCache, provider_id)

    def get_models(self, provider_id: str) -> list[dict[str, Any]]:
        """Get model list for a provider from cache."""
        entry = self.get_provider(provider_id)
        if not entry:
            return []
        return list(entry.models.values())

    def get_all_models(self) -> dict[str, list[dict[str, Any]]]:
        """Get all models grouped by provider."""
        providers = self.get_cached_providers()
        return {p.provider_id: list(p.models.values()) for p in providers}

    def get_kind(self, provider_id: str) -> ProviderKind | None:
        """The kind for one cached models.dev provider pydantic-ai can use, or None."""
        entry = self.get_provider(provider_id)
        return kind_from_entry(entry) if entry is not None else None

    def get_kinds(self) -> list[ProviderKind]:
        """Every cached models.dev provider pydantic-ai can use, most models first."""
        kinds = (kind_from_entry(entry) for entry in self.get_cached_providers())
        return [k for k in kinds if k is not None]


# Global service instance (set during app startup)
_service: ModelsDevService | None = None


def init_models_dev_service(session_factory: Callable[[], Iterator[Session]]) -> ModelsDevService:
    """Initialize the global models.dev service."""
    global _service
    _service = ModelsDevService(session_factory)
    return _service


def get_models_dev_service() -> ModelsDevService | None:
    """Get the global models.dev service."""
    return _service


def resolve_kind(kind_id: str) -> ProviderKind | None:
    """A saved provider's kind: from the models.dev cache table (survives restarts), or the
    built-in form for a native or local kind, so a saved provider never vanishes."""
    kind = _service.get_kind(kind_id) if _service else None
    return kind or BY_ID.get(kind_id)


async def list_kinds() -> list[ProviderKind]:
    """What the "Add provider" picker offers: every models.dev provider pydantic-ai can
    use, plus local Ollama. An empty cache (first start) is filled first."""
    if _service is None:
        return list(LOCAL_KINDS)
    if not _service.get_cached_providers():
        try:
            await _service.ensure_cache_fresh()
        except Exception as exc:  # offline: Ollama alone until models.dev answers
            log.warning("Couldn't fetch models.dev: %s", exc)
    return [*_service.get_kinds(), *LOCAL_KINDS]


async def refresh_models_dev_cache(force: bool = False) -> int:
    """Refresh the models.dev cache through the global service (0 when there is none)."""
    if _service is None:
        return 0
    return await _service.ensure_cache_fresh(force=force)
