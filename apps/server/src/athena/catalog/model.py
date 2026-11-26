"""The catalog app format.

A catalog app is a plain compose file plus an `x-athena` block:

    x-athena:
      title: Jellyfin
      description: Stream your movies, shows and music.
      category: media
      icon: https://…/jellyfin.svg
      homepage: https://jellyfin.org
      web_port: WEB_PORT          # env key (or a number) that "Open" links to
      platforms: [linux/amd64, linux/arm64]
      env:                        # renders the install form; values go to .env
        - key: WEB_PORT
          label: Web port
          type: port
          default: "8096"
        - key: TZ
          label: Timezone
          default: "@timezone"    # tokens: @timezone @uid @gid @app_data[/sub]
        - key: DB_PASSWORD
          label: Database password
          type: password
          generate: secret        # filled with a random value if left empty
                                  # (hex16 / hex32: that many random bytes as hex)
      profiles:                   # optional parts: services with `profiles: [browser]`
        - id: browser
          label: Browser for agents
          default: false

The compose file references values with standard `${KEY}` interpolation. Athena
writes the answers to `.env` next to `compose.yaml`, which compose reads on its own.
"""

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

FieldType = Literal["text", "password", "port", "path", "number", "boolean", "select"]
Category = Literal[
    "ai",
    "media",
    "files",
    "productivity",
    "notes",
    "documents",
    "reading",
    "finance",
    "development",
    "databases",
    "home",
    "network",
    "security",
    "monitoring",
    "downloads",
    "utilities",
]
CATEGORY_LABELS: dict[str, str] = {
    "ai": "AI",
    "media": "Media",
    "files": "Files & sync",
    "productivity": "Productivity",
    "notes": "Notes & knowledge",
    "documents": "Documents & PDF",
    "reading": "Bookmarks & reading",
    "finance": "Finance",
    "development": "Development",
    "databases": "Databases",
    "home": "Home automation",
    "network": "Network",
    "security": "Security",
    "monitoring": "Monitoring",
    "downloads": "Downloads",
    "utilities": "Utilities",
}

ENV_KEY = r"^[A-Z][A-Z0-9_]{0,63}$"
APP_ID = r"^[a-z0-9][a-z0-9-]{0,62}$"
PROFILE_ID = r"^[a-z0-9][a-z0-9-]{0,30}$"


class EnvField(BaseModel):
    key: str = Field(pattern=ENV_KEY)
    label: str
    description: str | None = None
    type: FieldType = "text"
    default: str | None = None
    """A literal, or a token: @timezone, @uid, @gid, @app_data, @app_data/<sub>."""
    required: bool = True
    options: list[str] | None = None
    """For type: select."""
    generate: Literal["secret", "hex16", "hex32"] | None = None
    """Fill an empty value with a random secret at install time: ``secret`` is 32 URL-safe
    characters, ``hex16``/``hex32`` are 16 or 32 random bytes as hex (32 or 64 characters),
    for apps that decode their key as hex (e.g. an AES key and IV)."""
    advanced: bool = False
    """Collapsed in the install form."""

    @field_validator("options")
    @classmethod
    def options_need_select(cls, value: list[str] | None, info) -> list[str] | None:
        if value is not None and not value:
            raise ValueError("options can't be empty")
        return value


class ProfileMeta(BaseModel):
    """An optional part of an app, switched on at install time (a Compose profile).

    The compose file puts the services of this part under ``profiles: [<id>]``; the
    install form lists a checkbox per entry and writes the chosen ids to ``.env`` as
    ``COMPOSE_PROFILES``, which Docker Compose reads on its own.
    """

    id: str = Field(pattern=PROFILE_ID)
    label: str
    description: str | None = None
    default: bool = False
    """Switched on in the install form unless the admin clears it."""
    requires: list[str] = Field(default_factory=list)
    """Host capabilities this part needs (e.g. ``docker-socket``); unmet ones disable it."""
    platforms: list[str] | None = None
    """CPUs this part runs on, when narrower than the app's."""
    env: dict[str, str] = Field(default_factory=dict)
    """Values written to ``.env`` while this part is on. The compose file reads them as
    ``${KEY:-default}``, so the app behaves as without the part when it is off."""


class AppMeta(BaseModel):
    title: str
    description: str
    category: Category
    icon: str | None = None
    homepage: str | None = None
    web_port: str | int | None = None
    """An env key holding the web port, or a fixed port number."""
    web_path: str = "/"
    platforms: list[str] = Field(default_factory=lambda: ["linux/amd64", "linux/arm64"])
    env: list[EnvField] = Field(default_factory=list)
    profiles: list[ProfileMeta] = Field(default_factory=list)
    """Optional parts of the app (Compose profiles) the admin can switch on."""
    notes: str | None = None
    """Shown on the app page, e.g. first-login instructions."""
    tagline: str | None = None
    """One short line for the store card and the popular banner."""
    tags: list[str] = Field(default_factory=list)
    """Small chips on the card, e.g. Movies, Transcoding."""
    features: list[str] = Field(default_factory=list)
    """Bullet points in the app page's "What you get" list."""
    screenshots: list[str] = Field(default_factory=list)
    """http(s) URLs shown in the app page's screenshot gallery."""
    license: str | None = None
    """SPDX-ish license name, shown in the app's details."""
    popular: bool = False
    """Feature in the store's front-page banner."""
    smoke: Literal["web", "start", "skip"] = "web"
    """What the runtime smoke test (``athena.catalog.smoke``) checks: ``web`` waits for
    the web port to answer, ``start`` only for the containers to keep running (apps
    without a reachable web page, e.g. host networking), ``skip`` doesn't run it."""
    smoke_note: str | None = None
    """Why ``smoke`` isn't ``web`` (e.g. "needs an NVIDIA GPU")."""

    @field_validator("tagline")
    @classmethod
    def tagline_is_short(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 90:
            raise ValueError("keep the tagline under 90 characters")
        return value

    @field_validator("tags")
    @classmethod
    def tags_are_small(cls, value: list[str]) -> list[str]:
        if len(value) > 6:
            raise ValueError("at most 6 tags")
        for tag in value:
            if not tag.strip() or len(tag) > 24:
                raise ValueError("each tag needs 1-24 characters")
        return value

    @field_validator("features")
    @classmethod
    def features_are_small(cls, value: list[str]) -> list[str]:
        if len(value) > 8:
            raise ValueError("at most 8 features")
        for feature in value:
            if not feature.strip() or len(feature) > 160:
                raise ValueError("each feature needs 1-160 characters")
        return value

    @field_validator("screenshots")
    @classmethod
    def screenshots_are_urls(cls, value: list[str]) -> list[str]:
        if len(value) > 6:
            raise ValueError("at most 6 screenshots")
        for url in value:
            if not url.startswith(("http://", "https://")):
                raise ValueError(f"screenshot {url!r} isn't an http(s) URL")
        return value


class CatalogAppVariant(BaseModel):
    slug: str
    """Filesystem-safe variant id (``default`` for ``compose.yaml``)."""
    label: str
    """Human-readable variant name shown in the install form."""
    compose: str
    images: list[str]
    """Every image the variant can pull, optional profiles included."""
    core_images: list[str] = Field(default_factory=list)
    """Images of the services that always run (no profile): these set the app's platforms."""
    web_port: str | int | None = None
    env: list[EnvField] = Field(default_factory=list)
    profiles_used: list[str] = Field(default_factory=list)
    """Profile ids the compose file's services belong to."""
    docker_access: bool = False
    """A service that always runs mounts the Docker socket."""
    docker_access_profiles: list[str] = Field(default_factory=list)
    """Profiles whose services mount the Docker socket."""


class CatalogApp(BaseModel):
    id: str = Field(pattern=APP_ID)
    catalog: str
    """Which catalog it came from ("builtin" or a remote catalog's id)."""
    meta: AppMeta
    variants: list[CatalogAppVariant]
    compose: str
    """The default variant's compose file, kept for backward compatibility."""
    images: list[str]
    """The default variant's images, kept for backward compatibility."""
    core_images: list[str] = Field(default_factory=list)
    files: dict[str, bytes] = Field(default_factory=dict, exclude=True)
    """Config files shipped in the app folder's ``files/``: path relative to it -> content.
    Installed next to compose.yaml, so the compose file reaches them as ``./files/<path>``."""


class InvalidCatalogAppError(ValueError):
    pass


_INTERP = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)")


def _slug_of(compose_file_name: str) -> str:
    """``compose.postgres.yaml`` -> ``postgres``; ``compose.yaml`` -> ``default``."""
    if compose_file_name == "compose.yaml":
        return "default"
    body = compose_file_name[len("compose.") : -len(".yaml")]
    return body or "default"


def _label_of(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").title() or "Default"


def _env_fields(raw: dict[str, Any], app_id: str) -> tuple[list[EnvField], list[str]]:
    env_raw = raw.get("env", []) or []
    fields: list[EnvField] = []
    keys: list[str] = []
    for entry in env_raw:
        try:
            field = EnvField.model_validate(entry)
        except ValidationError as exc:
            raise InvalidCatalogAppError(f"{app_id}: invalid env field: {exc}") from exc
        fields.append(field)
        keys.append(field.key)
    if len(keys) != len(set(keys)):
        raise InvalidCatalogAppError(f"{app_id}: duplicate env keys")
    return fields, keys


def _service_profiles(service: dict[str, Any]) -> list[str]:
    value = service.get("profiles") or []
    return [str(p) for p in value] if isinstance(value, list) else []


def _mounts_docker_socket(service: dict[str, Any]) -> bool:
    for volume in service.get("volumes") or []:
        text = volume if isinstance(volume, str) else " ".join(str(v) for v in volume.values())
        if "docker.sock" in text:
            return True
    return False


def _images_of(doc: dict[str, Any], app_id: str) -> list[str]:
    services = doc.get("services") or {}
    images = sorted({s.get("image", "") for s in services.values() if isinstance(s, dict)} - {""})
    if not images:
        raise InvalidCatalogAppError(f"{app_id}: no images")
    return images


def _variant(app_id: str, slug: str, text: str, doc: dict[str, Any]) -> CatalogAppVariant:
    """Parse a single ``compose.*.yaml`` file into an installable variant."""
    raw = doc.get("x-athena")
    if not isinstance(raw, dict):
        raise InvalidCatalogAppError(f"{app_id}: missing `x-athena` metadata")
    env_fields, keys = _env_fields(raw, app_id)
    for f in env_fields:
        if f.type == "select" and not f.options:
            raise InvalidCatalogAppError(f"{app_id}: {f.key} is a select without options")
    web_port = raw.get("web_port")
    if isinstance(web_port, str) and web_port not in keys:
        raise InvalidCatalogAppError(f"{app_id}: web_port {web_port} isn't an env key")

    # Every ${VAR} in the compose file must be an env field, a profile's env key, or
    # provided by Athena.
    profile_keys = {
        str(key)
        for entry in raw.get("profiles") or []
        if isinstance(entry, dict)
        for key in (entry.get("env") or {})
    }
    provided = {*keys, *profile_keys, "ATHENA_APP_DATA"}
    unknown = sorted({m for m in _INTERP.findall(text) if m not in provided})
    if unknown:
        raise InvalidCatalogAppError(f"{app_id}: undeclared variables {', '.join(unknown)}")

    services = [s for s in (doc.get("services") or {}).values() if isinstance(s, dict)]
    core = [s for s in services if not _service_profiles(s)]
    profiles_used = sorted({p for s in services for p in _service_profiles(s)})
    docker_profiles = sorted(
        {p for s in services if _mounts_docker_socket(s) for p in _service_profiles(s)}
    )
    return CatalogAppVariant(
        slug=slug,
        label=(raw.get("variant") or {}).get("label") or _label_of(slug),
        compose=text,
        images=_images_of(doc, app_id),
        core_images=sorted({s.get("image", "") for s in core} - {""}),
        web_port=web_port,
        env=env_fields,
        profiles_used=profiles_used,
        docker_access=any(_mounts_docker_socket(s) for s in core),
        docker_access_profiles=docker_profiles,
    )


def parse_app(app_id: str, catalog: str, docs: list[tuple[str, str, dict[str, Any]]]) -> CatalogApp:
    """Build a CatalogApp from one or more parsed compose documents.

    The first document is the default variant (``compose.yaml``); every additional
    ``compose.<slug>.yaml`` sibling is another installable variant of the same app.
    """
    if not docs:
        raise InvalidCatalogAppError(f"{app_id}: no compose files")
    _, default_text, default_doc = docs[0]
    raw = default_doc.get("x-athena")
    if not isinstance(raw, dict):
        raise InvalidCatalogAppError(f"{app_id}: missing `x-athena` metadata")
    try:
        meta = AppMeta.model_validate(raw)
    except ValidationError as exc:
        raise InvalidCatalogAppError(f"{app_id}: invalid x-athena: {exc}") from exc

    variants = [_variant(app_id, "default", default_text, default_doc)]
    for name, text, doc in docs[1:]:
        variants.append(_variant(app_id, _slug_of(name), text, doc))

    from athena.catalog.requirements import KNOWN_REQUIREMENTS

    for profile in meta.profiles:
        unknown = sorted(set(profile.requires) - set(KNOWN_REQUIREMENTS))
        if unknown:
            raise InvalidCatalogAppError(
                f"{app_id}: profile {profile.id} requires unknown {', '.join(unknown)}"
            )
    declared = [p.id for p in meta.profiles]
    if len(declared) != len(set(declared)):
        raise InvalidCatalogAppError(f"{app_id}: duplicate profile ids")
    for variant in variants:
        undeclared = sorted(set(variant.profiles_used) - set(declared))
        if undeclared:
            raise InvalidCatalogAppError(
                f"{app_id}: services use profiles {', '.join(undeclared)} that x-athena.profiles "
                "doesn't list, so nobody could switch them on"
            )
    unused = sorted(set(declared) - set(variants[0].profiles_used))
    if unused:
        raise InvalidCatalogAppError(
            f"{app_id}: profiles {', '.join(unused)} aren't used by any service"
        )

    return CatalogApp(
        id=app_id,
        catalog=catalog,
        meta=meta,
        variants=variants,
        compose=variants[0].compose,
        images=variants[0].images,
        core_images=variants[0].core_images,
    )
