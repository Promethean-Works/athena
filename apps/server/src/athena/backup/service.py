"""Shared pieces of the backup area: getting a verified restic and opening a destination."""

import asyncio
from pathlib import Path
from typing import Any

from sqlmodel import Session

from athena import audit
from athena.apps.store import AppStore
from athena.backup import retention, snapshots
from athena.backup.plans import PlanItems, parse_items, parse_retention
from athena.backup.restic import Repository, Restic, ensure_restic
from athena.backup.settings import Retention
from athena.backup.snapshots import DestinationNotConnectedError
from athena.containers.runtime import Runtime
from athena.crypto import SecretBox
from athena.db.models import BackupDestination, BackupPlan
from athena.downloads import Log, quiet
from athena.jobs import Job


class ResticProvider:
    """Hands out a `Restic` backed by Athena's own pinned, checksum-verified binary."""

    def __init__(self, data_dir: Path, binary: Path | None = None) -> None:
        self.data_dir = data_dir
        self.binary = binary
        """Set by tests to use a restic they already have; production downloads one."""
        self._lock: asyncio.Lock | None = None

    async def get(self, log_line: Log = quiet) -> Restic:
        if self.binary is not None:
            path = self.binary
        else:
            if self._lock is None:
                self._lock = asyncio.Lock()
            async with self._lock:
                path = await ensure_restic(self.data_dir, log_line)
        return Restic(path, cache_dir=self.data_dir / "cache" / "restic")


def repository_of(
    row: BackupDestination,
    box: SecretBox,
    env: dict[str, str] | None = None,
) -> Repository:
    """The repository a destination row points at, with its decrypted password."""
    return Repository(location=row.location, password=box.decrypt(row.password), env=env)


class PlanRunner:
    """Runs a backup plan as one job: for each item in turn, snapshot it (docs/specs/backup.md)."""

    def __init__(self, state: Any) -> None:
        self.state = state
        """`app.state`: db, secret_box, restic, settings, app_jobs and backup_locks."""

    def busy_destination(self, destination_id: str) -> bool:
        lock = self.state.backup_locks.get(destination_id)
        return lock is not None and lock.locked()

    async def run(self, job: Job, plan_id: str, username: str, runtime: Runtime | None) -> None:
        """The job body. Raises (so the job fails) when any item failed or the run was
        skipped or cancelled; the plan's last-run fields say which."""
        engine = self.state.db.engine
        with Session(engine) as db:
            plan = db.get(BackupPlan, plan_id)
            dest = db.get(BackupDestination, plan.destination_id) if plan else None
            if plan is None or dest is None:
                raise RuntimeError("That plan or its destination no longer exists")
            items = parse_items(plan.items)
            keep = parse_retention(plan.retention)
            plan_name, dest_id, location = plan.name, dest.id, dest.location
            env = (
                {"RCLONE_CONFIG": str(self.state.settings.data_dir / "rclone" / "rclone.conf")}
                if dest.kind == "rclone"
                else None
            )
            repo = repository_of(dest, self.state.secret_box, env=env)

        work = asyncio.ensure_future(
            self._locked(job, dest_id, repo, location, items, keep, runtime)
        )

        async def cancel() -> None:
            work.cancel()

        job.cancel_hook = cancel
        status, error = "ok", None
        try:
            error = await work
            if error:
                status = "failed"
        except DestinationNotConnectedError as exc:
            status, error = "skipped", str(exc)
        except asyncio.CancelledError:
            if not job.cancelled:
                raise
            status, error = "failed", "Cancelled"
        except Exception as exc:
            status, error = "failed", str(exc) or exc.__class__.__name__
        with Session(engine) as db:
            plan = db.get(BackupPlan, plan_id)
            if plan is not None:
                plan.last_run_at = snapshots.now()
                plan.last_status, plan.last_error = status, error
                db.add(plan)
                db.commit()
            if status == "failed":
                audit.record(db, username, "backup.run.failed", plan_name, error)
        if error is not None:
            raise RuntimeError(error)

    async def _locked(
        self,
        job: Job,
        dest_id: str,
        repo: Repository,
        location: str,
        items: PlanItems,
        keep: Retention,
        runtime: Runtime | None,
    ) -> str | None:
        """Back everything up under the destination's lock. The error text, or None."""
        state = self.state
        async with state.backup_locks.setdefault(dest_id, asyncio.Lock()):
            tool = await state.restic.get(job.log)
            if snapshots._is_rclone_location(location):
                if not await snapshots.destination_reachable(tool, repo):
                    raise DestinationNotConnectedError(
                        f"The destination isn't connected: {location} is unreachable"
                    )
            elif not await asyncio.to_thread(snapshots.destination_connected, location):
                raise DestinationNotConnectedError(
                    f"The destination isn't connected: {location} is missing or isn't a "
                    "backup repository"
                )
            data_dir: Path = state.settings.data_dir
            engine = state.db.engine
            results = await snapshots.run_items(
                tool=tool,
                repo=repo,
                job=job,
                data_dir=data_dir,
                store=AppStore(data_dir),
                runtime=runtime,
                items=items,
                busy=state.app_jobs,
                known_apps=snapshots.known_app_names(lambda: Session(engine)),
            )
        problems = [f"{r.item}: {r.error}" for r in results if r.error]
        for r in results:
            if r.error:
                continue  # an item that wasn't backed up has nothing new to trim around
            try:
                removed = await retention.forget(tool, repo, r.item, keep)
                if removed:
                    await job.log(f"{r.item}: forgot {removed} old version(s)")
            except Exception as exc:
                message = str(exc) or exc.__class__.__name__
                await job.log(f"error: {r.item}: retention: {message}")
                problems.append(f"{r.item}: retention: {message}")
        problems += await self._upkeep(job, tool, repo, dest_id)
        if problems:
            return "; ".join(problems)[:1000]
        await job.log(f"Backed up {len(results)} item(s)")
        return None

    async def _upkeep(self, job: Job, tool: Restic, repo: Repository, dest_id: str) -> list[str]:
        """Prune and check this destination when they're due. Returns the problems."""
        state = self.state
        cfg = state.settings_file.get().backup
        engine = state.db.engine
        with Session(engine) as db:
            dest = db.get(BackupDestination, dest_id)
            if dest is None:
                return []
            last_pruned, last_checked = dest.last_pruned_at, dest.last_checked_at
        moment = snapshots.now()
        problems: list[str] = []
        for name, last, days, work in (
            ("prune", last_pruned, cfg.prune_interval_days, retention.prune),
            ("check", last_checked, cfg.check_interval_days, retention.check),
        ):
            if not retention.due(last, days, moment):
                continue
            await job.log(f"Running restic {name}")
            try:
                await work(tool, repo)
            except Exception as exc:
                message = str(exc) or exc.__class__.__name__
                await job.log(f"error: {name}: {message}")
                problems.append(f"{name}: {message}")
                continue
            with Session(engine) as db:
                dest = db.get(BackupDestination, dest_id)
                if dest is not None:
                    setattr(
                        dest, "last_pruned_at" if name == "prune" else "last_checked_at", moment
                    )
                    db.add(dest)
                    db.commit()
        return problems
