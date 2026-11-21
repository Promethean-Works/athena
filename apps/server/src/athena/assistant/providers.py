"""Saved AI providers: their settings, the pydantic-ai model for a model id, and the live
model list (docs/design/assistant.md)."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import httpx2
from pydantic import BaseModel

from athena.assistant.kinds import ProviderKind, get_native_kind_ids, secret_keys
from athena.assistant.models_dev import get_models_dev_service, resolve_kind
from athena.crypto import SecretBox
from athena.db.models import AiProvider

if TYPE_CHECKING:
    from pydantic_ai import ConcurrencyLimiter
    from pydantic_ai.models import Model

LIST_TIMEOUT = 15.0
CACHE_SECONDS = 600


class ProviderError(Exception):
    """A provider can't be reached or refused the request. The message is for people."""


class ModelInfo(BaseModel):
    id: str
    name: str | None = None
    tools: bool | None = None
    """Whether the model can call tools, when the provider says; None when unknown."""
    context_window: int | None = None
    """Tokens the model accepts, when the provider's list says."""


def listed_window(entry: dict[str, Any]) -> int | None:
    """A model list entry's window, under whichever name the provider uses: OpenRouter
    `context_length`, Groq `context_window`, Mistral `max_context_length`, vLLM
    `max_model_len`."""
    for key in ("context_length", "context_window", "max_context_length", "max_model_len"):
        value = entry.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return None


@dataclass
class ProviderConfig:
    """A saved provider with its secrets decrypted, ready to build models from."""

    id: str
    kind: ProviderKind
    name: str
    values: dict[str, str] = field(default_factory=dict)

    def get(self, key: str) -> str | None:
        value = self.values.get(key)
        if value:
            return value
        spec = next((f for f in self.kind.fields if f.key == key), None)
        return spec.default if spec else None


def config_of(row: AiProvider, box: SecretBox) -> ProviderConfig:
    kind = resolve_kind(row.kind)
    if kind is None:
        raise ProviderError(f"Unknown provider kind: {row.kind}")
    values: dict[str, str] = dict(json.loads(row.config or "{}"))
    if row.secrets:
        values.update(json.loads(box.decrypt(row.secrets)))
    return ProviderConfig(id=row.id, kind=kind, name=row.name, values=values)


def split_values(
    kind: ProviderKind, values: dict[str, str]
) -> tuple[dict[str, str], dict[str, str]]:
    """(plain config, secrets) for the kind's known fields; other keys are dropped."""
    secret = secret_keys(kind)
    known = {f.key for f in kind.fields}
    plain = {k: v for k, v in values.items() if k in known and k not in secret and v}
    secrets = {k: v for k, v in values.items() if k in secret and v}
    return plain, secrets


def check_values(kind: ProviderKind, values: dict[str, str]) -> None:
    for f in kind.fields:
        value = values.get(f.key) or f.default
        if f.required and not value:
            raise ValueError(f"{f.label} is required")
        if f.key == "base_url" and value:
            parts = urlsplit(value)
            if parts.scheme not in ("http", "https") or not parts.netloc:
                raise ValueError(f"{f.label} must be an http:// or https:// address")
        if f.key == "context_window" and value and not (value.isdigit() and int(value) >= 1024):
            raise ValueError(f"{f.label} must be a number of tokens, at least 1024")


def _strip(url: str) -> str:
    return url.rstrip("/")


LOCAL_HOSTS = {"localhost", "host.docker.internal", "host.containers.internal"}
_queues: dict[str, ConcurrencyLimiter] = {}


def is_local(kind: str, base_url: str | None) -> bool:
    """Whether the model runs on hardware the admin owns (Ollama, LM Studio, llama.cpp on
    this machine or the LAN): those answer one request at a time."""
    if kind == "ollama":
        return True
    host = urlsplit(base_url or "").hostname
    if not host:
        return False
    if host in LOCAL_HOSTS or host.endswith((".local", ".lan", ".home.arpa")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def queue_for(base_url: str) -> ConcurrencyLimiter:
    """One queue per local server, shared by every model on it: chat turns, titles,
    delegates, the advisor and reviews wait their turn instead of hitting it at once."""
    from pydantic_ai import ConcurrencyLimiter

    key = _strip(base_url)
    if key not in _queues:
        _queues[key] = ConcurrencyLimiter(max_running=1, name=f"ai:{key}")
    return _queues[key]


def build_model(cfg: ProviderConfig, model_id: str) -> Model:
    """The pydantic-ai model for `model_id` on this provider. Models on a local server
    share a queue, so it gets one request at a time."""
    from pydantic_ai.models.concurrency import ConcurrencyLimitedModel

    model = _build_model(cfg, model_id)
    if is_local(cfg.kind.id, model.base_url):
        return ConcurrencyLimitedModel(model, queue_for(model.base_url or cfg.kind.id))
    return model


def _build_model(cfg: ProviderConfig, model_id: str) -> Model:
    kind = cfg.kind.id
    key = cfg.get("api_key")

    if kind == "anthropic":
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        return AnthropicModel(
            model_id, provider=AnthropicProvider(api_key=key, base_url=cfg.get("base_url"))
        )
    if kind == "openai":
        from pydantic_ai.models.openai import OpenAIResponsesModel
        from pydantic_ai.providers.openai import OpenAIProvider

        return OpenAIResponsesModel(
            model_id, provider=OpenAIProvider(base_url=cfg.get("base_url"), api_key=key)
        )
    if kind == "google":
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider

        return GoogleModel(model_id, provider=GoogleProvider(api_key=key))
    if kind == "openrouter":
        from pydantic_ai.models.openrouter import OpenRouterModel
        from pydantic_ai.providers.openrouter import OpenRouterProvider

        return OpenRouterModel(
            model_id, provider=OpenRouterProvider(api_key=key, app_title="Athena")
        )
    if kind == "groq":
        from pydantic_ai.models.groq import GroqModel
        from pydantic_ai.providers.groq import GroqProvider

        return GroqModel(model_id, provider=GroqProvider(api_key=key))
    if kind == "mistral":
        from pydantic_ai.models.mistral import MistralModel
        from pydantic_ai.providers.mistral import MistralProvider

        return MistralModel(model_id, provider=MistralProvider(api_key=key))
    if kind == "deepseek":
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.deepseek import DeepSeekProvider

        return OpenAIChatModel(model_id, provider=DeepSeekProvider(api_key=key))
    if kind == "cohere":
        from pydantic_ai.models.cohere import CohereModel
        from pydantic_ai.providers.cohere import CohereProvider

        return CohereModel(model_id, provider=CohereProvider(api_key=key))
    if kind == "xai":
        # xAI's OpenAI-compatible API
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        return OpenAIChatModel(
            model_id, provider=OpenAIProvider(base_url="https://api.x.ai/v1", api_key=key)
        )
    if kind == "azure":
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.azure import AzureProvider

        return OpenAIChatModel(
            model_id,
            provider=AzureProvider(
                azure_endpoint=cfg.get("base_url"),
                api_version=cfg.get("api_version"),
                api_key=key,
            ),
        )
    if kind == "bedrock":
        from pydantic_ai.models.bedrock import BedrockConverseModel
        from pydantic_ai.providers.bedrock import BedrockProvider

        return BedrockConverseModel(
            model_id,
            provider=BedrockProvider(
                aws_access_key_id=cfg.get("access_key_id"),
                aws_secret_access_key=cfg.get("secret_access_key"),
                region_name=cfg.get("region"),
            ),
        )
    if kind == "ollama":
        from pydantic_ai.models.ollama import OllamaModel
        from pydantic_ai.providers.ollama import OllamaProvider

        base = _strip(cfg.get("base_url") or "")
        return OllamaModel(
            model_id, provider=OllamaProvider(base_url=f"{base}/v1", api_key=key or "ollama")
        )

    # All other providers (including dynamically loaded from models.dev) use OpenAI-compatible API
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    # Get base URL from models.dev cache
    service = get_models_dev_service()
    base_url = None
    if service:
        entry = service.get_provider(kind)
        if entry and entry.api_url:
            base_url = entry.api_url

    # Fall back to configured base_url
    base_url = base_url or cfg.get("base_url") or ""

    return OpenAIChatModel(
        model_id,
        provider=OpenAIProvider(base_url=base_url, api_key=key or "not-needed"),
    )


# ---------------------------------------------------------------- model lists


def _describe(exc: Exception, cfg: ProviderConfig) -> str:
    if isinstance(exc, httpx2.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return f"{cfg.name} refused the API key (HTTP {code})"
        detail = ""
        with contextlib.suppress(ValueError):
            body = exc.response.json()
            err = body.get("error") if isinstance(body, dict) else None
            detail = (err.get("message") if isinstance(err, dict) else err) or ""
        return f"{cfg.name} answered HTTP {code}" + (f": {detail}" if detail else "")
    if isinstance(exc, httpx2.TimeoutException):
        return f"{cfg.name} didn't answer in time"
    if isinstance(exc, httpx2.RequestError):
        return f"Can't reach {cfg.name}: {exc}"
    return f"{cfg.name}: {exc}"


async def _json(client: httpx2.AsyncClient, method: str, url: str, **kw: Any) -> Any:
    res = await client.request(method, url, **kw)
    res.raise_for_status()
    return res.json()


def _bearer(key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"} if key else {}


async def _openai_style(client: httpx2.AsyncClient, base: str, key: str | None) -> list[ModelInfo]:
    data = await _json(client, "GET", f"{_strip(base)}/models", headers=_bearer(key))
    return [
        ModelInfo(id=m["id"], context_window=listed_window(m))
        for m in data.get("data", [])
        if m.get("id")
    ]


async def _ollama(client: httpx2.AsyncClient, base: str, key: str | None) -> list[ModelInfo]:
    base = _strip(base)
    tags = await _json(client, "GET", f"{base}/api/tags", headers=_bearer(key))
    listed = [m for m in tags.get("models", []) if m.get("name")]

    def info_of(name: str, caps: object) -> ModelInfo:
        if not isinstance(caps, list):
            return ModelInfo(id=name)
        if "completion" not in caps and "embedding" in caps:
            return ModelInfo(id=name, tools=False, name="embedding")
        return ModelInfo(id=name, tools="tools" in caps)

    async def show(model: dict[str, Any]) -> ModelInfo:
        name = model["name"]
        if "capabilities" in model:
            return info_of(name, model["capabilities"])
        try:
            info = await _json(
                client, "POST", f"{base}/api/show", json={"model": name}, headers=_bearer(key)
            )
        except (httpx2.HTTPError, ValueError):
            return ModelInfo(id=name)
        return info_of(name, info.get("capabilities"))

    infos = await asyncio.gather(*(show(m) for m in listed))
    return [i for i in infos if i.name != "embedding"]


async def _anthropic(client: httpx2.AsyncClient, cfg: ProviderConfig) -> list[ModelInfo]:
    data = await _json(
        client,
        "GET",
        f"{_strip(cfg.get('base_url') or '')}/v1/models",
        params={"limit": 1000},
        headers={"x-api-key": cfg.get("api_key") or "", "anthropic-version": "2023-06-01"},
    )
    return [
        ModelInfo(id=m["id"], name=m.get("display_name"), tools=True)
        for m in data.get("data", [])
        if m.get("id")
    ]


async def _google(client: httpx2.AsyncClient, cfg: ProviderConfig) -> list[ModelInfo]:
    data = await _json(
        client,
        "GET",
        "https://generativelanguage.googleapis.com/v1beta/models",
        params={"pageSize": 1000},
        headers={"x-goog-api-key": cfg.get("api_key") or ""},
    )
    out = []
    for m in data.get("models", []):
        if "generateContent" not in m.get("supportedGenerationMethods", []):
            continue
        out.append(ModelInfo(id=m["name"].removeprefix("models/"), name=m.get("displayName")))
    return out


async def _openrouter(client: httpx2.AsyncClient, cfg: ProviderConfig) -> list[ModelInfo]:
    data = await _json(
        client,
        "GET",
        "https://openrouter.ai/api/v1/models",
        headers=_bearer(cfg.get("api_key")),
    )
    return [
        ModelInfo(
            id=m["id"],
            name=m.get("name"),
            tools="tools" in (m.get("supported_parameters") or []),
            context_window=listed_window(m),
        )
        for m in data.get("data", [])
        if m.get("id")
    ]


async def _mistral(client: httpx2.AsyncClient, cfg: ProviderConfig) -> list[ModelInfo]:
    data = await _json(
        client, "GET", "https://api.mistral.ai/v1/models", headers=_bearer(cfg.get("api_key"))
    )
    out = []
    for m in data.get("data", []):
        caps = m.get("capabilities") or {}
        if caps.get("completion_chat") is False:
            continue
        tools = caps.get("function_calling")
        out.append(
            ModelInfo(
                id=m["id"],
                tools=tools if isinstance(tools, bool) else None,
                context_window=listed_window(m),
            )
        )
    return out


async def _azure(client: httpx2.AsyncClient, cfg: ProviderConfig) -> list[ModelInfo]:
    """Azure can't list deployments with a key, so this only proves the key works."""
    await _json(
        client,
        "GET",
        f"{_strip(cfg.get('base_url') or '')}/openai/models",
        params={"api-version": cfg.get("api_version")},
        headers={"api-key": cfg.get("api_key") or ""},
    )
    return []


async def _cohere(client: httpx2.AsyncClient, cfg: ProviderConfig) -> list[ModelInfo]:
    data = await _json(
        client, "GET", "https://api.cohere.com/v2/models", headers=_bearer(cfg.get("api_key"))
    )
    out = []
    for m in data.get("models", []):
        if "chat" not in m.get("endpoints", []):
            continue
        out.append(ModelInfo(id=m["name"], name=m.get("name")))
    return out


def _bedrock(cfg: ProviderConfig) -> list[ModelInfo]:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        client = boto3.client(
            "bedrock",
            aws_access_key_id=cfg.get("access_key_id"),
            aws_secret_access_key=cfg.get("secret_access_key"),
            region_name=cfg.get("region"),
        )
        data = client.list_foundation_models(byOutputModality="TEXT")
    except (BotoCoreError, ClientError) as exc:
        raise ProviderError(f"{cfg.name}: {exc}") from exc
    return [
        ModelInfo(id=m["modelId"], name=m.get("modelName"))
        for m in data.get("modelSummaries", [])
        if "ON_DEMAND" in (m.get("inferenceTypesSupported") or ["ON_DEMAND"])
    ]


async def _fetch_models_from_cache(kind: str) -> list[ModelInfo] | None:
    """Try to get models from models.dev database cache."""
    service = get_models_dev_service()
    if not service:
        return None

    models = service.get_models(kind)
    if not models:
        return None

    out = []
    for m in models:
        out.append(
            ModelInfo(
                id=m.get("id"),
                name=m.get("name"),
                tools=m.get("tool_call"),
                context_window=m.get("limit", {}).get("context"),
            )
        )
    return sorted(out, key=lambda m: m.id)


async def fetch_models(
    cfg: ProviderConfig, transport: httpx2.AsyncBaseTransport | None = None
) -> list[ModelInfo]:
    """The provider's own model list. Raises ProviderError with a readable message."""
    kind = cfg.kind.id

    # Native providers with special model listing
    if kind == "bedrock":
        return await asyncio.to_thread(_bedrock, cfg)

    # Try provider's own API first for native providers
    try:
        async with httpx2.AsyncClient(timeout=LIST_TIMEOUT, transport=transport) as client:
            if kind == "anthropic":
                return await _anthropic(client, cfg)
            elif kind == "google":
                return await _google(client, cfg)
            elif kind == "openrouter":
                return await _openrouter(client, cfg)
            elif kind == "mistral":
                return await _mistral(client, cfg)
            elif kind == "groq":
                # Groq uses its own API
                data = await _json(
                    client,
                    "GET",
                    "https://api.groq.com/openai/v1/models",
                    headers=_bearer(cfg.get("api_key")),
                )
                return [
                    ModelInfo(id=m["id"], context_window=listed_window(m))
                    for m in data.get("data", [])
                    if m.get("id")
                ]
            elif kind == "azure":
                return await _azure(client, cfg)
            elif kind == "ollama":
                return await _ollama(client, cfg.get("base_url") or "", cfg.get("api_key"))
            elif kind == "cohere":
                return await _cohere(client, cfg)
            elif kind in get_native_kind_ids():
                # Other native providers use OpenAI-compatible listing
                base = cfg.get("base_url") or ""
                return await _openai_style(client, base, cfg.get("api_key"))
    except (httpx2.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
        # For native providers, propagate the error
        if kind in get_native_kind_ids():
            raise ProviderError(_describe(exc, cfg)) from exc

    # For all other providers (dynamically loaded from models.dev), use database cache
    cached = await _fetch_models_from_cache(kind)
    if cached:
        return cached

    # Fallback: try OpenAI-compatible API if base_url is configured
    if cfg.get("base_url"):
        try:
            async with httpx2.AsyncClient(timeout=LIST_TIMEOUT, transport=transport) as client:
                return await _openai_style(client, cfg.get("base_url") or "", cfg.get("api_key"))
        except (httpx2.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            pass

    raise ProviderError(f"No model list available for provider {kind!r}")


class ModelCache:
    """Model lists per provider, kept for CACHE_SECONDS."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._entries: dict[str, tuple[float, list[ModelInfo]]] = {}

    def get(self, provider_id: str) -> list[ModelInfo] | None:
        entry = self._entries.get(provider_id)
        if entry and self._clock() - entry[0] < CACHE_SECONDS:
            return entry[1]
        return None

    def put(self, provider_id: str, models: list[ModelInfo]) -> None:
        self._entries[provider_id] = (self._clock(), models)

    def drop(self, provider_id: str) -> None:
        self._entries.pop(provider_id, None)
