"""Tunnel API endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from athena.auth.deps import Authed, DbSession, require_user
from athena.jobs import Job, JobManager
from athena.system_settings import load, save
from athena.tunnel import get_provider
from athena.tunnel.base import TunnelConfig

log = logging.getLogger(__name__)

router = APIRouter(prefix="/tunnel", tags=["tunnel"], dependencies=[require_user])


def _jobs(request: Request) -> JobManager:
    return request.app.state.jobs


class TunnelStatusResponse(BaseModel):
    running: bool
    public_url: str | None = None
    provider: str | None = None
    detail: str | None = None
    config: dict | None = None
    capability_status: str | None = None  # ready/stopped/missing


class TunnelConfigRequest(BaseModel):
    provider: str | None = None
    config: dict = {}
    auto_start: bool | None = None
    port: int | None = None


class TunnelStartResponse(BaseModel):
    job_id: str


class TunnelInstallRequest(BaseModel):
    provider: str


@router.get("/status", response_model=TunnelStatusResponse)
async def get_tunnel_status(db: DbSession) -> TunnelStatusResponse:
    """Get current tunnel status."""
    settings = load(db)

    if not settings.tunnel_enabled or not settings.tunnel_provider:
        return TunnelStatusResponse(
            running=False,
            provider=None,
            detail="Tunnel disabled",
            capability_status="missing",
        )

    provider = get_provider(f"tunnel.{settings.tunnel_provider}")
    if not provider:
        return TunnelStatusResponse(
            running=False,
            provider=settings.tunnel_provider,
            detail="Unknown provider",
            capability_status="missing",
        )

    # Get capability status from detection
    # This would come from the capability manifest
    # For now, we'll check the provider status
    status = provider.status()

    return TunnelStatusResponse(
        running=status.running,
        public_url=status.public_url,
        provider=status.provider,
        detail=status.detail,
        config=status.config,
        capability_status="ready" if status.running else "stopped",
    )


@router.post("/start", response_model=TunnelStartResponse)
async def start_tunnel(
    request: Request,
    db: DbSession,
    current_user: Authed,
) -> TunnelStartResponse:
    """Start the tunnel."""
    settings = load(db)

    if not settings.tunnel_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tunnel not enabled")

    if not settings.tunnel_provider:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No tunnel provider configured"
        )

    provider = get_provider(f"tunnel.{settings.tunnel_provider}")
    if not provider:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown provider")

    config = TunnelConfig(
        port=settings.tunnel_port,
        provider_config=settings.tunnel_config,
    )

    jobs = _jobs(request)

    # Create a job to start the tunnel
    async def start_job(job: Job) -> None:
        try:
            url = await provider.start(job, config)
            job.log(f"Tunnel started: {url}")
            job.set_result({"public_url": url})
        except Exception as e:
            job.log(f"Tunnel start failed: {e}")
            raise

    job = jobs.start(
        f"Start {provider.label} tunnel",
        start_job,
    )

    return TunnelStartResponse(job_id=job.id)


@router.post("/stop", response_model=TunnelStartResponse)
async def stop_tunnel(
    request: Request,
    db: DbSession,
    current_user: Authed,
) -> TunnelStartResponse:
    """Stop the tunnel."""
    settings = load(db)

    if not settings.tunnel_provider:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No tunnel provider configured"
        )

    provider = get_provider(f"tunnel.{settings.tunnel_provider}")
    if not provider:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown provider")

    jobs = _jobs(request)

    async def stop_job(job: Job) -> None:
        try:
            await provider.stop(job)
            job.log("Tunnel stopped")
        except Exception as e:
            job.log(f"Tunnel stop failed: {e}")
            raise

    job = jobs.start(
        f"Stop {provider.label} tunnel",
        stop_job,
    )

    return TunnelStartResponse(job_id=job.id)


@router.put("/config")
async def update_tunnel_config(
    request: TunnelConfigRequest,
    db: DbSession,
    current_user: Authed,
) -> dict[str, Any]:
    """Update tunnel configuration (admin only)."""
    settings = load(db)

    if request.provider is not None:
        settings.tunnel_provider = request.provider
    if request.config:
        settings.tunnel_config = request.config
    if request.auto_start is not None:
        settings.tunnel_auto_start = request.auto_start
    if request.port is not None:
        settings.tunnel_port = request.port

    save(db, settings)

    return {"ok": True, "settings": settings.model_dump()}


@router.post("/install")
async def install_tunnel_binary(
    request: Request,
    body: TunnelInstallRequest,
    db: DbSession,
    current_user: Authed,
) -> TunnelStartResponse:
    """Download and install tunnel binary (admin only)."""
    provider = get_provider(f"tunnel.{body.provider}")
    if not provider:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown provider")

    jobs = _jobs(request)

    async def install_job(job: Job) -> None:
        try:
            await provider.install(job)
            job.log(f"{provider.label} installed successfully")
        except Exception as e:
            job.log(f"Install failed: {e}")
            raise

    job = jobs.start(
        f"Install {provider.label}",
        install_job,
    )

    return TunnelStartResponse(job_id=job.id)


@router.put("/service")
async def configure_tunnel_service(
    request: Request,
    enabled: bool,
    db: DbSession,
    current_user: Authed,
) -> TunnelStartResponse:
    """Enable/disable auto-start service (admin only)."""
    settings = load(db)

    if not settings.tunnel_provider:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No tunnel provider configured"
        )

    provider = get_provider(f"tunnel.{settings.tunnel_provider}")
    if not provider:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown provider")

    jobs = _jobs(request)

    async def service_job(job: Job) -> None:
        try:
            await provider.configure_service(job, enabled)
            job.log(f"Auto-start service {'enabled' if enabled else 'disabled'}")
        except Exception as e:
            job.log(f"Service config failed: {e}")
            raise

    job = jobs.start(
        f"{'Enable' if enabled else 'Disable'} auto-start for {provider.label}",
        service_job,
    )

    return TunnelStartResponse(job_id=job.id)
