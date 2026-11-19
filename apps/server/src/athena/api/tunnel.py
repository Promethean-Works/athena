"""Tunnel API endpoints."""

import logging

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from athena import system_settings
from athena.auth.deps import Authed, DbSession, require_user
from athena.crypto import SecretBox, SecretError
from athena.jobs import Job, JobManager
from athena.platform.store import CapabilityStore
from athena.system_settings import SystemSettings, load, save
from athena.tunnel import get_provider
from athena.tunnel.base import TunnelConfig

log = logging.getLogger(__name__)

router = APIRouter(prefix="/tunnel", tags=["tunnel"], dependencies=[require_user])


def _jobs(request: Request) -> JobManager:
    return request.app.state.jobs


def _box(request: Request) -> SecretBox:
    return request.app.state.secret_box


def _require_admin(user: Authed) -> None:
    if not user.user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can manage the tunnel")


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


class TunnelConfigResponse(BaseModel):
    ok: bool
    settings: SystemSettings
    """Secrets are never returned; `settings.tunnel_secrets_set` lists the stored ones."""


@router.get("/status", response_model=TunnelStatusResponse)
async def get_tunnel_status(request: Request, db: DbSession) -> TunnelStatusResponse:
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

    # Check capability manifest for binary installation status
    store: CapabilityStore = request.app.state.capabilities
    caps = {c.id: c for c in (await store.get()).capabilities}
    capability_id = f"tunnel.{settings.tunnel_provider}"
    cap = caps.get(capability_id)

    # Get provider status
    status = provider.status()

    # Determine capability_status based on binary availability and tunnel running state
    if cap and cap.status == "missing":
        capability_status = "not_installed"
    elif status.running:
        capability_status = "ready"
    else:
        capability_status = "stopped"

    return TunnelStatusResponse(
        running=status.running,
        public_url=status.public_url,
        provider=status.provider,
        detail=status.detail,
        config=status.config,
        capability_status=capability_status,
    )


@router.post("/start", response_model=TunnelStartResponse)
async def start_tunnel(
    request: Request,
    db: DbSession,
    current_user: Authed,
) -> TunnelStartResponse:
    """Start the tunnel (admin only)."""
    _require_admin(current_user)
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

    try:
        provider_config = system_settings.provider_config(settings, _box(request))
    except SecretError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    config = TunnelConfig(port=settings.tunnel_port, provider_config=provider_config)

    jobs = _jobs(request)

    # Create a job to start the tunnel
    async def start_job(job: Job) -> None:
        try:
            url = await provider.start(job, config)
            await job.log(f"Tunnel started: {url}")
            # Store result in job lines for retrieval
            await job.log(f"RESULT: {url}")
        except Exception as e:
            await job.log(f"Tunnel start failed: {e}")
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
    """Stop the tunnel (admin only)."""
    _require_admin(current_user)
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
            await job.log("Tunnel stopped")
        except Exception as e:
            await job.log(f"Tunnel stop failed: {e}")
            raise

    job = jobs.start(
        f"Stop {provider.label} tunnel",
        stop_job,
    )

    return TunnelStartResponse(job_id=job.id)


@router.put("/config", response_model=TunnelConfigResponse)
async def update_tunnel_config(
    request: Request,
    body: TunnelConfigRequest,
    db: DbSession,
    current_user: Authed,
) -> TunnelConfigResponse:
    """Update tunnel configuration (admin only).

    Secrets left empty or out of `config` keep their stored value; `null` clears one."""
    _require_admin(current_user)
    settings = load(db)

    if body.provider is not None:
        settings.tunnel_provider = body.provider
    if body.config:
        settings.tunnel_config = system_settings.merge_tunnel_config(
            settings.tunnel_config, body.config, _box(request)
        )
    if body.auto_start is not None:
        settings.tunnel_auto_start = body.auto_start
    if body.port is not None:
        settings.tunnel_port = body.port

    save(db, settings)

    return TunnelConfigResponse(ok=True, settings=system_settings.public(settings))


@router.post("/install")
async def install_tunnel_binary(
    request: Request,
    body: TunnelInstallRequest,
    db: DbSession,
    current_user: Authed,
) -> TunnelStartResponse:
    """Download and install tunnel binary (admin only)."""
    _require_admin(current_user)
    provider = get_provider(f"tunnel.{body.provider}")
    if not provider:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown provider")

    jobs = _jobs(request)

    async def install_job(job: Job) -> None:
        try:
            await provider.install(job)
            await job.log(f"{provider.label} installed successfully")
        except Exception as e:
            await job.log(f"Install failed: {e}")
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
    _require_admin(current_user)
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
            await provider.configure_service(job, enabled, port=settings.tunnel_port)
            await job.log(f"Auto-start service {'enabled' if enabled else 'disabled'}")
        except Exception as e:
            await job.log(f"Service config failed: {e}")
            raise

    job = jobs.start(
        f"{'Enable' if enabled else 'Disable'} auto-start for {provider.label}",
        service_job,
    )

    return TunnelStartResponse(job_id=job.id)
