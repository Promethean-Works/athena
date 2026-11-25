"""Restoring one app from a version (docs/specs/backup.md).

The version is restored by restic into a staging folder first, and checked there. Only then
is the app stopped, its current folder moved aside to `apps/<name>.before-restore-<time>/`,
the restored folder moved into place and the app started. The app stops for the swap only,
and is always started again, even when the restore fails or the job is cancelled.
"""

import asyncio
import json
import logging
import os
import platform
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from athena import __version__, restart
from athena.apps.store import (
    APP_NAME,
    AppStore,
    InvalidComposeError,
    check_name,
    compose,
    parse_compose,
)
from athena.backup import snapshots, versions
from athena.backup.restic import Repository, Restic, ResticError, failure_message
from athena.config import SETTINGS_FILE
from athena.crypto import KEY_FILE
from athena.jobs import Job, run_or_fail
from athena.updates import version_key

log = logging.getLogger(__name__)

ASIDE = ".before-restore-"
STAMP = "%Y%m%dT%H%M%SZ"
_ASIDE_RE = re.compile(rf"^({APP_NAME[1:-1]}){re.escape(ASIDE)}(\d{{8}}T\d{{6}}Z)(?:-\d+)?$")


@dataclass
class Plan:
    """What a restore will do, worked out and checked before anything is touched."""

    version_id: str
    source: str
    """The app the version was taken from."""
    root: str
    """The folder that was backed up, as restic lists it."""
    os: str | None


def staging_dir(data_dir: Path, version_id: str) -> Path:
    return data_dir / "cache" / "backup" / f"restore-{version_id[:16]}"


async def plan_for(tool: Restic, repo: Repository, version_id: str) -> Plan:
    """Look the version up. It must be an app version (`app:<name>` tag); Athena's own
    versions are restored from the first-run screen, not here."""
    if not versions.SNAPSHOT_ID.match(version_id):
        raise ResticError("That isn't a version id")
    result = await tool.run_ok(repo, "snapshots", "--json", version_id)
    try:
        snap = json.loads(result.stdout or "[]")[0]
        tags = [t for t in snap["tags"] if isinstance(t, str)]
        root = versions.restic_path(snap["paths"][0])
        full_id = str(snap["id"])
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ResticError("No such version") from exc
    item = next((t for t in tags if versions.ITEM.match(t)), None)
    if item is None or not item.startswith("app:"):
        raise ResticError("That version isn't an app's")
    return Plan(full_id, item[4:], root, versions._tag_value(tags, "os:"))


def _staged_folder(staging: Path, root: str) -> Path:
    """Where restic put the backed-up folder inside the staging folder."""
    return staging.joinpath(*[p for p in root.split("/") if p])


def check_staged(folder: Path, staging: Path) -> None:
    """The restored folder is a real folder inside staging with a valid compose file."""
    real = os.path.realpath(folder)
    if folder.is_symlink() or not folder.is_dir() or not _inside(real, os.path.realpath(staging)):
        raise ResticError("The version doesn't hold an app folder")
    compose_file = folder / "compose.yaml"
    if compose_file.is_symlink() or not compose_file.is_file():
        raise ResticError("The version has no compose.yaml")
    try:
        parse_compose(compose_file.read_text(encoding="utf-8"))
    except (InvalidComposeError, UnicodeDecodeError, OSError) as exc:
        raise ResticError(f"The version's compose.yaml isn't usable: {exc}") from exc


def _inside(path: str, folder: str) -> bool:
    return os.path.commonpath([path, folder]) == folder and path != folder


def aside_path(store: AppStore, name: str, moment: datetime) -> Path:
    base = f"{name}{ASIDE}{moment.strftime(STAMP)}"
    candidate, n = store.root / base, 1
    while candidate.exists():
        candidate = store.root / f"{base}-{n}"
        n += 1
    return candidate


def aside_folders(store: AppStore, name: str | None = None) -> list[tuple[Path, datetime, str]]:
    """The folders restores moved aside: path, when, and the app they belonged to."""
    out: list[tuple[Path, datetime, str]] = []
    if not store.root.is_dir():
        return out
    for entry in store.root.iterdir():
        found = _ASIDE_RE.match(entry.name)
        if not found or not entry.is_dir() or (name is not None and found.group(1) != name):
            continue
        out.append(
            (entry, datetime.strptime(found.group(2), STAMP).replace(tzinfo=UTC), found.group(1))
        )
    return out


def sweep_aside(store: AppStore, keep_days: int, now: datetime, name: str | None = None) -> int:
    """Delete moved-aside folders older than `keep_days` (all of them when it's negative)."""
    removed = 0
    for path, when, _ in aside_folders(store, name):
        if keep_days < 0 or now - when >= timedelta(days=keep_days):
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    return removed


def _swap(store: AppStore, staged: Path, target: str, aside: Path) -> bool:
    """Move the current folder aside (if there is one) and the staged one into place.
    Returns whether something was moved aside. Undoes the first move if the second fails."""
    folder = store.dir(target)
    moved = False
    if folder.exists():
        os.replace(folder, aside)
        moved = True
    try:
        os.replace(staged, folder)
    except OSError:
        if moved:
            os.replace(aside, folder)
        raise
    return moved


async def _restic_restore(
    tool: Restic, repo: Repository, job: Job, version_id: str, staging: Path
) -> None:
    async def on_line(line: str) -> None:
        try:
            message = json.loads(line)
        except ValueError:
            return
        if isinstance(message, dict) and message.get("message_type") == "status":
            fraction = message.get("percent_done")
            await job.set_progress(
                float(fraction) if isinstance(fraction, int | float) else None,
                "Restoring files",
            )

    result = await tool.stream(
        repo, "restore", "--json", version_id, "--target", str(staging), on_line=on_line
    )
    if result.code != 0:
        raise ResticError(failure_message(result), result.code)


async def restore_app(
    *,
    tool: Restic,
    repo: Repository,
    job: Job,
    store: AppStore,
    data_dir: Path,
    runtime,  # type: ignore[no-untyped-def]  # Runtime; the caller checked it isn't None
    plan: Plan,
    target: str,
    replace: bool,
    keep_days: int,
    on_placed: Callable[[], None] | None = None,
) -> None:
    """Restore `plan` as the app `target`. `replace` means `target` is an existing app: it is
    stopped and its folder moved aside. `on_placed` runs once the folder is in place (the new
    app's database row). Raises on failure; the app is started again either way."""
    check_name(target)
    if plan.os and plan.os != platform.system().lower():
        await job.log(
            f"warning: this version was taken on {plan.os}; bind-mount paths in its compose "
            "file may not exist on this host"
        )
    staging = staging_dir(data_dir, plan.version_id)
    path = store.compose_path(target)
    try:
        await asyncio.to_thread(shutil.rmtree, staging, True)
        staging.mkdir(parents=True)
        await job.log(f"Restoring version {plan.version_id[:8]} of {plan.source}")
        await _restic_restore(tool, repo, job, plan.version_id, staging)
        staged = _staged_folder(staging, plan.root)
        await asyncio.to_thread(check_staged, staged, staging)

        was_stopped = False
        failure: BaseException | None = None
        aside = aside_path(store, target, snapshots.now())
        try:
            if replace and path.is_file():
                await job.log(f"Stopping {target}")
                was_stopped = True  # even a failed stop may have stopped some containers
                await run_or_fail(
                    job, compose(runtime, target, path, "stop"), "docker compose stop",
                    env=store.env(target),
                )  # fmt: skip
            await job.log("Replacing the app's folder" if replace else "Creating the app's folder")
            # Shielded: a half-done swap would leave the app without a folder.
            moved = await asyncio.shield(asyncio.to_thread(_swap, store, staged, target, aside))
            if moved:
                await job.log(f"The old folder is kept as {aside.name}")
            if on_placed is not None:
                await asyncio.to_thread(on_placed)
        except BaseException as exc:
            failure = exc
        if failure is None or was_stopped:
            await job.log(f"Starting {target}")
            try:
                await asyncio.shield(
                    run_or_fail(
                        job,
                        compose(runtime, target, path, "up", "--detach", "--remove-orphans"),
                        "docker compose up",
                        env=store.env(target),
                    )
                )
            except Exception as exc:
                message = f"{target} could not be started: {exc}"
                if failure is None or isinstance(failure, Exception):
                    failure = ResticError(
                        f"{failure}; {message}" if failure is not None else message
                    )
                else:
                    log.error(message)
                    await job.log(f"error: {message}")
        if failure is not None:
            raise failure
    finally:
        await asyncio.shield(asyncio.to_thread(shutil.rmtree, staging, True))
    removed = await asyncio.to_thread(sweep_aside, store, keep_days, snapshots.now())
    if removed:
        await job.log(f"Deleted {removed} old moved-aside folder(s)")


async def restore_athena(
    *,
    tool: Restic,
    repo: Repository,
    job: Job,
    data_dir: Path,
    version_id: str,
) -> None:
    """Restore all of Athena from an `athena` version.

    Stages the snapshot into a temporary folder, checks it holds what a restore needs,
    then stops the server (so the supervisor restarts it), moves the current data folder
    aside and the restored one into place. The restored DB is migrated by Alembic on the
    next start; the server's `server` section is replaced by this host's own settings.
    """
    staging = staging_dir(data_dir, version_id[:16])
    await job.log(f"Restoring Athena from version {version_id[:8]}")
    await asyncio.to_thread(shutil.rmtree, staging, True)
    staging.mkdir(parents=True)
    await _restic_restore(tool, repo, job, version_id, staging)
    staged = _staged_folder(staging, "athena")
    if not staged.is_dir():
        raise ResticError("The version doesn't hold Athena's data folder")
    for name in (SETTINGS_FILE, KEY_FILE):
        if not (staged / name).is_file():
            raise ResticError(f"The version has no {name}")

    # Check the Athena version of the snapshot.
    result = await tool.run_ok(repo, "snapshots", "--json", version_id)
    try:
        snap = json.loads(result.stdout or "[]")[0]
        tags = [t for t in snap["tags"] if isinstance(t, str)]
        backup_version = versions._tag_value(tags, "athena-version:")
        backup_os = versions._tag_value(tags, "os:")
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ResticError("Could not read snapshot tags") from exc

    if backup_version:
        current_key = version_key(__version__)
        backup_key = version_key(backup_version)
        if current_key is not None and backup_key is not None and backup_key > current_key:
            raise ResticError(
                f"This backup was made by Athena {backup_version}, which is newer than "
                f"the installed version ({__version__}). Upgrade Athena first, then restore."
            )
        await job.log(f"Backup Athena version: {backup_version}")
    else:
        await job.log("warning: backup has no Athena version tag; skipping version check")

    # Cross-OS warning.
    current_os = platform.system().lower()
    if backup_os and backup_os != current_os:
        await job.log(
            f"warning: this backup was taken on {backup_os}, but this host is {current_os}. "
            "Bind-mount paths in the restored apps may not exist on this host."
        )

    # Stop the server so the supervisor starts a fresh one after the swap.
    if not restart.request():
        await job.log("warning: server won't restart automatically; restart it after the restore")
    aside = data_dir / f"athena.before-restore-{snapshots.now().strftime(STAMP)}"
    await asyncio.to_thread(shutil.rmtree, aside, ignore_errors=True)
    current = data_dir
    await job.log("Moving the current data folder aside")
    os.replace(current, aside)
    try:
        await job.log("Moving the restored data into place")
        os.replace(staged, current)
        staging = None  # already moved; skip cleanup
    except BaseException:
        os.replace(aside, current)
        raise
    finally:
        if staging is not None:
            await asyncio.shield(asyncio.to_thread(shutil.rmtree, staging, True))

    # Replace the server section of athena.json with this host's settings.
    # The old server.host and server.port may clash with this install.
    try:
        restored_settings = (data_dir / SETTINGS_FILE).read_text(encoding="utf-8")
        restored = json.loads(restored_settings)
        current_settings = (aside / SETTINGS_FILE).read_text(encoding="utf-8")
        current = json.loads(current_settings)
        if "server" in current:
            restored["server"] = current["server"]
            (data_dir / SETTINGS_FILE).write_text(
                json.dumps(restored, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            await job.log("Replaced server section in athena.json with this host's settings")
    except (OSError, json.JSONDecodeError) as exc:
        await job.log(
            f"warning: could not replace server section in athena.json: {exc}. "
            "You may need to edit it manually."
        )

    # The HTTPS certificate will be reissued by the daily check because the addresses changed.
    await job.log(
        "Note: the HTTPS certificate will be reissued automatically by the next daily check "
        "(or run `athena https status` to trigger it)."
    )
