"""Taking snapshots (docs/specs/backup.md): one restic snapshot per item of a plan.

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

from sqlmodel import Session, select

from athena import __version__
from athena.apps.store import AppStore, compose
from athena.backup import restic
from athena.backup.plans import PlanApp, PlanItems
from athena.backup.repository import looks_like_repository
from athena.backup.restic import Repository, Restic, ResticError
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
    """Snapshot one app's folder, stopping it for the duration unless `while_running`."""
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
            stopped = True  # even a failed stop may have stopped some of its containers
            await run_or_fail(
                job, compose(runtime, item.name, path, "stop"), "docker compose stop",
                env=store.env(item.name),
            )  # fmt: skip
        result = await backup_folder(tool, repo, job, folder, snapshot_tags(label), label)
    except BaseException as exc:
        failure = exc
    if stopped:
        assert runtime is not None
        await job.log(f"Starting {item.name} again")
        try:
            # Shielded: a cancelled job still starts every app it stopped.
            await asyncio.shield(
                run_or_fail(
                    job, compose(runtime, item.name, path, "up", "--detach", "--remove-orphans"),
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
    total = int(items.athena) + len(items.apps)
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
