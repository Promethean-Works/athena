"""Models.dev integration: fetch, cache, and serve provider/model data from models.dev.

This module replaces hardcoded provider lists with dynamic data from models.dev,
cached in the database for fast access and offline resilience.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
from sqlmodel import Session, select

from athena.assistant.kinds import KindField, ProviderKind, get_native_kind_ids
from athena.db.models import ModelsDevCache

log = logging.getLogger(__name__)

MODELS_DEV_API = "https://models.dev/api.json"
CACHE_TTL = timedelta(hours=24)  # Cache for 24 hours
FETCH_TIMEOUT = 30.0

# Providers with native pydantic-ai support (use dedicated providers, not OpenAI-compatible)
# These are the ones defined in kinds.py as NATIVE_KINDS
NATIVE_PROVIDERS = get_native_kind_ids()

# Skip patterns (token plans, routers, gateways, unknown providers)
SKIP_PATTERNS = [
    "token-plan",
    "coding-plan",
    "gateway",
    "router",
    "merge-gateway",
    "unrestricted",
    "unbiased",
    "refuseless",
    "abliteration",
    "ai-router",
    "agentrouter",
    "openreason",
    "korouter",
    "trustedrouter",
    "unorouter",
    "teamorouter",
    "logits",
    "routing-run",
    "the-grid-ai",
    "confidential-ai",
    "aistupidlevel",
    "hubris",
    "frequency",
    "ambient",
    "crossmodel",
    "aipg",
    "paraloncloud",
    "vercel",
    "bothub",
    "lynkr",
    "toapis",
    "phase",
    "kenari",
    "reflection",
    "cline-pass",
    "claudinio",
    "teapot-router",
    "chutes",
    "fortytwo",
    "tinfoil",
    "nano-gpt",
    "cheapest-token",
    "standardcompute",
    "uplinkswitch",
    "aihubmix",
    "vancine",
    "moneo",
    "obscurify",
    "berget",
    "entrim",
    "echo",
    "auriko",
    "evroc",
    "ofox",
    "ezkielyna",
    "morph",
    "sokkan",
    "jalapeno",
    "frogbot",
    "wallaby",
    "joingonka",
    "friendli",
    "submodel",
    "verda",
    "bumo",
    "inceptron",
    "aki-io",
    "bee",
    "atomic-chat",
    "synthetic",
    "runcrate",
    "fiftyx",
    "neosmith",
    "wally",
    "pendra",
    "tokengo",
    "moark",
    "tenstorrent",
    "superbot-gg",
    "sandbase",
    "ruapi",
    "vispark",
    "aigrow",
    "zeldoc",
    "aimlapi",
    "sarvam",
    "agnes",
    "uncensuredai",
    "powerspring",
    "munito-eu",
    "munito",
    "inco",
    "dinference",
    "qvac",
    "databricks",
    "tokenify",
    "above",
    "neuralwatt",
    "greenpt",
    "adaption",
    "nearai",
    "modelis",
    "aiand",
    "wandb",
    "klavo",
    "watt",
    "nan",
    "kosmik",
    "sap-ai-core",
    "ebcloud",
    "cloudflare-ai-gateway",
    "inference-coop",
    "stepfun-ai-step-plan",
    "infer",
    "stepfun",
    "prime",
    "kunavo",
    "scaleway",
    "snowflake-cortex",
    "github-copilot",
    "huggingface",
    "hostinger-router",
    "xpersona",
    "lyceum",
    "synthorai",
    "alibaba-token-plan",
    "engy",
    "proxystacks",
    "mixlayer",
    "zro",
    "doubleword",
    "trustedtokens",
    "meganova",
    "sakana",
    "minimax-cn",
    "venice",
    "zai-coding-plan",
    "scx-ai",
    "anyapi",
    "liquid",
    "kuae-cloud-coding-plan",
    "cloudflare-workers-ai",
    "tencent-coding-plan",
    "inference-coop",
    "stepfun-ai",
    "inception",
    "baseten",
    "poolside",
    "zai",
    "amd",
    "crusoe",
    "umans-ai",
    "powerspring",
    "privatemode-ai",
    "zenmux",
    "coralbricks",
    "lowrouter",
    "fastrouter",
    "lmstudio",
    "helicone",
    "tencent-token-plan",
    "siliconflow",
    "sagg",
    "wafer.ai",
    "inferx",
    "kitani",
    "nokeep",
    "infersia",
    "stepping-stone",
    "deepinfra",
    "zhipuai",
    "cortecs",
    "minimax",
    "orcarouter",
    "drun",
    "steadyrouter",
    "tokenwatt",
    "azure-cognitive-services",
    "arcee",
    "vivgrid",
    "nova",
    "freemodel",
    "salad-cloud",
    "xiaomi-token-plan",
    "xiaomi-token-plan-ams",
    "xiaomi-token-plan-cn",
    "xiaomi-token-plan-sgp",
    "subconscious",
    "hetzner",
    "graphn",
    "huawei-maas",
    "qihang-ai",
    "cloudflare-workers-ai",
    "inferenceapis",
    "opencode",
    "opencode-go",
    "tokenrouter",
    "cheapllm",
    "boundless",
    "llmgateway",
    "llmgateway-providers",
    "merge-gateway",
    "watsonx",
    "aigrow",
    "ai-router",
    "ruapi",
    "vispark",
    "volcengine-coding-plan",
    "zhipuai-coding-plan",
    "klokintegration",
    "siliconflow-cn",
    "moark",
    "unbiased",
    "abliteratedllm",
    "xai",
    "augure",
    "inferris",
    "bailing",
    "autarcho",
    "isoquant",
    "moonshotai-cn",
    "mallard",
    "opper",
    "alibaba-coding-plan-cn",
    "confidential-ai",
    "daoxe",
    "llmtr",
    "moonshotai",
    "melious",
    "kimi-code-plan-global",
    "kimi-code-plan-cn",
    "anonrouter",
    "evroc",
    "ofox",
    "upstage",
    "digitalocean",
    "vultr",
    "novita-ai",
    "nebius",
    "inference",
    "modal",
    "oci",
    "perplexity-agent",
    "ollama-cloud",
]


def should_skip(provider_id: str) -> bool:
    """Check if a provider should be skipped."""
    if provider_id in NATIVE_PROVIDERS:
        return True
    return any(pattern in provider_id for pattern in SKIP_PATTERNS)


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
        """Check if this provider uses OpenAI-compatible API."""
        if self.npm in (
            "@ai-sdk/openai-compatible",
            "@ai-sdk/openai",
            "@openrouter/ai-sdk-provider",
        ):
            return True
        return bool(self.api and "openai" in self.api.lower())

    def get_base_url(self) -> str | None:
        """Get the base URL for OpenAI-compatible endpoints."""
        if self.api:
            url = self.api.rstrip("/")
            for suffix in ["/models", "/v1/models", "/v2/models", "/api/v1/models"]:
                if url.endswith(suffix):
                    url = url[: -len(suffix)]
                    break
            return url
        return None

    def to_provider_kind(self) -> ProviderKind:
        """Convert to a ProviderKind for the UI."""
        env_vars = self.env
        env_var = env_vars[0] if env_vars else f"{self.id.upper().replace('-', '_')}_API_KEY"

        fields = [
            KindField(
                key="api_key",
                label="API key",
                secret=True,
                required=True,
                help=f"Set {env_var} in your environment or enter it here",
            ),
        ]

        base_url = self.get_base_url()
        if base_url:
            fields.append(
                KindField(
                    key="base_url",
                    label="Base URL",
                    required=False,
                    default=base_url,
                    placeholder=base_url,
                    help=self.doc or "Provider's API endpoint",
                )
            )
        else:
            fields.append(
                KindField(
                    key="base_url",
                    label="Base URL",
                    required=False,
                    placeholder="Optional: custom endpoint",
                    help="Leave empty to use the official API",
                )
            )

        fields.append(
            KindField(
                key="context_window",
                label="Context window",
                placeholder="e.g. 32768",
                help="Tokens the model accepts. Leave empty to detect automatically.",
            )
        )

        return ProviderKind(
            id=self.id,
            label=self.name,
            group="cloud" if base_url else "local",
            fields=fields,
            lists_models=True,
        )


class ModelsDevService:
    """Service for fetching and caching models.dev data."""

    def __init__(self, session_factory):
        self._session_factory = session_factory
        self._fetch_lock = asyncio.Lock()
        self._last_fetch: float = 0
        self._min_fetch_interval = 300  # Minimum 5 minutes between fetches

    async def ensure_cache_fresh(self, force: bool = False) -> int:
        """Fetch and cache models.dev data if stale. Returns number of providers cached."""
        async with self._fetch_lock:
            # Rate limiting: don't fetch more than once per 5 minutes unless forced
            now = time.monotonic()
            if not force and now - self._last_fetch < self._min_fetch_interval:
                log.debug("models.dev cache fetch rate limited")
                return 0

            with self._session_factory() as db:
                # Check if we have fresh cache
                now_utc = datetime.now(UTC)
                latest = db.exec(
                    select(ModelsDevCache.expires_at)
                    .order_by(ModelsDevCache.expires_at.desc())
                    .limit(1)
                ).first()

                if not force and latest and latest > now_utc:
                    log.debug("models.dev cache is fresh")
                    return 0

                # Cache is stale or empty, fetch fresh data
                log.info("Fetching fresh models.dev data...")
                providers = await self._fetch_models_dev()
                count = await self._store_cache(db, providers)
                self._last_fetch = time.monotonic()
                return count

    async def _fetch_models_dev(self) -> dict[str, ModelsDevProvider]:
        """Fetch all providers from models.dev API."""
        async with httpx2.AsyncClient(timeout=FETCH_TIMEOUT) as client:
            resp = await client.get(MODELS_DEV_API)
            resp.raise_for_status()
            data = resp.json()

        providers = {}
        for provider_id, provider_data in data.items():
            if should_skip(provider_id):
                continue
            providers[provider_id] = ModelsDevProvider.from_json(provider_id, provider_data)
        log.info(f"Fetched {len(providers)} providers from models.dev")
        return providers

    async def _store_cache(self, db: Session, providers: dict[str, ModelsDevProvider]) -> int:
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
                env_vars=json.dumps(provider.env),
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

    def _get_session(self) -> Session:
        """Get a database session."""
        return next(self._session_factory())

    def get_cached_providers(self) -> list[ModelsDevCache]:
        """Get all cached providers from database."""
        db = self._get_session()
        try:
            return list(
                db.exec(
                    select(ModelsDevCache)
                    .where(ModelsDevCache.expires_at > datetime.now(UTC))
                    .order_by(ModelsDevCache.model_count.desc())
                ).all()
            )
        finally:
            db.close()

    def get_provider(self, provider_id: str) -> ModelsDevCache | None:
        """Get a single cached provider."""
        db = self._get_session()
        try:
            return db.get(ModelsDevCache, provider_id)
        finally:
            db.close()

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

    def get_dynamic_kinds(self) -> list[ProviderKind]:
        """Generate ProviderKind entries for all cached OpenAI-compatible providers."""
        kinds = []
        for entry in self.get_cached_providers():
            if not entry.is_openai_compatible:
                continue

            # Skip if this is a native provider
            if entry.provider_id in NATIVE_PROVIDERS:
                continue

            env_vars = json.loads(entry.env_vars or "[]")
            env_var = (
                env_vars[0]
                if env_vars
                else f"{entry.provider_id.upper().replace('-', '_')}_API_KEY"
            )

            fields = [
                KindField(
                    key="api_key",
                    label="API key",
                    secret=True,
                    required=True,
                    help=f"Set {env_var} in your environment or enter it here",
                ),
            ]

            if entry.api_url:
                fields.append(
                    KindField(
                        key="base_url",
                        label="Base URL",
                        required=False,
                        default=entry.api_url,
                        placeholder=entry.api_url,
                        help=entry.doc_url or "Provider's API endpoint",
                    )
                )
            else:
                fields.append(
                    KindField(
                        key="base_url",
                        label="Base URL",
                        required=False,
                        placeholder="Optional: custom endpoint",
                        help="Leave empty to use the official API",
                    )
                )

            fields.append(
                KindField(
                    key="context_window",
                    label="Context window",
                    placeholder="e.g. 32768",
                    help="Tokens the model accepts. Leave empty to detect automatically.",
                )
            )

            kind = ProviderKind(
                id=entry.provider_id,
                label=entry.name,
                group="cloud" if entry.api_url else "local",
                fields=fields,
                lists_models=True,
            )
            kinds.append(kind)

        return kinds


# Global service instance (set during app startup)
_service: ModelsDevService | None = None


def init_models_dev_service(session_factory) -> ModelsDevService:
    """Initialize the global models.dev service."""
    global _service
    _service = ModelsDevService(session_factory)
    return _service


def get_models_dev_service() -> ModelsDevService | None:
    """Get the global models.dev service."""
    return _service


async def refresh_models_dev_cache(session_factory, force: bool = False) -> int:
    """Manually refresh the models.dev cache."""
    service = ModelsDevService(session_factory)
    return await service.ensure_cache_fresh(force=force)
