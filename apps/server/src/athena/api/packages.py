"""Package managers: search, installed, upgradable, and install/uninstall/upgrade jobs.

Only managers in the capability manifest (`packages.<id>`) are offered, and changes need
the capability to be `ready` (docs/design/platform.md). Each manager runs one job at a
time, so two operations never fight over apt's or dnf's lock.
"""

import asyncio
import time
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response, status
from pydantic import BaseModel, Field

from athena import audit
from athena.auth.deps import AdminUser, Authed, DbSession
from athena.jobs import Job, JobManager, JobOut, run_or_fail
from athena.packages import MANAGERS, bootstrap, http
from athena.packages.base import (
    PACKAGE_NAME,
    SEARCH_QUERY,
    InstalledPackage,
    PackageDetails,
    PackageError,
    PackageManager,
    PackageRef,
    UpgradablePackage,
    command_env,
    resolve,
)
from athena.platform.capabilities import Capability, Status
from athena.platform.probe import Probe
from athena.platform.store import CapabilityStore

router = APIRouter(prefix="/packages", tags=["packages"])

ManagerId = Annotated[str, Path(pattern=r"^[a-z]{2,16}$")]
PackageName = Annotated[str, Field(pattern=PACKAGE_NAME.pattern)]
SOURCE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"


class ManagerOut(BaseModel):
    id: str
    label: str
    status: Status
    available: bool
    detail: str | None = None
    """The version when ready, or why it isn't (e.g. needs root)."""
    can_upgrade_one: bool
    can_refresh: bool
    note: str | None = None
    elevation: Literal["password", "system"] | None = None
    """Set when the admin's computer password lets Athena make changes (reads work without)."""
    has_logo: bool = False
    """The manager's own logo is at `/api/packages/{id}/logo`."""


class InstallIn(BaseModel):
    name: PackageName
    source: Annotated[str, Field(pattern=SOURCE_PATTERN)] | None = None
    """Flatpak remote, Scoop bucket, or "cask" for Homebrew casks."""
    password: str | None = Field(default=None, max_length=1024, repr=False)
    """The computer's password, when the manager says `elevation: "password"`. Used once for
    `sudo`, never stored or logged."""


class NameIn(BaseModel):
    name: PackageName
    password: str | None = Field(default=None, max_length=1024, repr=False)
    """The computer's password, when the manager says `elevation: "password"`. Used once for
    `sudo`, never stored or logged."""


class UpgradeIn(BaseModel):
    name: PackageName | None = None
    """Leave out to upgrade everything."""
    password: str | None = Field(default=None, max_length=1024, repr=False)
    """The computer's password, when the manager says `elevation: "password"`. Used once for
    `sudo`, never stored or logged."""


class RefreshIn(BaseModel):
    password: str | None = Field(default=None, max_length=1024, repr=False)
    """The computer's password, when the manager says `elevation: "password"`. Used once for
    `sudo`, never stored or logged."""


async def _capabilities(request: Request) -> list[Capability]:
    store: CapabilityStore = request.app.state.capabilities
    return (await store.get()).capabilities


def _out(cap: Capability, cls: type[PackageManager]) -> ManagerOut:
    return ManagerOut(
        id=cls.id,
        label=cls.label,
        status=cap.status,
        available=cap.available,
        detail=cap.detail,
        can_upgrade_one=cls.can_upgrade_one,
        can_refresh=cls.can_refresh,
        note=cls.note,
        elevation=cap.elevation if cap.status == "needs_privilege" else None,
        has_logo=bool(cls.logo_url),
    )


async def _manager(request: Request, manager: str) -> PackageManager:
    cls = MANAGERS.get(manager)
    caps = {c.id: c for c in await _capabilities(request)}
    cap = caps.get(f"packages.{manager}")
    if cls is None or cap is None or cap.status == "missing":
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{manager} isn't installed on this host")
    if not cap.available and not (cap.status == "needs_privilege" and cap.elevation == "password"):
        # With a password available, reads work as Athena's own user; changes ask for it.
        raise HTTPException(status.HTTP_409_CONFLICT, cap.detail or f"{cls.label} isn't ready")
    return cls(request.app.state.package_runner)


async def _change_manager(
    request: Request, manager: str, password: str | None
) -> tuple[PackageManager, str | None]:
    """The manager for an action that changes the host, and the password to run it with
    (`None` when Athena already has the rights)."""
    pm = await _manager(request, manager)
    cap = next(c for c in await _capabilities(request) if c.id == f"packages.{manager}")
    if cap.available:
        return pm, None
    if not password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Enter your computer's password to continue")
    return pm, password


async def _read(coro):
    try:
        return await coro
    except PackageError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.get("", operation_id="listPackageManagers")
async def list_managers(request: Request) -> list[ManagerOut]:
    """The package managers found on this host (ready or not), in detection order."""
    return [
        _out(cap, MANAGERS[cap.id.removeprefix("packages.")])
        for cap in await _capabilities(request)
        if cap.id.startswith("packages.")
        and cap.status != "missing"
        and cap.id.removeprefix("packages.") in MANAGERS
    ]


# ---------------------------------------------------------------- add a package manager

InstallerId = Annotated[str, Path(pattern=r"^[a-z]{2,16}$")]


class BootstrapIn(BaseModel):
    password: str | None = Field(default=None, max_length=1024, repr=False)
    """The computer's password (sudo), when `needs_password` says so. Used once."""


def _probe(request: Request) -> Probe:
    """The host probe (tests replace it through `app.state.package_probe`)."""
    return getattr(request.app.state, "package_probe", None) or Probe()


def _installer(installer: str) -> bootstrap.Installer:
    inst = bootstrap.INSTALLERS.get(installer)
    if inst is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Athena can't install {installer}")
    return inst


@router.get("/installable", operation_id="listInstallablePackageManagers")
async def list_installable(request: Request, user: AdminUser) -> list[bootstrap.InstallableOut]:
    """Package managers this host doesn't have but Athena can install, with what each needs."""
    caps = {c.id: c for c in await _capabilities(request)}
    return await asyncio.to_thread(bootstrap.installable, _probe(request), caps)


@router.get(
    "/installable/{installer}/logo",
    operation_id="getInstallablePackageManagerLogo",
    response_class=Response,
)
async def installable_logo(installer: InstallerId, user: AdminUser) -> Response:
    """The logo from the manager's own site, for the "Add a package manager" list."""
    inst = _installer(installer)
    return _image(*await _read(http.fetch_image(inst.logo_url, inst.hosts)))


@router.post(
    "/installable/{installer}/install",
    operation_id="installPackageManager",
    status_code=status.HTTP_202_ACCEPTED,
)
async def install_manager(
    installer: InstallerId, body: BootstrapIn, request: Request, user: AdminUser, db: DbSession
) -> JobOut:
    """Download the vendor's official installer and run it as a job. Re-detects when done."""
    inst = _installer(installer)
    store: CapabilityStore = request.app.state.capabilities
    caps = {c.id: c for c in await _capabilities(request)}
    probe = _probe(request)
    offered = {i.id: i for i in await asyncio.to_thread(bootstrap.installable, probe, caps)}
    if inst.id not in offered:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{inst.label} can't be installed here")
    if not offered[inst.id].ready:
        unmet = next(r for r in offered[inst.id].requirements if not r.met)
        raise HTTPException(status.HTTP_409_CONFLICT, f"{unmet.label}: {unmet.hint or 'not met'}")
    try:
        password = bootstrap.password_for(probe, inst, body.password)
    except PackageError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc

    busy: dict[str, str] = request.app.state.package_jobs
    jobs: JobManager = request.app.state.jobs
    current = busy.get("bootstrap")
    if current and (running := jobs.get(current)) and running.status == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Busy: {running.title}. Wait for it.")

    async def run(job: Job) -> None:
        try:
            await bootstrap.run_installer(job, inst, probe, caps, password, store.refresh)
        finally:
            busy.pop("bootstrap", None)

    audit.record(db, user.user.username, "package.bootstrap", inst.id)
    job = jobs.start(f"Install {inst.label}", run)
    busy["bootstrap"] = job.id
    return job.out()


@router.get("/{manager}/search", operation_id="searchPackages")
async def search(
    manager: ManagerId,
    request: Request,
    q: Annotated[str, Query(pattern=SEARCH_QUERY.pattern)],
) -> list[PackageRef]:
    return await _read((await _manager(request, manager)).find(q.strip()))


INFO_TTL = 600.0
_info_cache: dict[tuple[str, str, str | None], tuple[float, PackageDetails]] = {}


async def _details(
    request: Request, manager: str, name: str, source: str | None
) -> tuple[PackageManager, PackageDetails]:
    pm = await _manager(request, manager)
    key = (manager, name, source)
    if (hit := _info_cache.get(key)) and hit[0] > time.monotonic():
        return pm, hit[1]
    details = await _read(pm.details(name, source))
    if len(_info_cache) > 200:
        _info_cache.clear()
    _info_cache[key] = (time.monotonic() + INFO_TTL, details)
    return pm, details


@router.get("/{manager}/info", operation_id="getPackageInfo")
async def info(
    manager: ManagerId,
    request: Request,
    name: Annotated[str, Query(pattern=PACKAGE_NAME.pattern)],
    source: Annotated[str, Query(pattern=SOURCE_PATTERN)] | None = None,
) -> PackageDetails:
    """What the manager knows about one package. Whether it is installed is never cached."""
    pm, details = await _details(request, manager, name, source)
    fresh = details.model_copy()
    try:
        have = {p.name: p.version for p in await pm.installed()}
    except PackageError:
        return fresh
    fresh.installed = name in have
    fresh.installed_version = have.get(name)
    return fresh


def _image(content: bytes, kind: str) -> Response:
    # The bytes only change when the store changes them, so browsers may keep them a day.
    return Response(content, media_type=kind, headers={"Cache-Control": "private, max-age=86400"})


@router.get("/{manager}/icon", operation_id="getPackageIcon", response_class=Response)
async def icon(
    manager: ManagerId,
    request: Request,
    name: Annotated[str, Query(pattern=PACKAGE_NAME.pattern)],
    source: Annotated[str, Query(pattern=SOURCE_PATTERN)] | None = None,
) -> Response:
    """The package's icon from the manager's own store, fetched by the server (404 if none)."""
    pm, details = await _details(request, manager, name, source)
    if not details.icon_url:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This package has no icon")
    return _image(*await _read(http.fetch_image(details.icon_url, pm.image_hosts())))


@router.get("/{manager}/logo", operation_id="getPackageManagerLogo", response_class=Response)
async def logo(manager: ManagerId, request: Request) -> Response:
    """The manager's own logo from its official site (404 if it has none)."""
    pm = await _manager(request, manager)
    if not pm.logo_url:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{pm.label} has no logo")
    return _image(*await _read(http.fetch_image(pm.logo_url, pm.image_hosts())))


@router.get("/{manager}/installed", operation_id="listInstalledPackages")
async def installed(manager: ManagerId, request: Request) -> list[InstalledPackage]:
    return await _read((await _manager(request, manager)).installed())


@router.get("/{manager}/upgradable", operation_id="listUpgradablePackages")
async def upgradable(manager: ManagerId, request: Request) -> list[UpgradablePackage]:
    """From the package lists as last refreshed (apt, dnf and others cache them)."""
    return await _read((await _manager(request, manager)).upgradable())


# ---------------------------------------------------------------- changes (jobs)

Action = Literal["install", "uninstall", "upgrade", "refresh"]


def _start(
    request: Request,
    pm: PackageManager,
    action: Action,
    argv: list[str],
    title: str,
    user: Authed,
    db: DbSession,
    target: str,
    password: str | None = None,
) -> JobOut:
    busy: dict[str, str] = request.app.state.package_jobs
    jobs: JobManager = request.app.state.jobs
    current = busy.get(pm.id)
    if current and (job := jobs.get(current)) and job.status == "running":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{pm.label} is busy: {job.title}. Wait for it to finish."
        )

    stdin = None
    if password:  # the host account's password, for `sudo` only; it isn't logged or stored
        argv = ["sudo", "-S", "-k", "-p", "", *argv]
        stdin = password + "\n"

    async def body(job: Job) -> None:
        try:
            await run_or_fail(job, resolve(argv), title, env=command_env(pm.env), stdin=stdin)
        finally:
            busy.pop(pm.id, None)

    audit.record(db, user.user.username, f"package.{action}", f"{pm.id}:{target}")
    job = jobs.start(title, body)
    busy[pm.id] = job.id
    return job.out()


@router.post(
    "/{manager}/install", operation_id="installPackage", status_code=status.HTTP_202_ACCEPTED
)
async def install(
    manager: ManagerId, body: InstallIn, request: Request, user: Authed, db: DbSession
) -> JobOut:
    pm, password = await _change_manager(request, manager, body.password)
    argv = pm.install_argv(body.name, body.source)
    title = f"Install {body.name}"
    return _start(request, pm, "install", argv, title, user, db, body.name, password)


@router.post(
    "/{manager}/uninstall", operation_id="uninstallPackage", status_code=status.HTTP_202_ACCEPTED
)
async def uninstall(
    manager: ManagerId, body: NameIn, request: Request, user: Authed, db: DbSession
) -> JobOut:
    pm, password = await _change_manager(request, manager, body.password)
    argv = pm.uninstall_argv(body.name)
    title = f"Uninstall {body.name}"
    return _start(request, pm, "uninstall", argv, title, user, db, body.name, password)


@router.post(
    "/{manager}/upgrade", operation_id="upgradePackages", status_code=status.HTTP_202_ACCEPTED
)
async def upgrade(
    manager: ManagerId, body: UpgradeIn, request: Request, user: Authed, db: DbSession
) -> JobOut:
    pm, password = await _change_manager(request, manager, body.password)
    if body.name and not pm.can_upgrade_one:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{pm.label} can only upgrade everything at once. {pm.note or ''}".strip(),
        )
    title = f"Upgrade {body.name}" if body.name else f"Upgrade all {pm.label} packages"
    target = body.name or "*"
    argv = pm.upgrade_argv(body.name)
    return _start(request, pm, "upgrade", argv, title, user, db, target, password)


@router.post(
    "/{manager}/refresh", operation_id="refreshPackageLists", status_code=status.HTTP_202_ACCEPTED
)
async def refresh(
    manager: ManagerId,
    request: Request,
    user: Authed,
    db: DbSession,
    body: RefreshIn | None = None,
) -> JobOut:
    """Update the package lists (apt update, dnf makecache…) so search and upgrades are current."""
    pm, password = await _change_manager(request, manager, body.password if body else None)
    argv = pm.refresh_argv()
    if argv is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{pm.label} has no separate list refresh")
    title = f"Refresh {pm.label} package lists"
    return _start(request, pm, "refresh", argv, title, user, db, "-", password)
