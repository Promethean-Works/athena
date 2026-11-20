"""The app store: browse catalogs and install apps. All routes need a session."""

import asyncio
import re
import shutil
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Query, Request, status
from pydantic import BaseModel, Field
from sqlmodel import select

from athena import audit
from athena.api.apps import deploy_new_app
from athena.api.containers import RuntimeDep
from athena.apps.store import APP_NAME, AppStore
from athena.auth.deps import Authed, DbSession
from athena.catalog import remote
from athena.catalog.loader import (
    InstallValueError,
    env_file,
    form_defaults,
    resolve_values,
)
from athena.catalog.model import APP_ID, CATEGORY_LABELS, CatalogApp, EnvField, FieldType
from athena.catalog.platforms import Support, host_platform, support
from athena.catalog.registry import BUILTIN, CatalogRegistry
from athena.db.models import App, Catalog
from athena.jobs import Job, JobManager, JobOut
from athena.platform.capabilities import CapabilityManifest
from athena.platform.store import CapabilityStore

router = APIRouter(prefix="/store", tags=["store"])

CatalogName = Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")]
AppId = Annotated[str, Path(pattern=APP_ID)]


class Category(BaseModel):
    id: str
    label: str
    count: int


class StoreApp(BaseModel):
    catalog: str
    catalog_name: str
    id: str
    title: str
    description: str
    tagline: str | None
    category: str
    category_label: str
    tags: list[str]
    popular: bool
    cover: str | None
    """The first screenshot, used as the card's cover image."""
    icon: str | None
    installed: list[str]
    """Names of Athena apps installed from this catalog app."""
    support: Support
    """Whether the app's images run on this host's CPU: natively, under emulation
    (Docker Desktop on an arm64 Mac or Windows PC), or not at all."""


class FormField(BaseModel):
    key: str
    label: str
    description: str | None
    type: FieldType
    default: str
    """Resolved default for the suggested app name (passwords: empty, generated on install)."""
    required: bool
    options: list[str] | None
    generated: bool
    advanced: bool


class VariantDetail(BaseModel):
    slug: str
    label: str
    compose: str
    images: list[str]
    web_port: str | int | None = None
    fields: list[FormField]


class StoreAppDetail(StoreApp):
    homepage: str | None
    notes: str | None
    platforms: list[str]
    host_platform: str | None
    """This host's CPU as a container platform (``linux/arm64``), None if unknown."""
    images: list[str]
    web_port: str | int | None
    features: list[str]
    screenshots: list[str]
    license: str | None
    suggested_name: str
    fields: list[FormField]
    compose: str
    variants: list[VariantDetail]
    """Every installable variant of this app, each with its own compose file."""


class InstallIn(BaseModel):
    name: str = Field(pattern=APP_NAME, max_length=63)
    values: dict[str, str] = Field(default_factory=dict)
    variant: str | None = None
    """Which compose variant to install; defaults to the app's default variant."""


def _registry(request: Request) -> CatalogRegistry:
    return request.app.state.catalogs


def _get(request: Request, catalog: str, app_id: str) -> CatalogApp:
    app = _registry(request).get(catalog, app_id)
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No store app {catalog}/{app_id}")
    return app


async def _manifest(request: Request) -> CapabilityManifest:
    capabilities: CapabilityStore = request.app.state.capabilities
    return await capabilities.get()


def _support(app: CatalogApp, manifest: CapabilityManifest) -> Support:
    return support(app.meta.platforms, manifest.os, manifest.arch)


def _installed(db: DbSession) -> dict[str, list[str]]:
    by_catalog_id: dict[str, list[str]] = {}
    for app in db.exec(select(App).where(App.catalog_id.is_not(None))).all():  # type: ignore[union-attr]
        by_catalog_id.setdefault(app.catalog_id or "", []).append(app.name)
    return by_catalog_id


def _catalog_names(db: DbSession) -> dict[str, str]:
    return {BUILTIN: "Athena", **{c.id: c.name for c in db.exec(select(Catalog)).all()}}


def _summary(
    app: CatalogApp,
    installed: dict[str, list[str]],
    manifest: CapabilityManifest,
    names: dict[str, str] | None = None,
) -> StoreApp:
    return StoreApp(
        catalog=app.catalog,
        catalog_name=(names or {}).get(app.catalog, app.catalog),
        id=app.id,
        title=app.meta.title,
        description=app.meta.description,
        tagline=app.meta.tagline,
        category=app.meta.category,
        category_label=CATEGORY_LABELS.get(app.meta.category, app.meta.category),
        tags=app.meta.tags,
        popular=app.meta.popular,
        cover=app.meta.screenshots[0] if app.meta.screenshots else None,
        icon=app.meta.icon,
        installed=sorted(installed.get(f"{app.catalog}/{app.id}", [])),
        support=_support(app, manifest),
    )


def _field(f: EnvField, default: str) -> FormField:
    return FormField(
        key=f.key,
        label=f.label,
        description=f.description,
        type=f.type,
        default="" if f.generate == "secret" else default,
        required=f.required and f.generate != "secret",
        options=f.options,
        generated=f.generate == "secret",
        advanced=f.advanced,
    )


@router.get("/categories", operation_id="listStoreCategories")
def categories(request: Request) -> list[Category]:
    counts: dict[str, int] = {}
    for app in _registry(request).all():
        counts[app.meta.category] = counts.get(app.meta.category, 0) + 1
    return [
        Category(id=cat, label=label, count=counts[cat])
        for cat, label in CATEGORY_LABELS.items()
        if counts.get(cat)
    ]


@router.get("/apps", operation_id="listStoreApps")
async def list_store_apps(
    request: Request,
    db: DbSession,
    q: Annotated[str, Query(max_length=100)] = "",
    category: Annotated[str | None, Query(max_length=32)] = None,
) -> list[StoreApp]:
    needle = q.strip().lower()
    installed = _installed(db)
    names = _catalog_names(db)
    manifest = await _manifest(request)
    return [
        _summary(app, installed, manifest, names)
        for app in _registry(request).all()
        if (category is None or app.meta.category == category)
        and (
            not needle
            or needle in app.meta.title.lower()
            or needle in app.meta.description.lower()
            or needle in (app.meta.tagline or "").lower()
            or any(needle in tag.lower() for tag in app.meta.tags)
            or needle in app.id
        )
    ]


@router.get("/apps/{catalog}/{app_id}", operation_id="getStoreApp")
async def get_store_app(
    catalog: CatalogName, app_id: AppId, request: Request, db: DbSession
) -> StoreAppDetail:
    app = _get(request, catalog, app_id)
    manifest = await _manifest(request)
    taken = {a.name for a in db.exec(select(App)).all()}
    name, n = app.id, 2
    while name in taken:
        name, n = f"{app.id}-{n}", n + 1
    store = AppStore(request.app.state.settings.data_dir)
    data_dir = store.dir(name) / "data"
    defaults = form_defaults(app.meta.env, data_dir)
    variants = []
    for variant in app.variants:
        variant_defaults = form_defaults(variant.env, data_dir)
        variants.append(
            VariantDetail(
                slug=variant.slug,
                label=variant.label,
                compose=variant.compose,
                images=variant.images,
                web_port=variant.web_port,
                fields=[_field(f, variant_defaults[f.key]) for f in variant.env],
            )
        )
    return StoreAppDetail(
        **_summary(app, _installed(db), manifest, _catalog_names(db)).model_dump(),
        homepage=app.meta.homepage,
        notes=app.meta.notes,
        platforms=app.meta.platforms,
        host_platform=host_platform(manifest.arch),
        images=app.images,
        web_port=app.meta.web_port,
        features=app.meta.features,
        screenshots=app.meta.screenshots,
        license=app.meta.license,
        suggested_name=name,
        fields=[_field(f, defaults[f.key]) for f in app.meta.env],
        compose=app.compose,
        variants=variants,
    )


@router.post(
    "/apps/{catalog}/{app_id}/install",
    operation_id="installStoreApp",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        409: {"description": "The app's images don't run on this host's CPU"},
        422: {"description": "Invalid values: detail.errors maps field keys to messages"},
    },
)
async def install(
    catalog: CatalogName,
    app_id: AppId,
    body: InstallIn,
    request: Request,
    runtime: RuntimeDep,
    user: Authed,
    db: DbSession,
) -> JobOut:
    """Write compose.yaml and .env from the install form, then deploy as a job."""
    app = _get(request, catalog, app_id)
    manifest = await _manifest(request)
    if _support(app, manifest) == "unsupported":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{app.meta.title} doesn't run on this host: it's published for "
            f"{', '.join(app.meta.platforms) or 'no platform'}, and this host is "
            f"{host_platform(manifest.arch)}.",
        )
    slug = body.variant or "default"
    variant = next((v for v in app.variants if v.slug == slug), None)
    if variant is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"No variant {slug!r} for store app {catalog}/{app_id}"
        )
    data_dir = AppStore(request.app.state.settings.data_dir).dir(body.name) / "data"
    try:
        values = resolve_values(variant.env, body.values, data_dir)
    except InstallValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"message": "Some values need fixing", "errors": exc.errors},
        ) from exc
    return deploy_new_app(
        request,
        runtime,
        user,
        db,
        name=body.name,
        compose_text=variant.compose,
        source="catalog",
        env_text=env_file(values),
        catalog_id=f"{app.catalog}/{app.id}",
    )


# ---------------------------------------------------------------- catalogs

CatalogKind = Literal["auto", "athena", "casaos"]


class CatalogOut(BaseModel):
    id: str
    name: str
    url: str | None
    kind: str
    builtin: bool
    app_count: int
    refreshed_at: datetime | None
    error: str | None


class NewCatalog(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=8, max_length=500)
    kind: CatalogKind = "auto"


def _catalog_dir(request: Request, catalog_id: str):
    return request.app.state.settings.data_dir / "catalogs" / catalog_id


def _slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50] or "catalog"
    if base == BUILTIN:
        base = "builtin-2"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


def _catalog_out(row: Catalog) -> CatalogOut:
    return CatalogOut(
        id=row.id,
        name=row.name,
        url=row.url,
        kind=row.kind,
        builtin=False,
        app_count=row.app_count,
        refreshed_at=row.refreshed_at,
        error=row.error,
    )


def _refresh_job(request: Request, row: Catalog) -> JobOut:
    jobs: JobManager = request.app.state.jobs
    registry = _registry(request)
    database = request.app.state.db
    dest = _catalog_dir(request, row.id)
    catalog_id, url, kind = row.id, row.url, row.kind

    async def body(job: Job) -> None:
        loop = asyncio.get_running_loop()

        def log(line: str) -> None:
            asyncio.run_coroutine_threadsafe(job.log(line), loop)

        error: str | None = None
        count = 0
        try:
            count = await asyncio.to_thread(remote.refresh, url, kind, catalog_id, dest, log)
        except (remote.CatalogFetchError, ValueError) as exc:
            error = str(exc)
        registry.reload()
        with database.engine.begin() as conn:
            conn.exec_driver_sql(
                "UPDATE catalogs SET app_count = ?, refreshed_at = ?, error = ? WHERE id = ?",
                (registry.count(catalog_id), datetime.now(UTC).isoformat(), error, catalog_id),
            )
        if error:
            raise RuntimeError(error)
        await job.log(f"Store now lists {count} apps from {catalog_id}")

    return jobs.start(f"Refresh catalog {row.name}", body).out()


@router.get("/catalogs", operation_id="listCatalogs")
def list_catalogs(request: Request, db: DbSession) -> list[CatalogOut]:
    builtin = CatalogOut(
        id=BUILTIN,
        name="Athena",
        url=None,
        kind="athena",
        builtin=True,
        app_count=_registry(request).count(BUILTIN),
        refreshed_at=None,
        error=None,
    )
    rows = db.exec(select(Catalog).order_by(Catalog.created_at)).all()
    return [builtin, *(_catalog_out(r) for r in rows)]


@router.post("/catalogs", operation_id="addCatalog", status_code=status.HTTP_202_ACCEPTED)
async def add_catalog(body: NewCatalog, request: Request, user: Authed, db: DbSession) -> JobOut:
    """Add a remote catalog and download it (a job). GitHub, Codeberg and GitLab repository
    URLs work, as do direct .tar.gz/.zip links. Format: Athena or CasaOS AppStore."""
    try:
        remote.archive_url(body.url)
    except remote.CatalogFetchError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    if db.exec(select(Catalog).where(Catalog.url == body.url.strip())).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "That catalog is already added")
    taken = {c.id for c in db.exec(select(Catalog)).all()}
    row = Catalog(
        id=_slug(body.name, taken), name=body.name.strip(), url=body.url.strip(), kind=body.kind
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.record(db, user.user.username, "catalog.add", row.id, row.url)
    return _refresh_job(request, row)


@router.post(
    "/catalogs/{catalog_id}/refresh",
    operation_id="refreshCatalog",
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_catalog(
    catalog_id: CatalogName, request: Request, user: Authed, db: DbSession
) -> JobOut:
    row = db.get(Catalog, catalog_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such catalog")
    audit.record(db, user.user.username, "catalog.refresh", row.id)
    return _refresh_job(request, row)


@router.delete(
    "/catalogs/{catalog_id}", operation_id="removeCatalog", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_catalog(
    catalog_id: CatalogName, request: Request, user: Authed, db: DbSession
) -> None:
    """Forget a catalog. Apps already installed from it keep running."""
    row = db.get(Catalog, catalog_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such catalog")
    db.delete(row)
    db.commit()
    shutil.rmtree(_catalog_dir(request, catalog_id), ignore_errors=True)
    _registry(request).reload()
    audit.record(db, user.user.username, "catalog.remove", catalog_id)
