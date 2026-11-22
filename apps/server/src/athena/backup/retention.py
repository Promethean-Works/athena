"""Retention and upkeep of a repository (docs/specs/backup.md).

After each item's snapshot, `restic forget` drops the versions the plan's retention no
longer keeps. That only marks them; `restic prune` frees the space and runs at most once
every `prune_interval_days` per destination. `restic check` (metadata only, so it doesn't
read every backup) runs at most every `check_interval_days`.
"""

import json
from datetime import datetime, timedelta

from athena.backup.restic import Repository, Restic, ResticError, failure_message
from athena.backup.settings import Retention


def forget_args(tag: str, retention: Retention) -> list[str]:
    """`restic forget` for one item's versions. A count of 0 leaves that rule out."""
    if not retention.keeps_something():
        raise ResticError("Retention would delete every version")
    args = ["forget", "--tag", tag, "--group-by", ""]
    for flag, count in (
        ("--keep-last", retention.keep_last),
        ("--keep-daily", retention.keep_daily),
        ("--keep-weekly", retention.keep_weekly),
        ("--keep-monthly", retention.keep_monthly),
    ):
        if count:
            args += [flag, str(count)]
    return args


def due(last: datetime | None, every_days: int, now: datetime) -> bool:
    """True when `last` (UTC, maybe naive from SQLite) is empty or `every_days` old."""
    if last is None:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=now.tzinfo)
    return now - last >= timedelta(days=every_days)


async def forget(tool: Restic, repo: Repository, tag: str, retention: Retention) -> int:
    """Forget the versions of one item that retention doesn't keep. Returns how many."""
    result = await tool.run_ok(repo, *forget_args(tag, retention), "--json")
    return _forgotten(result.stdout)


def _forgotten(stdout: str) -> int:
    try:
        groups = json.loads(stdout or "[]")
    except ValueError:
        return 0
    if not isinstance(groups, list):
        return 0
    return sum(len(g.get("remove") or []) for g in groups if isinstance(g, dict))


async def prune(tool: Restic, repo: Repository) -> None:
    await tool.run_ok(repo, "prune")


async def check(tool: Restic, repo: Repository) -> None:
    """Metadata only (no `--read-data`): fast, and enough to notice a damaged repository."""
    result = await tool.run(repo, "check")
    if result.code != 0:
        raise ResticError(f"The repository check failed: {failure_message(result)}", result.code)
