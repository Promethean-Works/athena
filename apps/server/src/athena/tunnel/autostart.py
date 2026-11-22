"""Starting the configured tunnel: from the API and, when enabled, when the server boots."""

import logging

from fastapi import FastAPI

from athena import system_settings
from athena.jobs import Job
from athena.system_settings import SystemSettings
from athena.tunnel import get_provider
from athena.tunnel.base import TunnelConfig, TunnelProvider

log = logging.getLogger(__name__)


def start_job(app: FastAPI, provider: TunnelProvider, settings: SystemSettings) -> Job:
    """Start `provider` as a job. Raises `athena.crypto.SecretError` if a secret won't decrypt."""
    provider_config = system_settings.provider_config(settings, app.state.secret_box)
    config = TunnelConfig(port=settings.tunnel_port, provider_config=provider_config)

    async def body(job: Job) -> None:
        try:
            url = await provider.start(job, config)
            await job.log(f"Tunnel started: {url}")
            await job.log(f"RESULT: {url}")
        except Exception as e:
            await job.log(f"Tunnel start failed: {e}")
            raise

    return app.state.jobs.start(f"Start {provider.label} tunnel", body)


def auto_start(app: FastAPI) -> Job | None:
    """Start the tunnel at boot when it's enabled, has a provider and `tunnel_auto_start`
    is on. Never raises: a broken tunnel must not stop the server. Returns the job, if any."""
    try:
        settings = system_settings.load(app.state.settings_file)
        if not (settings.tunnel_enabled and settings.tunnel_auto_start):
            return None
        provider = get_provider(f"tunnel.{settings.tunnel_provider}")
        if provider is None:
            return None
        if provider.status().running:
            return None
        log.info("Starting the %s tunnel (auto-start is on)", provider.label)
        return start_job(app, provider, settings)
    except Exception:
        log.exception("Tunnel auto-start failed")
        return None
