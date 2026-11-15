"""The assistant's tools: Athena's own service layer, filtered by the capability manifest
(docs/mvp-design.md §4.5). Everything here only reads; the tools that change things are in
`actions.py` and need the admin's approval.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic_ai import FunctionToolset, RunContext, Tool, ToolFailed
from sqlmodel import Session, select

from athena.auth.deps import CurrentUser
from athena.catalog.model import APP_ID
from athena.containers import service as containers
from athena.containers.runtime import Runtime, RuntimeUnavailableError, runtime_from
from athena.containers.service import ContainerError
from athena.db.models import App
from athena.files import locations, ops
from athena.files.paths import FileError, resolve, root_of
from athena.packages.base import SEARCH_QUERY
from athena.platform.capabilities import CapabilityManifest

MAX_LOG_LINES = 300
MAX_LOG_CHARS = 20_000
MAX_FILE_ENTRIES = 200
MAX_TEXT_CHARS = 20_000
MAX_STORE_APPS = 50
MAX_PACKAGES = 50
CATALOG_NAME = r"^[a-z0-9][a-z0-9-]{0,62}$"
MANAGER_ID = r"^[a-z]{2,16}$"


@dataclass
class Deps:
    app: FastAPI
    db: Session
    user: CurrentUser
    """The admin chatting; actions run (and are audited) as them."""
    manifest: CapabilityManifest
    emit: Callable[[str, Any], None] = lambda event, data: None
    """Sends an extra event to the chat stream (the `job` a tool started)."""
    shell_commands: tuple[str, ...] = ()
    """The shell allowlist when the assistant shell is on (Settings → AI); empty when off."""
    memory: bool = True
    """Whether the assistant keeps notes across chats (Settings → AI)."""

    @property
    def username(self) -> str:
        return self.user.user.username

    def request(self) -> Request:
        """A bare request whose `.app` is the server, for helpers written for routes."""
        return Request({"type": "http", "app": self.app, "headers": []})

    def runtime(self) -> Runtime:
        try:
            return runtime_from(self.manifest.get("containers"))
        except RuntimeUnavailableError as exc:
            raise ToolFailed(str(exc)) from exc


Ctx = RunContext[Deps]


# ---------------------------------------------------------------- always available


async def get_capabilities(ctx: Ctx) -> dict[str, Any]:
    """What this server is and what it can do: OS, and each feature with its status
    (ready, stopped, missing, unsupported, needs_privilege) and details."""
    m = ctx.deps.manifest
    return {
        "os": m.os,
        "os_version": m.os_version,
        "arch": m.arch,
        "capabilities": [
            {"id": c.id, "label": c.label, "status": c.status, "detail": c.detail}
            for c in m.capabilities
        ],
    }


async def get_system_stats(ctx: Ctx) -> dict[str, Any]:
    """Current host stats: CPU, memory, swap, network and disk rates, disks, load,
    temperatures and boot time. Rates are bytes per second; sizes are bytes."""
    monitor = ctx.deps.app.state.monitor
    snapshot = await monitor.snapshot()
    return snapshot.model_dump(exclude={"history"})


# ---------------------------------------------------------------- containers


async def list_apps(ctx: Ctx) -> list[dict[str, Any]]:
    """The apps Athena manages (compose projects), with status, running/total containers
    and published ports."""
    from athena.api.apps import _summarize

    rows = ctx.deps.db.exec(select(App).order_by(App.name)).all()
    if not rows:
        return []
    try:
        found = await asyncio.to_thread(containers.list_containers, ctx.deps.runtime())
    except ContainerError as exc:
        raise ToolFailed(str(exc)) from exc
    request = ctx.deps.request()
    return [
        _summarize(request, row, found).model_dump(
            mode="json", include={"name", "title", "status", "running", "total", "ports"}
        )
        for row in rows
    ]


async def app_logs(ctx: Ctx, name: str, lines: int = 100) -> list[dict[str, str]]:
    """The last `lines` log lines (at most 300) of each container in the app `name`."""
    lines = max(1, min(lines, MAX_LOG_LINES))
    if ctx.deps.db.exec(select(App).where(App.name == name)).first() is None:
        raise ToolFailed(f"No app named {name!r}. Call list_apps for the names.")
    runtime = ctx.deps.runtime()
    try:
        found = await asyncio.to_thread(containers.list_containers, runtime)
        # One text per container under `content`, the field the prompt injection defender
        # reads (it skips lists of strings; see assistant/safety.py).
        out: list[dict[str, str]] = []
        budget = MAX_LOG_CHARS
        for c in (c for c in found if c.project == name):
            got = await asyncio.to_thread(containers.logs, runtime, c.name, lines)
            kept: list[str] = []
            for line in reversed(got):  # keep the newest lines when over budget
                budget -= len(line) + 1
                if budget < 0:
                    break
                kept.append(line)
            out.append({"container": c.name, "content": "\n".join(reversed(kept))})
    except ContainerError as exc:
        raise ToolFailed(str(exc)) from exc
    if not out:
        raise ToolFailed(f"{name} has no containers (it isn't deployed).")
    return out


# ---------------------------------------------------------------- files


async def list_file_locations(ctx: Ctx) -> list[dict[str, Any]]:
    """The folders the file manager can browse, with their ids for list_files."""
    return [
        {"id": loc.id, "name": loc.name, "path": loc.path}
        for loc in locations.all_locations(ctx.deps.db)
    ]


async def list_files(ctx: Ctx, location_id: int, path: str = "") -> dict[str, Any]:
    """The entries of a folder inside a file location. `path` is relative to the
    location, with `/` separators; "" is the location itself. At most 200 entries."""
    try:
        loc = locations.get(ctx.deps.db, location_id)
        root = root_of(loc.path)
        listing = await asyncio.to_thread(ops.list_dir, root, resolve(root, path))
    except (FileError, OSError) as exc:
        raise ToolFailed(str(exc)) from exc
    entries = [
        e.model_dump(mode="json", include={"name", "kind", "size", "modified"})
        for e in listing.entries[:MAX_FILE_ENTRIES]
    ]
    return {
        "location": loc.name,
        "path": path,
        "entries": entries,
        "truncated": len(listing.entries) > MAX_FILE_ENTRIES,
    }


async def read_text_file(ctx: Ctx, location_id: int, path: str) -> dict[str, Any]:
    """A text file's content (at most 20,000 characters) inside a file location."""
    try:
        loc = locations.get(ctx.deps.db, location_id)
        root = root_of(loc.path)
        text = await asyncio.to_thread(ops.read_text, root, resolve(root, path))
    except (FileError, OSError) as exc:
        raise ToolFailed(str(exc)) from exc
    content = text.content
    cut = len(content) > MAX_TEXT_CHARS
    return {"path": text.path, "content": content[:MAX_TEXT_CHARS], "truncated": cut}


# ---------------------------------------------------------------- store


async def search_store(ctx: Ctx, query: str = "", category: str | None = None) -> dict[str, Any]:
    """Apps in the app store matching `query` (title, description or id; "" for all),
    optionally in one category. At most 50. `installed` lists Athena apps made from it."""
    from athena.api import store

    found = _call(store.list_store_apps, ctx.deps.request(), ctx.deps.db, query[:100], category)
    return {
        "apps": [
            a.model_dump(include={"catalog", "id", "title", "description", "category", "installed"})
            for a in found[:MAX_STORE_APPS]
        ],
        "truncated": len(found) > MAX_STORE_APPS,
    }


async def get_store_app(ctx: Ctx, catalog: str, app_id: str) -> dict[str, Any]:
    """One store app: its install form (fields with defaults, required ones, choices),
    the suggested app name, notes and images. Call this before install_store_app."""
    from athena.api import store

    _check(catalog, CATALOG_NAME, "catalog")
    _check(app_id, APP_ID, "app id")
    app = _call(store.get_store_app, catalog, app_id, ctx.deps.request(), ctx.deps.db)
    return app.model_dump(exclude={"compose", "icon"})


# ---------------------------------------------------------------- packages


async def list_package_managers(ctx: Ctx) -> list[dict[str, Any]]:
    """The host's package managers (apt, brew, winget…) with their status."""
    from athena.api import packages

    found = await packages.list_managers(ctx.deps.request())
    return [m.model_dump() for m in found]


async def search_packages(ctx: Ctx, manager: str, query: str) -> list[dict[str, Any]]:
    """Search a package manager (its id from list_package_managers). At most 50 results."""
    from athena.api import packages

    _check(manager, MANAGER_ID, "manager")
    _check(query.strip(), SEARCH_QUERY.pattern, "query")
    pm = await _http(packages._manager(ctx.deps.request(), manager))
    found = await _http(packages._read(pm.search(query.strip())))
    return [p.model_dump() for p in found[:MAX_PACKAGES]]


async def list_upgradable_packages(ctx: Ctx, manager: str) -> list[dict[str, Any]]:
    """Packages with an update, from the lists as last refreshed."""
    from athena.api import packages

    _check(manager, MANAGER_ID, "manager")
    pm = await _http(packages._manager(ctx.deps.request(), manager))
    found = await _http(packages._read(pm.upgradable()))
    return [p.model_dump() for p in found[:MAX_PACKAGES]]


# ---------------------------------------------------------------- helpers


async def _http[T](work: Awaitable[T]) -> T:
    """Run a route helper; its HTTP errors become the tool's failure message."""
    try:
        return await work
    except HTTPException as exc:
        raise ToolFailed(http_detail(exc)) from exc


def _call[T](fn: Callable[..., T], *args: Any) -> T:
    """`_http` for a route helper that isn't async (they use the chat's database session,
    so they run on the event loop, not in a thread)."""
    try:
        return fn(*args)
    except HTTPException as exc:
        raise ToolFailed(http_detail(exc)) from exc


def http_detail(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        errors = detail.get("errors") or {}
        lines = [str(detail.get("message", "Invalid values"))]
        lines += [f"- {key}: {msg}" for key, msg in errors.items()]
        return "\n".join(lines)
    return str(detail)


def _check(value: str, pattern: str, what: str) -> None:
    if not re.fullmatch(pattern, value):
        raise ToolFailed(f"That isn't a valid {what}: {value!r}")


def _has_packages(manifest: CapabilityManifest) -> bool:
    return any(c.id.startswith("packages.") and c.available for c in manifest.capabilities)


def shell_provider(manifest: CapabilityManifest) -> str | None:
    """posix, wsl or powershell (the `assistant.shell` capability), or None."""
    cap = manifest.get("assistant.shell")
    return cap.provider if cap is not None and cap.available else None


def _ready(manifest: CapabilityManifest, capability: str) -> bool:
    cap = manifest.get(capability)
    return cap is not None and cap.available


def read_only_tools(manifest: CapabilityManifest) -> list[Any]:
    """The tools that only read, for what this host supports right now. They're all a
    delegated helper gets (`delegation.py`)."""
    tools: list[Any] = [get_capabilities, get_system_stats]
    if _ready(manifest, "containers"):
        tools += [list_apps, app_logs, search_store, get_store_app]
    if _ready(manifest, "files"):
        tools += [list_file_locations, list_files, read_text_file]
    if _has_packages(manifest):
        tools += [list_package_managers, search_packages, list_upgradable_packages]
    return tools


def toolset_for(
    manifest: CapabilityManifest, shell_commands: tuple[str, ...] = ()
) -> FunctionToolset[Deps]:
    """The tools this host supports right now. Tools that change something (from
    `actions.py`) need the admin's approval for every call. The PowerShell `run_command` is
    here only on Windows hosts without WSL, with the shell on and a non-empty allowlist."""
    from athena.assistant import actions

    tools = read_only_tools(manifest)
    changes: list[Any] = []
    if _ready(manifest, "containers"):
        changes += actions.APP_ACTIONS
    if _ready(manifest, "files"):
        changes += actions.FILE_ACTIONS
    if _has_packages(manifest):
        changes += actions.PACKAGE_ACTIONS
    approved = [Tool(fn, requires_approval=True) for fn in changes]
    # Linux, macOS and WSL get the harness Shell as capabilities (`workspace.py`); a Windows
    # host without WSL gets the PowerShell `run_command` here.
    if shell_commands and shell_provider(manifest) == "powershell":
        listed = ", ".join(shell_commands)
        doc = actions.run_command.__doc__ or ""
        approved.append(
            Tool(actions.run_command, description=f"{doc}\n\nAllowed programs: {listed}.")
        )
    return FunctionToolset([*tools, *approved])
