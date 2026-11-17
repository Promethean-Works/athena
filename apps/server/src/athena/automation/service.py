"""Automation service: durable triggers (cron, webhook) that run background jobs.

Triggers are stored in `automation_triggers` and each execution is recorded in
`automation_job_runs`. A cron expression fires on a schedule; an HTTP trigger
fires when its webhook URL is called. The action (what to run) is stored as JSON
and supports app lifecycle and package-manager actions.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from croniter import CroniterBadCronError, croniter
from fastapi import FastAPI
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from athena.apps.store import AppStore, compose
from athena.containers.runtime import RuntimeUnavailableError, runtime_from
from athena.db.models import AutomationJobRun, AutomationTrigger
from athena.jobs import Job, run_or_fail
from athena.packages import MANAGERS
from athena.packages.base import command_env, resolve

log = logging.getLogger(__name__)

# What each app verb runs, after `--project-name <name> --file <compose.yaml>`.
APP_ACTIONS: dict[str, list[list[str]]] = {
    "start": [["up", "--detach", "--remove-orphans"]],
    "stop": [["stop"]],
    "restart": [["restart"]],
    "update": [["pull"], ["up", "--detach", "--remove-orphans"]],
}

AppVerb = Literal["start", "stop", "restart", "update"]
PackageVerb = Literal["install", "uninstall", "upgrade", "refresh"]


class AppAction(BaseModel):
    kind: Literal["app"] = "app"
    name: str = Field(min_length=1, max_length=63)
    verb: AppVerb


class PackageAction(BaseModel):
    kind: Literal["package"] = "package"
    manager: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    verb: PackageVerb
    source: str | None = None


TriggerAction = Annotated[AppAction | PackageAction, Field(discriminator="kind")]


class TriggerIn(BaseModel):
    kind: Literal["cron", "http"] = "cron"
    name: str = Field(min_length=1, max_length=64)
    cron_expression: str | None = None
    action: TriggerAction
    enabled: bool = True


class TriggerOut(BaseModel):
    id: str
    kind: str
    name: str
    cron_expression: str | None
    action: TriggerAction
    enabled: bool
    webhook_token: str | None
    next_run_at: datetime | None
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


class JobRunOut(BaseModel):
    id: str
    trigger_id: str | None
    status: str
    started_at: datetime
    finished_at: datetime | None
    output: str | None
    error: str | None


def compute_next_run(expression: str, base: datetime) -> datetime:
    """Next fire time for a cron expression, preserving the base's timezone."""
    try:
        iterator = croniter(expression, base)
    except CroniterBadCronError as exc:
        raise ValueError(f"Invalid cron expression {expression!r}: {exc}") from exc
    return iterator.get_next(datetime)


def _trigger_out(trigger: AutomationTrigger) -> TriggerOut:
    return TriggerOut(
        id=trigger.id,
        kind=trigger.kind,
        name=trigger.name,
        cron_expression=trigger.cron_expression,
        action=trigger.action,
        enabled=trigger.enabled,
        webhook_token=trigger.webhook_token,
        next_run_at=trigger.next_run_at,
        last_run_at=trigger.last_run_at,
        created_at=trigger.created_at,
        updated_at=trigger.updated_at,
    )


def _job_run_out(run: AutomationJobRun) -> JobRunOut:
    return JobRunOut(
        id=run.id,
        trigger_id=run.trigger_id,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        output=run.output,
        error=run.error,
    )


# ---------------------------------------------------------------- scheduling


def _now_naive() -> datetime:
    """Current UTC as a naive datetime (SQLite drops tzinfo on read)."""
    return datetime.now(UTC).replace(tzinfo=None)


async def scheduler_loop(app: FastAPI) -> None:
    """Fire enabled cron triggers when their next_run_at is due.

    Wakes immediately when `app.state.automation_event` is set (a trigger was
    created, enabled or edited), otherwise polls at most every 60 seconds.
    """
    event: asyncio.Event = app.state.automation_event
    while True:
        now = _now_naive()
        due_ids: list[str] = []
        sleep_for = 60.0
        with Session(app.state.db.engine) as session:
            triggers = session.exec(
                select(AutomationTrigger).where(AutomationTrigger.enabled)
            ).all()
            for trigger in triggers:
                if trigger.kind != "cron" or not trigger.cron_expression:
                    continue
                if trigger.next_run_at is None:
                    trigger.next_run_at = compute_next_run(trigger.cron_expression, now)
                    session.add(trigger)
                # next_run_at is read back naive from SQLite; compare naive to naive.
                if trigger.next_run_at is not None and trigger.next_run_at <= now:
                    due_ids.append(trigger.id)
                else:
                    wait = (trigger.next_run_at - now).total_seconds()
                    if 0 < wait < sleep_for:
                        sleep_for = wait
            session.commit()
        for trigger_id in due_ids:
            try:
                await fire_trigger(app, trigger_id)
            except Exception:
                log.exception("automation trigger %s failed to start", trigger_id)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(event.wait(), timeout=min(max(sleep_for, 0.5), 60.0))
        event.clear()


# ---------------------------------------------------------------- running a trigger


async def fire_trigger(app: FastAPI, trigger_id: str) -> None:
    """Start one execution of `trigger`, recording a durable job run.

    Re-fetches the trigger inside its own session so detached objects from the
    scheduler's closed session never cause problems.
    """
    run_id = secrets.token_hex(8)
    started_at = _now_naive()

    # Capture the fields we need inside the session; the trigger object becomes
    # detached once the session closes, and the job body runs later.
    with Session(app.state.db.engine) as session:
        trigger = session.get(AutomationTrigger, trigger_id)
        if trigger is None or not trigger.enabled:
            return
        name = trigger.name
        action = dict(trigger.action)
        run = AutomationJobRun(
            id=run_id, trigger_id=trigger.id, status="running", started_at=started_at
        )
        session.add(run)
        if trigger.kind == "cron":
            trigger.last_run_at = started_at
            trigger.next_run_at = compute_next_run(trigger.cron_expression, started_at)
            trigger.updated_at = started_at
            session.add(trigger)
        session.commit()

    async def body(job: Job) -> None:
        error: str | None = None
        try:
            await run_trigger_action(app, action, job)
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__
            raise
        finally:
            finished_at = _now_naive()
            output = "\n".join(job.lines)
            with Session(app.state.db.engine) as session:
                record = session.get(AutomationJobRun, run_id)
                if record is not None:
                    record.status = "failed" if error else "succeeded"
                    record.finished_at = finished_at
                    record.output = output or None
                    record.error = error
                    session.add(record)
                    session.commit()

    app.state.jobs.start(f"Automation: {name}", body)


async def run_trigger_action(app: FastAPI, action: dict, job: Job) -> None:
    """Execute a stored action, streaming output into `job`."""
    if not isinstance(action, dict):
        raise ValueError("Automation action is missing")
    kind = action.get("kind")
    if kind == "app":
        await _run_app_action(app, action, job)
    elif kind == "package":
        await _run_package_action(app, action, job)
    else:
        raise ValueError(f"Unknown automation action kind: {kind!r}")


async def _run_app_action(app: FastAPI, action: dict[str, Any], job: Job) -> None:
    name = str(action["name"])
    verb = str(action["verb"])
    manifest = await app.state.capabilities.get()
    cap = manifest.get("containers")
    try:
        runtime = runtime_from(cap)
    except RuntimeUnavailableError as exc:
        raise RuntimeError(f"Container runtime unavailable: {exc}") from exc
    store = AppStore(app.state.settings.data_dir)
    path = store.compose_path(name)
    env = store.env(name)
    for args in APP_ACTIONS[verb]:
        await run_or_fail(
            job, compose(runtime, name, path, *args), f"docker compose {args[0]}", env=env
        )


async def _run_package_action(app: FastAPI, action: dict[str, Any], job: Job) -> None:
    manager = str(action["manager"])
    name = str(action["name"])
    verb = str(action["verb"])
    source = action.get("source")

    cls = MANAGERS.get(manager)
    if cls is None:
        raise ValueError(f"Unknown package manager: {manager}")
    manifest = await app.state.capabilities.get()
    cap = manifest.get(f"packages.{manager}")
    if cap is None or cap.status == "missing":
        raise RuntimeError(f"{manager} isn't installed on this host")
    if not cap.available:
        detail = f": {cap.detail}" if cap.detail else ""
        raise RuntimeError(f"{cls.label} isn't ready{detail}")

    pm = cls(app.state.package_runner)
    if verb == "install":
        argv = pm.install_argv(name, source)
    elif verb == "uninstall":
        argv = pm.uninstall_argv(name)
    elif verb == "upgrade":
        argv = pm.upgrade_argv(name)
    elif verb == "refresh":
        argv = pm.refresh_argv()
        if argv is None:
            raise RuntimeError(f"{cls.label} has no list refresh")
    else:
        raise ValueError(f"Unknown package verb: {verb}")

    await run_or_fail(job, resolve(argv), f"{manager} {verb}", env=command_env(pm.env))
