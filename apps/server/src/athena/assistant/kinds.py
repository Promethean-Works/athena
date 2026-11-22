"""The AI provider kinds Athena knows (docs/design/assistant.md).

Each kind is a small form description: the UI renders the fields, the server checks
them, and `providers.py` turns a saved provider into a pydantic-ai model.

Every provider in the list comes from models.dev (`models_dev.py`). The kinds here are
only the form and model class for models.dev ids that need their own pydantic-ai
provider (`NATIVE_KINDS`), and local Ollama, which models.dev doesn't list.
"""

from typing import Literal

from pydantic import BaseModel


class KindField(BaseModel):
    key: str
    label: str
    secret: bool = False
    """Stored encrypted and never sent back to the browser."""
    required: bool = False
    default: str | None = None
    placeholder: str | None = None
    help: str | None = None


class ProviderKind(BaseModel):
    id: str
    """The models.dev provider id (or "ollama")."""
    label: str
    group: Literal["cloud", "local", "custom"]
    fields: list[KindField]
    lists_models: bool = True
    """False when model ids can only be typed (Azure deployments)."""


def _key(required: bool = True, help: str | None = None) -> KindField:
    return KindField(key="api_key", label="API key", secret=True, required=required, help=help)


def _window(help: str) -> KindField:
    return KindField(
        key="context_window",
        label="Context window",
        placeholder="e.g. 32768",
        help=help + " Leave empty to detect it.",
    )


def _url(default: str | None, *, required: bool = False, help: str | None = None) -> KindField:
    return KindField(
        key="base_url",
        label="Base URL",
        required=required,
        default=default,
        placeholder=default,
        help=help,
    )


# models.dev ids with their own pydantic-ai provider or form. Listed only when models.dev
# lists them; their label then comes from models.dev.
NATIVE_KINDS: list[ProviderKind] = [
    ProviderKind(
        id="anthropic",
        label="Anthropic",
        group="cloud",
        fields=[_key(), _url("https://api.anthropic.com")],
    ),
    ProviderKind(
        id="openai",
        label="OpenAI",
        group="cloud",
        fields=[_key(), _url("https://api.openai.com/v1")],
    ),
    ProviderKind(id="google", label="Google Gemini", group="cloud", fields=[_key()]),
    ProviderKind(id="openrouter", label="OpenRouter", group="cloud", fields=[_key()]),
    ProviderKind(id="groq", label="Groq", group="cloud", fields=[_key()]),
    ProviderKind(id="mistral", label="Mistral", group="cloud", fields=[_key()]),
    ProviderKind(id="deepseek", label="DeepSeek", group="cloud", fields=[_key()]),
    ProviderKind(id="xai", label="xAI", group="cloud", fields=[_key()]),
    ProviderKind(
        id="azure",
        label="Azure OpenAI",
        group="cloud",
        lists_models=False,
        fields=[
            _key(),
            KindField(
                key="base_url",
                label="Endpoint",
                required=True,
                placeholder="https://<resource>.openai.azure.com",
            ),
            KindField(key="api_version", label="API version", default="2024-10-21"),
            _window("Tokens your deployment's model accepts."),
        ],
    ),
    ProviderKind(
        id="amazon-bedrock",
        label="Amazon Bedrock",
        group="cloud",
        fields=[
            KindField(key="access_key_id", label="Access key ID", required=True),
            KindField(
                key="secret_access_key", label="Secret access key", secret=True, required=True
            ),
            KindField(key="region", label="Region", required=True, default="us-east-1"),
        ],
    ),
    ProviderKind(
        id="cohere",
        label="Cohere",
        group="cloud",
        fields=[_key()],
    ),
    ProviderKind(
        id="google-vertex",
        label="Google Vertex AI",
        group="cloud",
        fields=[
            KindField(
                key="service_account",
                label="Service account key (JSON)",
                secret=True,
                required=True,
                help="Paste the whole JSON key file. The service account needs the "
                "Vertex AI User role; its project is used.",
            ),
            KindField(
                key="location",
                label="Location",
                required=True,
                default="us-central1",
                placeholder="us-central1",
                help="A region such as us-central1, or global.",
            ),
        ],
    ),
]


def _local(id: str, label: str, base_url: str, help: str | None = None) -> ProviderKind:
    """A local server with an OpenAI-compatible API (models listed from its /v1/models)."""
    return ProviderKind(
        id=id,
        label=label,
        group="local",
        fields=[
            _url(base_url, required=True, help=help),
            _key(required=False, help="Only if the server was started with an API key."),
            _window("Tokens the server runs models with."),
        ],
    )


# Local servers models.dev doesn't list (it has only "ollama-cloud" and a few desktop
# apps such as LM Studio). Always listed; each URL is the project's documented default.
LOCAL_KINDS: list[ProviderKind] = [
    ProviderKind(
        id="ollama",
        label="Ollama",
        group="local",
        fields=[
            _url("http://127.0.0.1:11434", required=True),
            _key(required=False, help="Only for Ollama Cloud or a proxy that asks for one."),
            _window("Tokens Ollama runs models with (OLLAMA_CONTEXT_LENGTH on the Ollama server)."),
        ],
    ),
    _local("llama-cpp", "llama.cpp (llama-server)", "http://127.0.0.1:8080/v1"),
    _local("vllm", "vLLM", "http://127.0.0.1:8000/v1"),
    _local("sglang", "SGLang", "http://127.0.0.1:30000/v1"),
    _local("localai", "LocalAI", "http://127.0.0.1:8080/v1"),
    _local("jan", "Jan", "http://127.0.0.1:1337/v1", help="Start Jan's Local API Server first."),
    _local(
        "gpt4all",
        "GPT4All",
        "http://127.0.0.1:4891/v1",
        help="Turn on GPT4All's Local API Server first.",
    ),
    _local("koboldcpp", "KoboldCpp", "http://127.0.0.1:5001/v1"),
    _local("llamafile", "llamafile", "http://127.0.0.1:8080/v1"),
    _local("tabbyapi", "TabbyAPI", "http://127.0.0.1:5000/v1"),
    _local(
        "text-generation-webui",
        "Text Generation WebUI",
        "http://127.0.0.1:5000/v1",
        help="Start it with --api.",
    ),
    _local(
        "docker-model-runner",
        "Docker Model Runner",
        "http://127.0.0.1:12434/engines/v1",
        help="Turn on host-side TCP support (docker desktop enable model-runner --tcp 12434).",
    ),
    _local("lemonade", "Lemonade Server", "http://127.0.0.1:13305/api/v1"),
    _local("mlx-lm", "MLX LM (mlx_lm.server)", "http://127.0.0.1:8080/v1"),
    _local("xinference", "Xinference", "http://127.0.0.1:9997/v1"),
]

# Any other server: the admin gives the base URL. Always listed.
CUSTOM_KINDS: list[ProviderKind] = [
    ProviderKind(
        id="openai-compatible",
        label="OpenAI-compatible API",
        group="custom",
        fields=[
            _url(
                None,
                required=True,
                help="The address before /chat/completions, e.g. http://host:8000/v1.",
            ),
            _key(required=False),
            _window("Tokens the model accepts."),
        ],
    ),
    ProviderKind(
        id="anthropic-compatible",
        label="Anthropic-compatible API",
        group="custom",
        fields=[
            _url(
                None,
                required=True,
                help="The address before /v1/messages, e.g. https://host/anthropic.",
            ),
            _key(required=False),
            _window("Tokens the model accepts."),
        ],
    ),
]

BY_ID: dict[str, ProviderKind] = {k.id: k for k in [*NATIVE_KINDS, *LOCAL_KINDS, *CUSTOM_KINDS]}


def secret_keys(kind: ProviderKind) -> set[str]:
    return {f.key for f in kind.fields if f.secret}


def get_native_kind_ids() -> set[str]:
    """The kinds Athena defines itself: `NATIVE_KINDS`, `LOCAL_KINDS` and `CUSTOM_KINDS`."""
    return set(BY_ID)
