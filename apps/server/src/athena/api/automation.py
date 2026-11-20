"""Automation triggers and job runs.

Durable triggers (cron, HTTP webhook) that start background jobs. Trigger
management (`/triggers`, `/jobs`) needs a signed-in session. The webhook that
fires an HTTP trigger (`/webhook/{token}`) is public but protected by the
trigger's secret token, so external automation (n8n, MCP clients) can call it
without a browser session.
"""

import secrets
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request, status
from pydantic import BaseModel
from sqlmodel import select

from athena import audit
from athena.auth.deps import Authed, DbSession
from athena.automation import service as automation
from athena.db.models import AutomationJobRun, AutomationTrigger

router = APIRouter(prefix="/automation", tags=["automation"])
public_router = APIRouter(prefix="/automation", tags=["automation"])
"""Public routes: no session required. Protected by the trigger's webhook token."""

TriggerId = Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$", max_length=64)]
"""A trigger or job-run id: `secrets.token_hex(8)` is 16 lowercase hex chars."""


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------- triggers


@router.get("/triggers", operation_id="listAutomationTriggers")
def list_triggers(db: DbSession) -> list[automation.TriggerOut]:
    triggers = db.exec(select(AutomationTrigger).order_by(AutomationTrigger.name)).all()
    return [automation._trigger_out(t) for t in triggers]


@router.get("/triggers/{trigger_id}", operation_id="getAutomationTrigger")
def get_trigger(trigger_id: TriggerId, db: DbSession) -> automation.TriggerOut:
    trigger = db.get(AutomationTrigger, trigger_id)
    if trigger is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such automation trigger")
    return automation._trigger_out(trigger)


@router.post(
    "/triggers", operation_id="createAutomationTrigger", status_code=status.HTTP_201_CREATED
)
def create_trigger(
    body: automation.TriggerIn, request: Request, user: Authed, db: DbSession
) -> automation.TriggerOut:
    if body.kind == "cron" and not body.cron_expression:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "A cron trigger needs a cron_expression.",
        )
    if body.kind == "http" and body.cron_expression:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "An HTTP trigger does not use a cron expression.",
        )
    if body.kind == "cron":
        try:
            next_run = automation.compute_next_run(body.cron_expression, _now())
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    else:
        next_run = None

    trigger = AutomationTrigger(
        id=secrets.token_hex(8),
        kind=body.kind,
        name=body.name,
        cron_expression=body.cron_expression,
        action=body.action.model_dump(),
        enabled=body.enabled,
        webhook_token=secrets.token_hex(16) if body.kind == "http" else None,
        next_run_at=next_run,
    )
    db.add(trigger)
    db.commit()
    audit.record(
        db,
        user.user.username,
        "automation.trigger.create",
        trigger.name,
        detail=f"{trigger.kind}:{trigger.name}",
    )
    request.app.state.automation_event.set()
    return automation._trigger_out(trigger)


@router.patch("/triggers/{trigger_id}", operation_id="updateAutomationTrigger")
def update_trigger(
    trigger_id: TriggerId,
    body: automation.TriggerIn,
    request: Request,
    user: Authed,
    db: DbSession,
) -> automation.TriggerOut:
    trigger = db.get(AutomationTrigger, trigger_id)
    if trigger is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such automation trigger")

    trigger.name = body.name
    trigger.action = body.action.model_dump()
    trigger.enabled = body.enabled
    trigger.updated_at = _now()

    if body.kind == "cron":
        if not body.cron_expression:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "A cron trigger needs a cron_expression.",
            )
        trigger.kind = "cron"
        trigger.cron_expression = body.cron_expression
        try:
            trigger.next_run_at = automation.compute_next_run(body.cron_expression, _now())
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        trigger.webhook_token = None
    else:
        # Keep the token of a trigger that was already a webhook: toggling it (the
        # Enabled switch) must not break the URL n8n or a script already calls.
        if trigger.kind != "http" or not trigger.webhook_token:
            trigger.webhook_token = secrets.token_hex(16)
        trigger.kind = "http"
        trigger.cron_expression = None
        trigger.next_run_at = None

    db.add(trigger)
    db.commit()
    audit.record(
        db,
        user.user.username,
        "automation.trigger.update",
        trigger.name,
        detail=f"{trigger.kind}:{trigger.name}",
    )
    request.app.state.automation_event.set()
    return automation._trigger_out(trigger)


@router.delete(
    "/triggers/{trigger_id}",
    operation_id="deleteAutomationTrigger",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_trigger(trigger_id: TriggerId, request: Request, user: Authed, db: DbSession) -> None:
    trigger = db.get(AutomationTrigger, trigger_id)
    if trigger is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such automation trigger")
    name = trigger.name
    db.delete(trigger)
    db.commit()
    audit.record(db, user.user.username, "automation.trigger.delete", name)
    request.app.state.automation_event.set()


# ---------------------------------------------------------------- job runs


@router.get("/jobs", operation_id="listAutomationJobRuns")
def list_job_runs(
    db: DbSession, limit: Annotated[int, Query(ge=1, le=1000)] = 100
) -> list[automation.JobRunOut]:
    runs = db.exec(
        select(AutomationJobRun).order_by(AutomationJobRun.started_at.desc()).limit(limit)
    ).all()
    return [automation._job_run_out(r) for r in runs]


@router.get("/jobs/{run_id}", operation_id="getAutomationJobRun")
def get_job_run(run_id: TriggerId, db: DbSession) -> automation.JobRunOut:
    run = db.get(AutomationJobRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such automation job run")
    return automation._job_run_out(run)


# ---------------------------------------------------------------- trigger action validation


class TriggerActionIn(BaseModel):
    action: automation.TriggerAction


@router.post("/triggers/validate-action", operation_id="validateAutomationTriggerAction")
def validate_trigger_action(body: TriggerActionIn) -> dict[str, str]:
    """Checks that an action's shape is valid without storing a trigger."""
    return {"ok": "action is valid"}


# ---------------------------------------------------------------- webhook (public)


class WebhookOut(BaseModel):
    job_run_id: str
    status: str


@public_router.post(
    "/webhook/{webhook_token}",
    operation_id="fireAutomationWebhook",
    status_code=status.HTTP_202_ACCEPTED,
)
async def fire_webhook(
    webhook_token: Annotated[str, Path(max_length=64)],
    request: Request,
    db: DbSession,
) -> WebhookOut:
    """Fire the HTTP trigger with this secret token. No session required; the
    token itself is the credential (an n8n HTTP Request node, for example)."""
    trigger = db.exec(
        select(AutomationTrigger).where(AutomationTrigger.webhook_token == webhook_token)
    ).first()
    if trigger is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such webhook")
    if trigger.kind != "http" or not trigger.enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This webhook is not enabled")
    run_id = await automation.fire_trigger(request.app, str(trigger.id))
    return WebhookOut(job_run_id=run_id, status="started")
