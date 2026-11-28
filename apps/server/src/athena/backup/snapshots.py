"""Taking snapshots (docs/specs/backup.md): one restic snapshot per item of a plan.

The users' files (`<data-dir>/users/`) are snapshotted as they are, with the tag `users`.
Athena itself is staged first (a consistent copy of the database through SQLite's online
backup API, never the live file) and snapshotted with the tag `athena`. Each app's folder
is snapshotted with the tag `app:<name>`, after stopping the app (unless the plan says to
back it up while running) and always starting it again, even when the backup fails or the
job is cancelled.
"""

import asyncio
import contextlib
import json
import logging
import os
import platform
import shutil
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml
from sqlmodel import Session, select

from athena import __version__
from athena.apps.store import AppStore, compose
from athena.backup import restic
from athena.backup.plans import PlanApp, PlanItems
from athena.backup.repository import looks_like_repository
from athena.backup.restic import Repository, Restic, ResticError, _environment
from athena.config import SETTINGS_FILE
from athena.containers import service as containers
from athena.containers.runtime import Runtime
from athena.crypto import KEY_FILE
from athena.db.models import App
from athena.jobs import Job, run_or_fail

log = logging.getLogger(__name__)

SNAPSHOT_HOST = "athena"
"""A fixed host name, so a snapshot's parent is found again after the host is renamed or
the data is restored onto new hardware (restic matches parents by host and path)."""

ATHENA_TAG = "athena"
USERS_TAG = "users"


def app_tag(name: str) -> str:
    return f"app:{name}"


class DestinationNotConnectedError(Exception):
    """The destination can't be reached right now (an unplugged USB disk): skip the run."""


@dataclass
class ItemResult:
    item: str
    error: str | None = None
    snapshot_id: str | None = None
    warning: str | None = None
    nothing_to_back_up: bool = False
    """No snapshot was taken because there was nothing to take (no retention to apply)."""


def staging_dir(data_dir: Path) -> Path:
    return data_dir / "cache" / "backup" / "athena"


def stage_athena(data_dir: Path, target: Path) -> None:
    """Copy what a restore of Athena needs into `target` (emptied first).

    `athena.db` goes through the SQLite backup API; `athena.json`, `secret.key` and
    `tls/` are copied. `athena.json.bak`, `athena.schema.json`, `bin/`, logs and caches are
    left out: they're written or downloaded again.
    """
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    with contextlib.suppress(OSError):
        target.chmod(0o700)  # it holds a copy of secret.key
    source = sqlite3.connect(f"file:{(data_dir / 'athena.db').as_posix()}?mode=ro", uri=True)
    try:
        copy = sqlite3.connect(target / "athena.db")
        try:
            source.backup(copy)
        finally:
            copy.close()
    finally:
        source.close()
    for name in (SETTINGS_FILE, KEY_FILE):
        if (data_dir / name).is_file():
            shutil.copy2(data_dir / name, target / name)
    if (data_dir / "tls").is_dir():
        shutil.copytree(data_dir / "tls", target / "tls")


def snapshot_tags(*tags: str) -> list[str]:
    """`--tag` arguments: the item's tag, the Athena version and the OS the version came from."""
    tags = (*tags, f"athena-version:{__version__}", f"os:{platform.system().lower()}")
    return [arg for tag in tags for arg in ("--tag", tag)]


def _progress(message: dict) -> tuple[float | None, str]:
    done, total = int(message.get("bytes_done") or 0), int(message.get("total_bytes") or 0)
    files_done, files = int(message.get("files_done") or 0), int(message.get("total_files") or 0)
    text = f"{_size(done)} of {_size(total)}" if total else _size(done)
    if files:
        text += f" · {files_done} of {files} files"
    fraction = message.get("percent_done")
    return (float(fraction) if isinstance(fraction, int | float) else None), text


def _size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


async def backup_folder(
    tool: Restic, repo: Repository, job: Job, folder: Path, tags: list[str], label: str
) -> ItemResult:
    """`restic backup` one folder, reporting progress. Raises `ResticError` on failure."""
    summary: dict = {}

    async def on_line(line: str) -> None:
        try:
            message = json.loads(line)
        except ValueError:
            return
        if not isinstance(message, dict):
            return
        if message.get("message_type") == "status":
            fraction, text = _progress(message)
            await job.set_progress(fraction, f"{label}: {text}")
        elif message.get("message_type") == "summary":
            summary.update(message)

    result = await tool.stream(
        repo,
        "backup",
        "--json",
        "--host",
        SNAPSHOT_HOST,
        *tags,
        str(folder),
        on_line=on_line,
    )
    out = ItemResult(label, snapshot_id=summary.get("snapshot_id"))
    if result.code == restic.EXIT_INCOMPLETE:
        out.warning = "some files couldn't be read and were left out"
    elif result.code != 0:
        raise ResticError(restic.failure_message(result), result.code)
    added = int(summary.get("data_added") or 0)
    await job.log(
        f"{label}: snapshot {str(out.snapshot_id or '')[:8]}, "
        f"{_size(added)} new" + (f" ({out.warning})" if out.warning else "")
    )
    return out


async def _running_state(runtime: Runtime, name: str) -> bool:
    try:
        found = await asyncio.to_thread(containers.list_containers, runtime)
    except containers.ContainerError:
        return False
    return any(c.project == name and c.state == "running" for c in found)


async def backup_app(
    tool: Restic,
    repo: Repository,
    job: Job,
    store: AppStore,
    runtime: Runtime | None,
    item: PlanApp,
) -> ItemResult:
    """Snapshot one app's folder, stopping it for the duration unless `while_running`.
    Also backs up named volumes declared in the app's compose file through a short-lived
    helper container, plus any bind mounts the admin opted into.
    """
    label = app_tag(item.name)
    folder = store.dir(item.name)
    if not folder.is_dir():
        raise ResticError(f"{item.name} has no folder to back up")
    path = store.compose_path(item.name)
    stop = (
        runtime is not None and not item.while_running and await _running_state(runtime, item.name)
    )
    stopped = False
    result: ItemResult | None = None
    failure: BaseException | None = None
    try:
        if stop:
            assert runtime is not None
            await job.log(f"Stopping {item.name}")
            stopped = True
            await run_or_fail(
                job, compose(runtime, item.name, path, "stop"), "docker compose stop",
                env=store.env(item.name),
            )  # fmt: skip
        result = await backup_folder(tool, repo, job, folder, snapshot_tags(label), label)
        volumes = _named_volumes(path)
        if volumes and runtime is not None:
            await _backup_volumes(tool, repo, job, runtime, item.name, volumes)
        if item.bind_mounts:
            await _backup_bind_mounts(tool, repo, job, item.bind_mounts, label)
    except BaseException as exc:
        failure = exc
    if stopped:
        assert runtime is not None
        await job.log(f"Starting {item.name} again")
        try:
            await asyncio.shield(
                run_or_fail(
                    job,
                    compose(runtime, item.name, path, "up", "--detach", "--remove-orphans"),
                    "docker compose up", env=store.env(item.name),
                )
            )  # fmt: skip
        except Exception as exc:
            message = f"{item.name} could not be started again: {exc}"
            if failure is None or isinstance(failure, Exception):
                failure = ResticError(f"{failure}; {message}" if failure is not None else message)
            else:
                log.error(message)
                await job.log(f"error: {message}")
    if failure is not None:
        raise failure
    assert result is not None
    return result


def _named_volumes(compose_path: Path) -> list[str]:
    """Named volumes declared under top-level `volumes:` and referenced by a service."""
    try:
        doc = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(doc, dict):
        return []
    services = doc.get("services") or {}
    top_level = doc.get("volumes") or {}
    if not isinstance(top_level, dict):
        return []
    declared: set[str] = set()
    for service in services.values():
        if not isinstance(service, dict):
            continue
        for vol in service.get("volumes") or []:
            if isinstance(vol, str) and ":" in vol:
                name = vol.split(":", 1)[0]
                if name in top_level:
                    declared.add(name)
    return sorted(declared)


async def _backup_volumes(
    tool: Restic,
    repo: Repository,
    job: Job,
    runtime: Runtime,
    app_name: str,
    volumes: list[str],
) -> None:
    """Stream each named volume through a helper container into restic --stdin."""
    helper = "busybox@sha256:8b7fe2f5e985f8509e2a342cf38889e2fe6e00bf3d7c7c3e49b5a9e8e1f8e4a1"
    for vol in volumes:
        await job.log(f"Backing up volume {vol}")
        docker_args = [
            *runtime.cli,
            "run",
            "--rm",
            "--network",
            "none",
            "-v",
            f"{vol}:/v:ro",
            helper,
            "tar",
            "-C",
            "/v",
            "-cf",
            "-",
        ]
        proc = await asyncio.create_subprocess_exec(
            *docker_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
        )
        assert proc.stdout is not None
        restic_args = [
            "backup",
            "--stdin",
            "--stdin-filename",
            f"volumes/{vol}.tar",
            "--host",
            SNAPSHOT_HOST,
            *snapshot_tags(app_tag(app_name)),
        ]
        restic_proc = await asyncio.create_subprocess_exec(
            str(tool.binary),
            *restic_args,
            stdin=proc.stdout,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_environment(repo, tool.cache_dir),
        )
        proc.stdout.close()
        _, restic_err = await restic_proc.communicate()
        docker_code = await proc.wait()
        if docker_code != 0 or restic_proc.returncode != 0:
            msg = (
                f"volume {vol}: docker exit {docker_code}, "
                f"restic exit {restic_proc.returncode}: {restic_err.decode(errors='replace')}"
            )
            raise ResticError(msg, restic_proc.returncode or docker_code)
        await job.log(f"Volume {vol}: snapshotted")


async def _backup_bind_mounts(
    tool: Restic,
    repo: Repository,
    job: Job,
    bind_mounts: list[str],
    label: str,
) -> None:
    """Back up each opted-in bind mount path."""
    for mount in bind_mounts:
        p = Path(mount)
        if not p.is_dir():
            await job.log(f"Bind mount {mount} not found, skipping")
            continue
        await job.log(f"Backing up bind mount {mount}")
        await backup_folder(tool, repo, job, p, snapshot_tags(f"{label}:{mount}"), f"bind:{mount}")


async def run_items(
    *,
    tool: Restic,
    repo: Repository,
    job: Job,
    data_dir: Path,
    store: AppStore,
    runtime: Runtime | None,
    items: PlanItems,
    busy: dict[str, str],
    known_apps: Callable[[], set[str]],
) -> list[ItemResult]:
    """Back up every item in turn; one item failing doesn't stop the others."""
    results: list[ItemResult] = []
    total = int(items.athena) + int(items.user_files) + len(items.apps)
    done = 0

    async def step(label: str, work: Callable[[], Awaitable[ItemResult]]) -> None:
        nonlocal done
        await job.set_progress(done / total, label)
        try:
            results.append(await work())
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            await job.log(f"error: {label}: {message}")
            results.append(ItemResult(label, error=message))
        done += 1

    if items.athena:

        async def athena() -> ItemResult:
            target = staging_dir(data_dir)
            try:
                await job.log("Copying Athena's database and settings")
                await asyncio.to_thread(stage_athena, data_dir, target)
                return await backup_folder(
                    tool, repo, job, target, snapshot_tags(ATHENA_TAG), ATHENA_TAG
                )
            finally:
                await asyncio.to_thread(shutil.rmtree, target, True)

        await step(ATHENA_TAG, athena)

    if items.user_files:

        async def user_files() -> ItemResult:
            folder = data_dir / "users"
            if not folder.is_dir():
                await job.log("No user files yet; nothing to back up")
                return ItemResult(USERS_TAG, nothing_to_back_up=True)
            await job.log("Backing up the users' files")
            return await backup_folder(tool, repo, job, folder, snapshot_tags(USERS_TAG), USERS_TAG)

        await step(USERS_TAG, user_files)

    for app in items.apps:

        async def one(app: PlanApp = app) -> ItemResult:
            if app.name not in known_apps():
                raise ResticError(f"{app.name} isn't an app any more")
            other = busy.get(app.name)
            if other and other != job.id:
                raise ResticError(f"{app.name} is busy with another job")
            busy[app.name] = job.id
            try:
                return await backup_app(tool, repo, job, store, runtime, app)
            finally:
                if busy.get(app.name) == job.id:
                    busy.pop(app.name, None)

        await step(app_tag(app.name), one)
    return results


def known_app_names(session_factory: Callable[[], Session]) -> Callable[[], set[str]]:
    def names() -> set[str]:
        with session_factory() as session:
            return set(session.exec(select(App.name)).all())

    return names


def now() -> datetime:
    return datetime.now(UTC)


def destination_connected(location: str) -> bool:
    """A local repository's folder is there and still looks like a repository."""
    return os.path.isdir(location) and looks_like_repository(Path(location))


def _is_rclone_location(location: str) -> bool:
    """`destination:path` style (rclone), not a local folder or Windows drive letter."""
    if ":" not in location:
        return False
    head = location.split(":", 1)[0]
    return "/" not in head and "\\" not in head and len(head) > 1


async def destination_reachable(tool: Restic, repo: Repository) -> bool:
    """The destination still holds a repository we can open (`restic cat config`)."""
    probe = await tool.run(repo, "cat", "config")
    return probe.code == 0
