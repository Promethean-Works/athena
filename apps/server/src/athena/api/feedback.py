"""In-app feedback: the diagnostics a report includes, and the issue URL to open.

Nothing is sent from here; the browser opens the URL and the user submits the issue.
See docs/specs/feedback.md and athena/feedback.py.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from athena import feedback
from athena.api.system import system_info
from athena.auth.deps import DbSession
from athena.catalog.model import APP_ID
from athena.catalog.registry import BUILTIN, CatalogRegistry
from athena.db.models import Catalog
from athena.platform.capabilities import CapabilityManifest
from athena.platform.detect import CONTAINERS
from athena.platform.store import CapabilityStore

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackInfo(BaseModel):
    """What every report includes. No hostname, addresses, paths or secrets."""

    version: str
    os_version: str
    arch: str
    runtime: str
    """The container runtime, e.g. "colima (Docker 27.3)", or "no container runtime"."""
    repo_url: str


class IssueIn(BaseModel):
    kind: feedback.Kind
    title: str = Field(default="", max_length=200)
    catalog: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    """For `app` reports: the store app's catalog ("builtin" or a remote catalog id)."""
    app_id: str | None = Field(default=None, pattern=APP_ID)
    logs: str = Field(default="", max_length=200_000)
    """Only what the user chose to include, after seeing it."""


class IssueUrl(BaseModel):
    url: str
    target: Literal["athena", "catalog"]
    """Athena's own repository, or the app's catalog repository."""
    target_name: str
    """Human name of where it goes, e.g. "Promethean-Works/athena" or "Big Bear catalog"."""
    logs_truncated: bool


def _runtime(manifest: CapabilityManifest) -> str:
    cap = manifest.get(CONTAINERS)
    if cap is None or not cap.available:
        return "no container runtime"
    # The detail ends with the engine's socket ("Engine 29.5 at /Users/me/.colima/…"),
    # which names the user's home folder; issues are public, so keep only the version.
    detail = (cap.detail or "").split(" at ")[0].strip()
    if "/" in detail or "\\" in detail:
        detail = ""
    return " ".join(p for p in (cap.provider, f"({detail})" if detail else None) if p)


async def _info(request: Request) -> FeedbackInfo:
    capabilities: CapabilityStore = request.app.state.capabilities
    host = system_info()
    return FeedbackInfo(
        version=host.version,
        os_version=host.os_version,
        arch=host.arch,
        runtime=_runtime(await capabilities.get()),
        repo_url=request.app.state.settings.feedback_repo,
    )


def _repo_name(url: str) -> str:
    repo = feedback.repo_of(url)
    return repo[1] if repo else url


@router.get("", operation_id="getFeedbackInfo")
async def get_feedback_info(request: Request) -> FeedbackInfo:
    return await _info(request)


@router.post("/issue-url", operation_id="buildIssueUrl")
async def build_issue_url(body: IssueIn, request: Request, db: DbSession) -> IssueUrl:
    """The new-issue URL for a report, with what Athena knows already filled in."""
    info = await _info(request)
    environment = feedback.environment_line(info.os_version, info.arch, info.runtime)
    logs, truncated = feedback.trim_logs(body.logs)
    athena_name = _repo_name(info.repo_url)

    if body.kind != "app":
        fields = {"title": body.title, "version": info.version, "os-details": environment}
        return IssueUrl(
            url=feedback.form_url(info.repo_url, body.kind, fields),
            target="athena",
            target_name=athena_name,
            logs_truncated=False,
        )

    if body.catalog is None or body.app_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "App reports need catalog and app_id"
        )
    registry: CatalogRegistry = request.app.state.catalogs
    app = registry.get(body.catalog, body.app_id)
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No store app {body.catalog}/{body.app_id}")
    title = body.title or f"{app.meta.title}: "
    source = db.get(Catalog, body.catalog) if body.catalog != BUILTIN else None

    if source is not None and feedback.repo_of(source.url):
        report = feedback.app_report_body(
            app_id=app.id,
            title=app.meta.title,
            images=app.images,
            version=info.version,
            environment=environment,
            logs=logs,
        )
        return IssueUrl(
            url=feedback.plain_url(source.url, title, report),
            target="catalog",
            target_name=source.name,
            logs_truncated=truncated,
        )

    fields = {
        "title": title,
        "app": app.id,
        "catalog": source.url if source else BUILTIN,
        "images": ", ".join(app.images),
        "version": info.version,
        "os-details": environment,
        "logs": logs,
    }
    return IssueUrl(
        url=feedback.form_url(info.repo_url, "app", fields),
        target="athena",
        target_name=athena_name,
        logs_truncated=truncated,
    )
