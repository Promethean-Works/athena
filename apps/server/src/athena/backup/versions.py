"""Listing versions (restic snapshots) and the files in one (docs/specs/backup.md). Read-only."""

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from athena.apps.store import APP_NAME
from athena.backup.restic import Repository, Restic, ResticError
from athena.backup.snapshots import ATHENA_TAG, USERS_TAG

ITEM = re.compile(f"^(?:{ATHENA_TAG}|{USERS_TAG}|app:(?:{APP_NAME[1:-1]}))$")
SNAPSHOT_ID = re.compile(r"^[0-9a-f]{8,64}$")
DIFF_PARALLEL = 4


@dataclass
class Version:
    id: str
    time: datetime
    item: str
    """`athena`, `users` or `app:<name>`."""
    size: int
    """Bytes the item held when it was backed up."""
    new_bytes: int
    """Bytes this version added to the repository (deduplicated)."""
    athena_version: str | None
    os: str | None
    parent: str | None
    files_added: int | None = None
    files_changed: int | None = None
    files_removed: int | None = None


@dataclass
class Entry:
    name: str
    path: str
    kind: str
    """`dir`, `file`, `symlink` or `other`."""
    size: int | None
    modified: datetime | None


def _time(text: object) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        # restic prints nanoseconds; Python takes microseconds.
        value = datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", text.replace("Z", "+00:00")))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _tag_value(tags: list[str], prefix: str) -> str | None:
    return next((t[len(prefix) :] for t in tags if t.startswith(prefix)), None)


def parse_versions(stdout: str) -> list[Version]:
    """Athena's snapshots from `restic snapshots --json`, newest first. Others are skipped."""
    try:
        raw = json.loads(stdout or "[]")
    except ValueError as exc:
        raise ResticError("restic printed something unexpected for the versions") from exc
    out: list[Version] = []
    for snap in raw if isinstance(raw, list) else []:
        if not isinstance(snap, dict) or not isinstance(snap.get("id"), str):
            continue
        tags = [t for t in snap.get("tags") or [] if isinstance(t, str)]
        item = next((t for t in tags if ITEM.match(t)), None)
        when = _time(snap.get("time"))
        if item is None or when is None:
            continue
        summary = snap.get("summary") if isinstance(snap.get("summary"), dict) else {}
        out.append(
            Version(
                id=snap["id"],
                time=when,
                item=item,
                size=int(summary.get("total_bytes_processed") or 0),
                new_bytes=int(summary.get("data_added") or 0),
                athena_version=_tag_value(tags, "athena-version:"),
                os=_tag_value(tags, "os:"),
                parent=snap["parent"] if isinstance(snap.get("parent"), str) else None,
            )
        )
    return sorted(out, key=lambda v: v.time, reverse=True)


async def list_versions(tool: Restic, repo: Repository, item: str | None = None) -> list[Version]:
    if item is not None and not ITEM.match(item):
        raise ResticError("That isn't Athena, the users' files or an app")
    args = ["snapshots", "--json", *(("--tag", item) if item else ())]
    result = await tool.run_ok(repo, *args)
    return parse_versions(result.stdout)


async def diff_stats(
    tool: Restic, repo: Repository, older: str, newer: str
) -> tuple[int, int, int] | None:
    """(added, changed, removed) files from `older` to `newer`, or None when restic can't say."""
    result = await tool.run(repo, "diff", "--json", older, newer)
    if result.code != 0:
        return None
    for line in reversed(result.stdout.splitlines()):
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if isinstance(message, dict) and message.get("message_type") == "statistics":
            added = message.get("added") or {}
            removed = message.get("removed") or {}
            return (
                int(added.get("files") or 0),
                int(message.get("changed_files") or 0),
                int(removed.get("files") or 0),
            )
    return None


async def add_diffs(
    tool: Restic,
    repo: Repository,
    versions: list[Version],
    cache: dict[tuple[str, str], tuple[int, int, int] | None],
    cache_key: str,
) -> None:
    """Fill in files added/changed/removed against each version's parent.

    A version never changes, so a diff is computed once per destination and kept in `cache`.
    """
    gate = asyncio.Semaphore(DIFF_PARALLEL)

    async def one(version: Version) -> None:
        if version.parent is None:
            return
        key = (cache_key, version.id)
        if key not in cache:
            async with gate:
                cache[key] = await diff_stats(tool, repo, version.parent, version.id)
        stats = cache[key]
        if stats is not None:
            version.files_added, version.files_changed, version.files_removed = stats

    await asyncio.gather(*(one(v) for v in versions))


def restic_path(path: str) -> str:
    """A backed-up folder as restic lists it: `/` separators, and `C:\\x` as `/C/x`."""
    text = path.replace("\\", "/").rstrip("/")
    if re.match(r"^[A-Za-z]:", text):
        text = "/" + text[0] + text[2:]
    return text if text.startswith("/") else "/" + text


async def snapshot_root(tool: Restic, repo: Repository, snapshot_id: str) -> str:
    """Where a version's files start: the folder that was backed up, as restic lists it."""
    if not SNAPSHOT_ID.match(snapshot_id):
        raise ResticError("That isn't a version id")
    result = await tool.run_ok(repo, "snapshots", "--json", snapshot_id)
    try:
        snaps = json.loads(result.stdout or "[]")
        paths = snaps[0]["paths"]
        return restic_path(paths[0])
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ResticError("No such version") from exc


def check_path(root: str, path: str | None) -> str:
    """`path` (or the root) if it's inside the version's folder, else `ResticError`."""
    wanted = (path or root).rstrip("/") or "/"
    parts = wanted.split("/")
    if ".." in parts or "\\" in wanted or "\0" in wanted:
        raise ResticError("That folder isn't in this version")
    if wanted != root and not wanted.startswith(root + "/"):
        raise ResticError("That folder isn't in this version")
    return wanted


async def list_files(tool: Restic, repo: Repository, snapshot_id: str, path: str) -> list[Entry]:
    """One folder level of a version: folders first, then files, by name."""
    result = await tool.run_ok(repo, "ls", "--json", snapshot_id, path)
    entries: list[Entry] = []
    for line in result.stdout.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or "path" not in row or row.get("struct_type") == "snapshot":
            continue
        if row["path"] == path or not isinstance(row.get("name"), str):
            continue
        kind = row.get("type")
        entries.append(
            Entry(
                name=row["name"],
                path=str(row["path"]),
                kind=kind if kind in ("dir", "file", "symlink") else "other",
                size=int(row["size"]) if isinstance(row.get("size"), int) else None,
                modified=_time(row.get("mtime")),
            )
        )
    entries.sort(key=lambda e: (e.kind != "dir", e.name.lower()))
    return entries
