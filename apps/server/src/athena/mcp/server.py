"""MCP server: exposes Athena capabilities as tools over streamable HTTP.

Built inside `create_app()` so each tool closes over the running FastAPI app and
can reach `app.state` (jobs, db, capabilities, …). The authenticated user comes
from `athena.mcp.auth.mcp_current_user`, set by `MCPAuthMiddleware`.
"""

from __future__ import annotations

import secrets
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request, status
from fastmcp import FastMCP
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from athena import audit
from athena.api import apps as apps_api
from athena.auth.deps import CurrentUser
from athena.automation import service as automation_service
from athena.containers.runtime import RuntimeUnavailableError, runtime_from
from athena.db.models import App, AutomationJobRun, AutomationTrigger, User
from athena.mcp.auth import MCPPrincipal, require_mcp_user
from athena.platform.store import CapabilityStore

# Shapes returned to MCP clients. Kept small and explicit so external agents
# (n8n, custom clients) get a stable contract.


class AppSummary(BaseModel):
    name: str
    source: str
    status: str
    running: int
    total: int
    ports: list[str]


class AppActionOut(BaseModel):
    job_id: str
    status: str
    title: str


class PackageManagerOut(BaseModel):
    id: str
    label: str
    status: str
    available: bool


class JobRunOut(BaseModel):
    id: str
    status: str
    started_at: str
    finished_at: str | None
    error: str | None


class AutomationActionIn(BaseModel):
    kind: Literal["app", "package"]
    name: str = Field(min_length=1, max_length=63)
    verb: str
    manager: str | None = None
    package_name: str | None = None
    source: str | None = None


def _request(app: FastAPI) -> Request:
    """A bare request whose `.app` is the server, for helpers written for routes."""
    return Request({"type": "http", "app": app, "headers": []})


TOKEN_AUDIT_DETAIL = "via MCP token"
"""Audit detail on rows written for `ATHENA_MCP_TOKEN` clients (they act as the admin)."""


def _current_user(db: Session, principal: MCPPrincipal) -> CurrentUser:
    """The user a tool acts as. Token clients act as the oldest admin account."""
    if principal.via_token:
        user = db.exec(select(User).where(User.is_admin).order_by(User.created_at, User.id)).first()
        if user is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "ATHENA_MCP_TOKEN clients act as the admin user, but no admin account "
                "exists yet. Finish Athena's setup first.",
            )
    else:
        user = db.exec(select(User).where(User.username == principal.username)).first()
        if user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such user")
    return CurrentUser(user=user, session=None)


def _audit_detail(principal: MCPPrincipal, detail: str | None = None) -> str | None:
    """Mark audit rows written for token clients, so they aren't mistaken for the admin."""
    if not principal.via_token:
        return detail
    return f"{detail} ({TOKEN_AUDIT_DETAIL})" if detail else TOKEN_AUDIT_DETAIL


def _db(app: FastAPI) -> Session:
    return Session(app.state.db.engine)


async def _runtime(app: FastAPI):
    store: CapabilityStore = app.state.capabilities
    cap = (await store.get()).get("containers")
    try:
        return runtime_from(cap)
    except RuntimeUnavailableError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


def build_mcp_server(app: FastAPI) -> FastMCP:
    """Build the MCP server, registering tools that close over `app`."""
    mcp = FastMCP(
        name="Athena",
        instructions=(
            "Athena automation server. Tools let an external agent (n8n, Claude "
            "Desktop, Cursor…) start/stop apps, manage packages, read files and "
            "create cron-style automation triggers. Every tool is audited."
        ),
    )

    # ---------------------------------------------------------------- apps

    @mcp.tool
    async def list_apps() -> list[AppSummary]:
        """List Athena-managed apps (compose projects) with their status."""
        principal = require_mcp_user()
        with _db(app) as db:
            _current_user(db, principal)
            rows = db.exec(select(App).order_by(App.name)).all()
        return [
            AppSummary(
                name=a.name,
                source=a.source,
                status="unknown",
                running=0,
                total=0,
                ports=[],
            )
            for a in rows
        ]

    # ---------------------------------------------------------------- packages

    @mcp.tool
    async def list_package_managers() -> list[PackageManagerOut]:
        """List the package managers detected on this host."""
        principal = require_mcp_user()
        with _db(app) as db:
            _current_user(db, principal)
            caps = (await app.state.capabilities.get()).capabilities
        from athena.packages import MANAGERS

        out = []
        for cap in caps:
            if not cap.id.startswith("packages."):
                continue
            cls = MANAGERS.get(cap.id.removeprefix("packages."))
            if cls is None:
                continue
            out.append(
                PackageManagerOut(
                    id=cap.id.removeprefix("packages."),
                    label=cls.label,
                    status=cap.status,
                    available=cap.available,
                )
            )
        return out

    # ---------------------------------------------------------------- system

    @mcp.tool
    async def list_capabilities() -> list[dict[str, Any]]:
        """List host capabilities and their status (ready, stopped, missing…)."""
        require_mcp_user()
        caps = (await app.state.capabilities.get()).capabilities
        return [
            {"id": c.id, "label": c.label, "status": c.status, "detail": c.detail} for c in caps
        ]

    @mcp.tool
    async def host_stats() -> dict[str, Any]:
        """Current host stats (CPU, memory, disks)."""
        require_mcp_user()
        return app.state.monitor.snapshot()

    # ---------------------------------------------------------------- automation

    @mcp.tool
    async def list_automation_triggers() -> list[dict[str, Any]]:
        """List automation triggers (cron and webhook)."""
        require_mcp_user()
        with _db(app) as db:
            triggers = db.exec(select(AutomationTrigger).order_by(AutomationTrigger.name)).all()
        return [
            {
                "id": t.id,
                "kind": t.kind,
                "name": t.name,
                "cron_expression": t.cron_expression,
                "enabled": t.enabled,
                "next_run_at": t.next_run_at.isoformat() if t.next_run_at else None,
                "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
            }
            for t in triggers
        ]

    @mcp.tool
    async def create_automation_trigger(
        kind: Literal["cron", "http"],
        name: str,
        action: AutomationActionIn,
        cron_expression: str | None = None,
        enabled: bool = True,
    ) -> dict[str, str | None]:
        """Create a durable automation trigger.

        kind "cron" fires on `cron_expression` (e.g. "0 2 * * *"). kind "http"
        fires when its webhook is called (a secret token is returned). `action`
        describes the job: {"kind": "app", "name": "…", "verb": "start"} or
        {"kind": "package", "name": "…", "verb": "install", "manager": "apt"}.
        """
        principal = require_mcp_user()
        if kind == "cron" and not cron_expression:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "cron_expression required for cron triggers",
            )
        if kind == "cron":
            try:
                next_run = automation_service.compute_next_run(
                    cron_expression, automation_service._now_naive()
                )
            except ValueError as exc:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        else:
            next_run = None

        with _db(app) as db:
            user = _current_user(db, principal)
            trigger = AutomationTrigger(
                id=secrets.token_hex(8),
                kind=kind,
                name=name,
                cron_expression=cron_expression,
                action=action.model_dump(exclude_none=True),
                enabled=enabled,
                webhook_token=secrets.token_hex(16) if kind == "http" else None,
                next_run_at=next_run,
            )
            db.add(trigger)
            db.commit()
            audit.record(
                db,
                user.user.username,
                "automation.trigger.create",
                trigger.name,
                detail=_audit_detail(principal, f"{trigger.kind}:{trigger.name}"),
            )
            app.state.automation_event.set()
            return {"id": trigger.id, "webhook_token": trigger.webhook_token}

    @mcp.tool
    async def list_automation_job_runs(limit: int = 50) -> list[JobRunOut]:
        """List recent automation job runs."""
        require_mcp_user()
        with _db(app) as db:
            runs = db.exec(
                select(AutomationJobRun).order_by(AutomationJobRun.started_at.desc()).limit(limit)
            ).all()
        return [
            JobRunOut(
                id=r.id,
                status=r.status,
                started_at=r.started_at.isoformat(),
                finished_at=r.finished_at.isoformat() if r.finished_at else None,
                error=r.error,
            )
            for r in runs
        ]

    # ---------------------------------------------------------------- app lifecycle

    @mcp.tool
    async def app_action(
        name: str, verb: Literal["start", "stop", "restart", "update"]
    ) -> AppActionOut:
        """Start, stop, restart or update an Athena-managed app."""
        principal = require_mcp_user()
        runtime = await _runtime(app)
        with _db(app) as db:
            user = _current_user(db, principal)
            started = apps_api.start_app_action(
                name,
                verb,
                _request(app),
                runtime,
                user.user.username,
                db,
                detail=_audit_detail(principal),
            )
        return AppActionOut(job_id=started.id, status=started.status, title=started.title)

    return mcp
