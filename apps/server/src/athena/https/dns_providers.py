"""DNS providers for Let's Encrypt's DNS-01 challenge (docs/specs/https.md).

Each provider is one entry: lego's provider code and the fields the admin fills in, each
mapped to the environment variable lego reads. Adding a provider is adding an entry
(check the variable names in lego's docs for that provider). Field keys ending in
`token`, `secret`, `password` or `key` are secrets: stored encrypted, never returned.
"""

from pydantic import BaseModel

from athena.system_settings import is_secret


class DnsField(BaseModel):
    key: str
    label: str
    env: str
    """The environment variable lego reads it from."""
    secret: bool
    required: bool = True
    help: str | None = None


class DnsProvider(BaseModel):
    id: str
    """lego's provider code (`lego run --dns <id>`)."""
    label: str
    fields: list[DnsField]
    docs: str


def _field(key: str, label: str, env: str, required: bool = True, help: str | None = None):
    return DnsField(
        key=key, label=label, env=env, secret=is_secret(key), required=required, help=help
    )


PROVIDERS: list[DnsProvider] = [
    DnsProvider(
        id="cloudflare",
        label="Cloudflare",
        fields=[
            _field(
                "api_token",
                "API token",
                "CLOUDFLARE_DNS_API_TOKEN",
                help="A token with Zone → Zone → Read and Zone → DNS → Edit for the domain's zone.",
            ),
        ],
        docs="https://go-acme.github.io/lego/dns/cloudflare/",
    ),
]

BY_ID = {p.id: p for p in PROVIDERS}


def provider_env(provider_id: str, values: dict[str, str]) -> dict[str, str]:
    """The environment variables lego needs for this provider. Raises `ValueError`."""
    provider = BY_ID.get(provider_id)
    if provider is None:
        raise ValueError(f"Unknown DNS provider {provider_id!r}")
    env: dict[str, str] = {}
    for f in provider.fields:
        value = (values.get(f.key) or "").strip()
        if not value:
            if f.required:
                raise ValueError(f"{provider.label}: {f.label} is required")
            continue
        env[f.env] = value
    return env
