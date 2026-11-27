"""Athena-managed apps (compose projects). All routes need a session (see main.py)."""

import asyncio
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path as FsPath
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Query, Request, status
from pydantic import BaseModel, Field
from sqlmodel import Session, delete, select

from athena import audit
from athena.api.containers import RuntimeDep
from athena.apps import docker_run
from athena.apps.store import APP_NAME, AppStore, InvalidComposeError, compose, parse_compose
from athena.auth.deps import Authed, DbSession, require_admin
from athena.catalog import profiles as catalog_profiles
from athena.catalog.loader import InstallValueError, env_file
from athena.catalog.model import CatalogApp
from athena.catalog.platforms import host_platform
from athena.containers import service as containers
from athena.containers.runtime import Runtime
from athena.containers.service import ContainerError, ContainerOut
from athena.db.models import App
from athena.jobs import Job, JobManager, JobOut, run_or_fail

router = APIRouter(prefix="/apps", tags=["apps"])

AppName = Annotated[str, Path(pattern=APP_NAME, max_length=63)]
AppStatus = Literal["running", "partial", "stopped", "not_deployed"]


class AppOut(BaseModel):
    name: str
    source: str
    catalog_id: str | None = None
    """Store app id for apps installed from a catalog."""
    web_port: int | None = None
    """The port "Open" should use, when the catalog declares one."""
    title: str | None = None
    """The store app's display name (e.g. "Home Assistant"), for catalog apps."""
    icon: str | None = None
    """The store app's icon URL, for catalog apps."""
    status: AppStatus
    running: int
    total: int
    ports: list[str]
    """Host ports published by the app's containers, e.g. "8080→80/tcp"."""
    created_at: datetime
    updated_at: datetime


class AppDetail(AppOut):
    compose: str
    env: str | None
    """The app's .env file (install-form values for store apps), if it has one."""
    containers: list[ContainerOut]
    profiles: list[catalog_profiles.ProfileState] = []
    """Optional parts of a store app (browser, sandbox, …), with which are on."""
    docker_access: bool = False
    """Something that always runs mounts the Docker socket."""


class ComposeIn(BaseModel):
    compose: str = Field(max_length=256 * 1024)


class NewApp(ComposeIn):
    name: str = Field(pattern=APP_NAME, max_length=63)
    source: Literal["compose", "docker-run"] = "compose"


class ConvertIn(BaseModel):
    command: str = Field(min_length=1, max_length=16 * 1024)


class ConvertOut(BaseModel):
    compose: str
    service: str
    warnings: list[str]


class ValidateOut(BaseModel):
    ok: bool
    errors: list[str]


Action = Literal["start", "stop", "restart", "update"]

# What each action runs, after `--project-name <name> --file <compose.yaml>`.
ACTIONS: dict[Action, list[list[str]]] = {
    "start": [["up", "--detach", "--remove-orphans"]],
    "stop": [["stop"]],
    "restart": [["restart"]],
    "update": [["pull"], ["up", "--detach", "--remove-orphans"]],
}


def _store(request: Request) -> AppStore:
    return AppStore(request.app.state.settings.data_dir)


def _jobs(request: Request) -> JobManager:
    return request.app.state.jobs


def _busy(request: Request) -> dict[str, str]:
    """app name -> id of its running job (one at a time per app)."""
    return request.app.state.app_jobs


def _get_app(db: DbSession, name: str) -> App:
    app = db.exec(select(App).where(App.name == name)).first()
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No app named {name!r}")
    return app


def _catalog_entry(request: Request, app: App) -> CatalogApp | None:
    if not app.catalog_id or "/" not in app.catalog_id:
        return None
    catalog, app_id = app.catalog_id.split("/", 1)
    return request.app.state.catalogs.get(catalog, app_id)


def _web_port(request: Request, app: App, entry: CatalogApp | None) -> int | None:
    """Catalog apps declare their web port (a number, or an env key in their .env)."""
    if entry is None or entry.meta.web_port is None:
        return None
    port = entry.meta.web_port
    if isinstance(port, str):
        port = _store(request).read_env(app.name).get(port, "")
    return int(port) if str(port).isdigit() else None


def _summarize(request: Request, app: App, all_containers: list[ContainerOut]) -> AppOut:
    mine = [c for c in all_containers if c.project == app.name]
    running = sum(c.state == "running" for c in mine)
    state: AppStatus = (
        "not_deployed"
        if not mine
        else "running"
        if running == len(mine)
        else "stopped"
        if running == 0
        else "partial"
    )
    ports = sorted({p for c in mine for p in c.ports})
    # The catalog can be removed after install; the app then just loses its icon and title.
    entry = _catalog_entry(request, app)
    return AppOut(
        name=app.name,
        source=app.source,
        catalog_id=app.catalog_id,
        web_port=_web_port(request, app, entry),
        title=entry.meta.title if entry else None,
        icon=entry.meta.icon if entry else None,
        status=state,
        running=running,
        total=len(mine),
        ports=ports,
        created_at=app.created_at,
        updated_at=app.updated_at,
    )


async def _containers(runtime: Runtime) -> list[ContainerOut]:
    try:
        return await asyncio.to_thread(containers.list_containers, runtime)
    except ContainerError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


def _start_job(
    request: Request, name: str, title: str, body, *, user_visible: bool = False
) -> JobOut:
    busy = _busy(request)
    jobs = _jobs(request)
    current = busy.get(name)
    if current and (job := jobs.get(current)) and job.status == "running":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{name} is busy: {job.title}. Wait for it to finish."
        )

    async def wrapped(job: Job) -> None:
        try:
            await body(job)
        finally:
            busy.pop(name, None)

    job = jobs.start(title, wrapped, user_visible=user_visible)
    busy[name] = job.id
    return job.out()


async def _validate_with_cli(runtime: Runtime, store: AppStore, name: str, text: str) -> list[str]:
    """`docker compose config --quiet` on a temporary copy. Returns error lines."""
    with tempfile.TemporaryDirectory() as tmp:
        path = FsPath(tmp) / "compose.yaml"
        path.write_text(text, encoding="utf-8")
        proc = await asyncio.create_subprocess_exec(
            *compose(runtime, name, path, "config", "--quiet"),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL,
            env=store.env(name),
        )
        out, _ = await proc.communicate()
    if proc.returncode == 0:
        return []
    lines = [ln.strip() for ln in out.decode(errors="replace").splitlines() if ln.strip()]
    return lines or [f"docker compose config failed (exit code {proc.returncode})"]


# ---------------------------------------------------------------- read


@router.get("", operation_id="listApps")
async def list_apps(request: Request, runtime: RuntimeDep, db: DbSession) -> list[AppOut]:
    apps = db.exec(select(App).order_by(App.name)).all()
    if not apps:
        return []
    all_containers = await _containers(runtime)
    return [_summarize(request, a, all_containers) for a in apps]


@router.get("/{name}", operation_id="getApp", dependencies=[require_admin])
async def get_app(name: AppName, request: Request, runtime: RuntimeDep, db: DbSession) -> AppDetail:
    app = _get_app(db, name)
    all_containers = await _containers(runtime)
    summary = _summarize(request, app, all_containers)
    catalog_app = _catalog_app(request, app)
    profiles: list[catalog_profiles.ProfileState] = []
    if catalog_app is not None and catalog_app.meta.profiles:
        manifest = await request.app.state.capabilities.get()
        enabled = catalog_profiles.enabled_in(_store(request).read_env(name))
        profiles = catalog_profiles.states(
            catalog_app, manifest, host_platform(manifest.arch), enabled
        )
    return AppDetail(
        **summary.model_dump(),
        compose=_store(request).read(name),
        env=_store(request).read_env_text(name),
        containers=[c for c in all_containers if c.project == name],
        profiles=profiles,
        docker_access=catalog_app.variants[0].docker_access if catalog_app else False,
    )


# ---------------------------------------------------------------- authoring helpers


@router.post("/convert", operation_id="convertDockerRun", dependencies=[require_admin])
def convert_docker_run(body: ConvertIn) -> ConvertOut:
    """Turn a `docker run …` command into a compose file to review before deploying."""
    try:
        result = docker_run.convert(body.command)
    except docker_run.ConversionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return ConvertOut(compose=result.compose, service=result.service, warnings=result.warnings)


@router.post("/validate", operation_id="validateCompose", dependencies=[require_admin])
async def validate_compose(
    body: ComposeIn,
    request: Request,
    runtime: RuntimeDep,
    name: Annotated[str, Query(pattern=APP_NAME, max_length=63)] = "athena-validate",
) -> ValidateOut:
    try:
        parse_compose(body.compose)
    except InvalidComposeError as exc:
        return ValidateOut(ok=False, errors=[str(exc)])
    errors = await _validate_with_cli(runtime, _store(request), name, body.compose)
    return ValidateOut(ok=not errors, errors=errors)


# ---------------------------------------------------------------- write


def _deploy_body(
    runtime: Runtime,
    store: AppStore,
    name: str,
    path: FsPath,
    pull: bool,
    remove: list[str] | None = None,
):
    """``remove``: services to stop and delete first (a profile that was just switched off:
    ``up --remove-orphans`` leaves their containers running)."""

    async def body(job: Job) -> None:
        env = store.env(name)
        await job.log(f"App directory: {path.parent}")
        steps = [
            ["config", "--quiet"],
            *([["rm", "--stop", "--force", *remove]] if remove else []),
            *([["pull"]] if pull else []),
            ["up", "--detach", "--remove-orphans"],
        ]
        for args in steps:
            code = await job.run_command(compose(runtime, name, path, *args), env=env)
            if code != 0:
                raise RuntimeError(f"docker compose {args[0]} failed (exit code {code})")

    return body


def _catalog_app(request: Request, app: App) -> CatalogApp | None:
    """The store app a catalog-installed app came from, if that catalog still has it."""
    catalog, _, app_id = (app.catalog_id or "").partition("/")
    return request.app.state.catalogs.get(catalog, app_id) if app_id else None


def deploy_new_app(
    request: Request,
    runtime: Runtime,
    user: Authed,
    db: DbSession,
    *,
    name: str,
    compose_text: str,
    source: str,
    env_text: str | None = None,
    catalog_id: str | None = None,
    files: dict[str, bytes] | None = None,
    detail: str | None = None,
) -> JobOut:
    """Save an app's files, record it, and start its deploy job (shared with the store)."""
    if db.exec(select(App).where(App.name == name)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"An app named {name!r} exists")
    try:
        parse_compose(compose_text)
    except InvalidComposeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    store = _store(request)
    path = store.write(name, compose_text)
    if env_text is not None:
        store.write_env(name, env_text)
    if files:
        store.write_files(name, files)
    db.add(App(name=name, source=source, catalog_id=catalog_id))
    db.commit()
    audit.record(
        db,
        user.user.username,
        "app.create",
        name,
        f"{catalog_id or source} ({detail})" if detail else catalog_id or source,
    )
    return _start_job(
        request, name, f"Deploy {name}", _deploy_body(runtime, store, name, path, True)
    )


@router.post(
    "", operation_id="createApp", dependencies=[require_admin], status_code=status.HTTP_202_ACCEPTED
)
async def create_app(
    body: NewApp, request: Request, runtime: RuntimeDep, user: Authed, db: DbSession
) -> JobOut:
    """Save the compose file and deploy it. Follow progress at /api/jobs/{id}/events."""
    return deploy_new_app(
        request, runtime, user, db, name=body.name, compose_text=body.compose, source=body.source
    )


@router.put(
    "/{name}",
    operation_id="updateAppCompose",
    dependencies=[require_admin],
    status_code=status.HTTP_202_ACCEPTED,
)
async def update_compose(
    name: AppName,
    body: ComposeIn,
    request: Request,
    runtime: RuntimeDep,
    user: Authed,
    db: DbSession,
) -> JobOut:
    """Replace the compose file (the old one is kept as compose.prev.yaml) and redeploy."""
    app = _get_app(db, name)
    try:
        parse_compose(body.compose)
    except InvalidComposeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    store = _store(request)
    path = store.write(name, body.compose)
    app.updated_at = datetime.now(UTC)
    db.add(app)
    db.commit()
    audit.record(db, user.user.username, "app.edit", name)
    return _start_job(
        request, name, f"Redeploy {name}", _deploy_body(runtime, store, name, path, False)
    )


class EnvIn(BaseModel):
    env: str = Field(max_length=64 * 1024)


_ENV_LINE = re.compile(r"^\s*(#.*)?$|^[A-Za-z_][A-Za-z0-9_]*=.*$")


@router.put(
    "/{name}/env",
    operation_id="updateAppEnv",
    dependencies=[require_admin],
    status_code=status.HTTP_202_ACCEPTED,
)
async def update_env(
    name: AppName,
    body: EnvIn,
    request: Request,
    runtime: RuntimeDep,
    user: Authed,
    db: DbSession,
) -> JobOut:
    """Replace the app's .env (e.g. change a store app's port or folder) and redeploy."""
    app = _get_app(db, name)
    bad = [i + 1 for i, line in enumerate(body.env.splitlines()) if not _ENV_LINE.match(line)]
    if bad:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Lines {', '.join(map(str, bad[:5]))} aren't KEY=value, a comment or blank",
        )
    store = _store(request)
    store.write_env(name, body.env if body.env.endswith("\n") else body.env + "\n")
    app.updated_at = datetime.now(UTC)
    db.add(app)
    db.commit()
    audit.record(db, user.user.username, "app.env", name)
    return _start_job(
        request,
        name,
        f"Redeploy {name}",
        _deploy_body(runtime, store, name, store.compose_path(name), False),
    )


class ProfilesIn(BaseModel):
    profiles: list[str] = Field(max_length=32)


def _services_of(compose_text: str, profile: str) -> list[str]:
    doc = parse_compose(compose_text)
    return [
        service
        for service, spec in doc["services"].items()
        if profile in (spec.get("profiles") or [])
    ]


@router.put(
    "/{name}/profiles",
    operation_id="updateAppProfiles",
    dependencies=[require_admin],
    status_code=status.HTTP_202_ACCEPTED,
)
async def update_profiles(
    name: AppName,
    body: ProfilesIn,
    request: Request,
    runtime: RuntimeDep,
    user: Authed,
    db: DbSession,
) -> JobOut:
    """Switch a store app's optional parts (browser, sandbox, …) on or off and redeploy."""
    app = _get_app(db, name)
    catalog_app = _catalog_app(request, app)
    if catalog_app is None or not catalog_app.meta.profiles:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{name} has no optional parts to switch")
    manifest = await request.app.state.capabilities.get()
    try:
        chosen = catalog_profiles.choose(
            catalog_app, body.profiles, manifest, host_platform(manifest.arch)
        )
    except InstallValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"message": "Some values need fixing", "errors": exc.errors},
        ) from exc
    store = _store(request)
    before = catalog_profiles.enabled_in(store.read_env(name))
    env = store.read_env(name)
    for key in catalog_profiles.profile_keys(catalog_app):
        env.pop(key, None)
    env.update(catalog_profiles.env_for(catalog_app, chosen))
    store.write_env(name, env_file(env))
    removed = [
        service
        for pid in sorted(before - set(chosen))
        for service in _services_of(store.read(name), pid)
    ]
    app.updated_at = datetime.now(UTC)
    db.add(app)
    db.commit()
    audit.record(db, user.user.username, "app.profiles", name, detail=",".join(chosen) or "none")
    return _start_job(
        request,
        name,
        f"Update {name}",
        _deploy_body(runtime, store, name, store.compose_path(name), False, removed),
    )


@router.post("/{name}/{action}", operation_id="appAction", status_code=status.HTTP_202_ACCEPTED)
async def app_action(
    name: AppName,
    action: Action,
    request: Request,
    runtime: RuntimeDep,
    user: Authed,
    db: DbSession,
) -> JobOut:
    """start (up -d), stop, restart, or update (pull + up -d). Only admins can update."""
    if action == "update" and not user.user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can update apps")
    return start_app_action(name, action, request, runtime, user.user.username, db)


def start_app_action(
    name: str,
    action: str,
    request: Request,
    runtime: Runtime,
    username: str,
    db: Session,
    detail: str | None = None,
) -> JobOut:
    """Start an app's lifecycle job and audit it (shared with the MCP server)."""
    _get_app(db, name)
    store = _store(request)
    path = store.compose_path(name)

    async def body(job: Job) -> None:
        for args in ACTIONS[action]:
            await run_or_fail(
                job,
                compose(runtime, name, path, *args),
                f"docker compose {args[0]}",
                env=store.env(name),
            )

    audit.record(db, username, f"app.{action}", name, detail=detail)
    # Plain users may start, stop and restart apps, so they may follow that job; installs,
    # updates and removals are admin routes and their logs stay admin-only.
    return _start_job(request, name, f"{action.capitalize()} {name}", body, user_visible=True)


@router.delete(
    "/{name}",
    operation_id="deleteApp",
    dependencies=[require_admin],
    status_code=status.HTTP_202_ACCEPTED,
)
async def delete_app(
    name: AppName,
    request: Request,
    runtime: RuntimeDep,
    user: Authed,
    db: DbSession,
    delete_data: bool = False,
) -> JobOut:
    """`compose down` and forget the app. With delete_data, also remove its volumes and
    the app directory (including data/)."""
    _get_app(db, name)
    store = _store(request)
    path = store.compose_path(name)
    database = request.app.state.db

    async def body(job: Job) -> None:
        args = ["down", "--remove-orphans", *(["--volumes"] if delete_data else [])]
        await run_or_fail(
            job,
            compose(runtime, name, path, *args),
            "docker compose down",
            env=store.env(name),
        )
        store.remove(name, delete_data)
        with Session(database.engine) as session:
            session.exec(delete(App).where(App.name == name))
            session.commit()
        await job.log(
            "Removed the app and its data."
            if delete_data
            else f"Removed the app. Its data/ folder was kept in {store.dir(name)}."
        )

    audit.record(db, user.user.username, "app.delete", name, "with data" if delete_data else None)
    return _start_job(request, name, f"Remove {name}", body)
