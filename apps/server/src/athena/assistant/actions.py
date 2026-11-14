"""The assistant's tools that change things (docs/mvp-design.md §4.5, part B).

Each one is registered with `requires_approval=True`, so the model can only *ask*: the run
pauses, the admin sees an Approve/Deny card with `summarize()`'s sentence and the exact
arguments, and the tool runs only after Approve. They call the same route helpers the UI
does, so validation, one-job-per-resource and audit are the same; a tool that starts a job
waits for it and reports how it went.
"""

import asyncio
from typing import Annotated, Any, Literal

from pydantic import Field
from pydantic_ai import ToolFailed
from sqlmodel import Session

from athena.apps.store import APP_NAME
from athena.assistant.tools import CATALOG_NAME, MANAGER_ID, Ctx, _http
from athena.catalog.model import APP_ID
from athena.files import locations
from athena.files.ops import MAX_TEXT, OnConflict
from athena.files.paths import FileError
from athena.jobs import JobOut
from athena.packages.base import PACKAGE_NAME

JOB_WAIT_SECONDS = 15 * 60
"""How long a tool waits for its job before telling the model it's still running."""
LOG_TAIL = 30

AppName = Annotated[str, Field(pattern=APP_NAME, max_length=63)]
CatalogName = Annotated[str, Field(pattern=CATALOG_NAME)]
AppId = Annotated[str, Field(pattern=APP_ID)]
ManagerId = Annotated[str, Field(pattern=MANAGER_ID)]
PackageName = Annotated[str, Field(pattern=PACKAGE_NAME.pattern)]
PackageSource = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
RelPath = Annotated[str, Field(max_length=4096)]
Paths = Annotated[list[Annotated[str, Field(min_length=1, max_length=4096)]], Field(min_length=1)]


async def _follow(ctx: Ctx, started: JobOut) -> dict[str, Any]:
    """Wait for a job the tool started. The chat gets a `job` event at once, so the
    card can show the live log while this waits."""
    job = ctx.deps.app.state.jobs.get(started.id)
    if job is None:  # pragma: no cover - jobs are kept for a while after finishing
        return {"job_id": started.id, "status": "unknown"}
    ctx.deps.emit("job", {"id": ctx.tool_call_id, "job_id": job.id, "title": job.title})
    try:
        await asyncio.wait_for(job.wait(), JOB_WAIT_SECONDS)
    except TimeoutError:
        return {
            "job_id": job.id,
            "status": "running",
            "note": f"{job.title} is still running. It will finish on its own.",
        }
    tail = job.lines[-LOG_TAIL:]
    if job.status == "failed":
        log = "\n".join(tail)
        raise ToolFailed(f"{job.title} failed: {job.error}\nLast log lines:\n{log}")
    return {"job_id": job.id, "status": job.status, "title": job.title, "log": tail}


# ---------------------------------------------------------------- apps and the store


async def install_store_app(
    ctx: Ctx,
    catalog: CatalogName,
    app_id: AppId,
    name: AppName,
    values: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Install an app from the store and deploy it. `name` is the new app's name (use
    get_store_app's suggested_name unless asked otherwise); `values` fills the install
    form by field key. Leave out a field to use its default; passwords are generated."""
    from athena.api import store

    body = store.InstallIn(name=name, values=values or {})
    d = ctx.deps
    started = await _http(
        store.install(catalog, app_id, body, d.request(), d.runtime(), d.user, d.db)
    )
    return await _follow(ctx, started)


async def create_app(
    ctx: Ctx, name: AppName, compose: Annotated[str, Field(min_length=1, max_length=256 * 1024)]
) -> dict[str, Any]:
    """Create a new app from a Docker Compose file (YAML) and deploy it."""
    from athena.api import apps

    body = apps.NewApp(name=name, compose=compose)
    d = ctx.deps
    started = await _http(apps.create_app(body, d.request(), d.runtime(), d.user, d.db))
    return await _follow(ctx, started)


async def change_app(
    ctx: Ctx, name: AppName, action: Literal["start", "stop", "restart", "update"]
) -> dict[str, Any]:
    """Start, stop or restart an app, or update it (pull newer images and recreate)."""
    from athena.api import apps

    d = ctx.deps
    started = await _http(apps.app_action(name, action, d.request(), d.runtime(), d.user, d.db))
    return await _follow(ctx, started)


async def remove_app(ctx: Ctx, name: AppName, delete_data: bool = False) -> dict[str, Any]:
    """Stop and remove an app. With delete_data, also delete its volumes and its folder,
    including its data: that can't be undone."""
    from athena.api import apps

    d = ctx.deps
    started = await _http(
        apps.delete_app(name, d.request(), d.runtime(), d.user, d.db, delete_data=delete_data)
    )
    return await _follow(ctx, started)


# ---------------------------------------------------------------- packages


async def install_package(
    ctx: Ctx, manager: ManagerId, name: PackageName, source: PackageSource | None = None
) -> dict[str, Any]:
    """Install a host package with a package manager (see list_package_managers).
    `source` is a Flatpak remote, a Scoop bucket, or "cask" for a Homebrew cask."""
    from athena.api import packages

    d = ctx.deps
    body = packages.InstallIn(name=name, source=source)
    started = await _http(packages.install(manager, body, d.request(), d.user, d.db))
    return await _follow(ctx, started)


async def uninstall_package(ctx: Ctx, manager: ManagerId, name: PackageName) -> dict[str, Any]:
    """Uninstall a host package."""
    from athena.api import packages

    d = ctx.deps
    body = packages.NameIn(name=name)
    started = await _http(packages.uninstall(manager, body, d.request(), d.user, d.db))
    return await _follow(ctx, started)


async def upgrade_packages(
    ctx: Ctx, manager: ManagerId, name: PackageName | None = None
) -> dict[str, Any]:
    """Upgrade one package, or every package of that manager when `name` is left out."""
    from athena.api import packages

    d = ctx.deps
    body = packages.UpgradeIn(name=name)
    started = await _http(packages.upgrade(manager, body, d.request(), d.user, d.db))
    return await _follow(ctx, started)


# ---------------------------------------------------------------- files


async def write_text_file(
    ctx: Ctx,
    location_id: int,
    path: Annotated[str, Field(min_length=1, max_length=4096)],
    content: Annotated[str, Field(max_length=MAX_TEXT)],
) -> dict[str, Any]:
    """Replace the whole content of an existing text file (read it first with
    read_text_file)."""
    from athena.api import files

    body = files.TextIn(location=location_id, path=path, content=content)
    saved = await _http(files.write_text(body, ctx.deps.db))
    return {"path": saved.path, "saved": True}


async def create_folder(ctx: Ctx, location_id: int, path: RelPath, name: str) -> dict[str, Any]:
    """Create a folder called `name` inside `path` ("" for the location itself)."""
    from athena.api import files

    body = files.NewFolderIn(location=location_id, path=path, name=name)
    entry = await _http(files.create_folder(body, ctx.deps.db))
    return entry.model_dump(mode="json", include={"name", "path", "kind"})


async def rename_file(
    ctx: Ctx,
    location_id: int,
    path: Annotated[str, Field(min_length=1, max_length=4096)],
    new_name: str,
) -> dict[str, Any]:
    """Rename a file or folder in place (`new_name` is a name, not a path)."""
    from athena.api import files

    body = files.RenameIn(location=location_id, path=path, name=new_name)
    entry = await _http(files.rename(body, ctx.deps.db))
    return entry.model_dump(mode="json", include={"name", "path", "kind"})


async def delete_files(
    ctx: Ctx, location_id: int, paths: Paths, permanent: bool = False
) -> dict[str, Any]:
    """Move files or folders to the trash, or delete them for good with `permanent`."""
    from athena.api import files

    body = files.DeleteIn(location=location_id, paths=paths, permanent=permanent)
    out = await _http(files.delete(body, ctx.deps.user, ctx.deps.db))
    if out.errors and not out.deleted:
        raise ToolFailed("; ".join(f"{e.path}: {e.error}" for e in out.errors))
    return out.model_dump()


async def copy_or_move_files(
    ctx: Ctx,
    op: Literal["copy", "move"],
    location_id: int,
    paths: Paths,
    dest_location_id: int,
    dest_path: RelPath = "",
    on_conflict: OnConflict = "rename",
) -> dict[str, Any]:
    """Copy or move files or folders into the folder `dest_path` of a location (maybe
    another one). When a name is taken: "rename" adds " (1)", "skip" leaves it, and
    "overwrite" replaces a file."""
    from athena.api import files

    body = files.TransferIn(
        op=op,
        location=location_id,
        paths=paths,
        dest_location=dest_location_id,
        dest_path=dest_path,
        on_conflict=on_conflict,
    )
    started = await _http(files.transfer(body, ctx.deps.request(), ctx.deps.user, ctx.deps.db))
    return await _follow(ctx, started)


APP_ACTIONS = [install_store_app, create_app, change_app, remove_app]
PACKAGE_ACTIONS = [install_package, uninstall_package, upgrade_packages]
FILE_ACTIONS = [write_text_file, create_folder, rename_file, delete_files, copy_or_move_files]
NAMES = frozenset(fn.__name__ for fn in (*APP_ACTIONS, *PACKAGE_ACTIONS, *FILE_ACTIONS))


# ---------------------------------------------------------------- approval cards


def _where(db: Session, location_id: Any, path: Any = "") -> str:
    try:
        name = locations.get(db, int(location_id)).name
    except (FileError, TypeError, ValueError):
        name = f"location {location_id}"
    rel = str(path or "").strip("/")
    return f"{name}/{rel}" if rel else name


def _items(paths: Any) -> str:
    paths = [str(p) for p in paths] if isinstance(paths, list) else [str(paths)]
    shown = ", ".join(paths[:5])
    return shown + (f" and {len(paths) - 5} more" if len(paths) > 5 else "")


def summarize(db: Session, name: str, args: Any) -> str | None:
    """One sentence for the approval card, or None for a tool that needs no approval."""
    if name not in NAMES:
        return None
    a: dict[str, Any] = args if isinstance(args, dict) else {}
    match name:
        case "install_store_app":
            return f"Install {a.get('catalog')}/{a.get('app_id')} from the store as {a.get('name')}"
        case "create_app":
            return f"Create the app {a.get('name')} from a compose file and deploy it"
        case "change_app":
            verb = {"update": "Update (pull and recreate)"}.get(a.get("action", ""), "")
            return f"{verb or str(a.get('action', 'Change')).capitalize()} the app {a.get('name')}"
        case "remove_app":
            data = " and delete all its data" if a.get("delete_data") else " (its data is kept)"
            return f"Remove the app {a.get('name')}{data}"
        case "install_package":
            source = f" from {a['source']}" if a.get("source") else ""
            return f"Install the package {a.get('name')}{source} with {a.get('manager')}"
        case "uninstall_package":
            return f"Uninstall the package {a.get('name')} with {a.get('manager')}"
        case "upgrade_packages":
            if a.get("name"):
                return f"Upgrade the package {a['name']} with {a.get('manager')}"
            return f"Upgrade every {a.get('manager')} package"
        case "write_text_file":
            return f"Replace the content of {_where(db, a.get('location_id'), a.get('path'))}"
        case "create_folder":
            inside = _where(db, a.get("location_id"), a.get("path"))
            return f"Create the folder {a.get('name')} in {inside}"
        case "rename_file":
            where = _where(db, a.get("location_id"), a.get("path"))
            return f"Rename {where} to {a.get('new_name')}"
        case "delete_files":
            how = "Permanently delete" if a.get("permanent") else "Move to the trash"
            return f"{how} {_items(a.get('paths', []))} in {_where(db, a.get('location_id'))}"
        case "copy_or_move_files":
            verb = "Move" if a.get("op") == "move" else "Copy"
            src = _where(db, a.get("location_id"))
            dest = _where(db, a.get("dest_location_id"), a.get("dest_path"))
            return f"{verb} {_items(a.get('paths', []))} from {src} to {dest}"
    return None  # pragma: no cover - every name in NAMES has a case


DESTRUCTIVE = frozenset({"remove_app", "uninstall_package", "delete_files", "write_text_file"})


def is_destructive(name: str, args: Any) -> bool:
    """Cards for these get the destructive style."""
    a: dict[str, Any] = args if isinstance(args, dict) else {}
    if name == "copy_or_move_files":
        return a.get("op") == "move" or a.get("on_conflict") == "overwrite"
    return name in DESTRUCTIVE
