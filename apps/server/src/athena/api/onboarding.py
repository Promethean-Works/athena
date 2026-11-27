"""The setup wizard's state and the settings it alone sets (docs/specs/onboarding-wizard.md).

Language, locations, the runtime and the AI provider use the routes Settings already has;
this only reports which steps are done, saves the listen address and port, and records
that the wizard was finished.
"""

import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, ValidationError
from sqlmodel import select

from athena import audit, onboarding
from athena.api.settings import Appearance
from athena.auth.deps import Authed, DbSession, SettingsStore
from athena.db.models import AiProvider, FileLocation
from athena.onboarding import STEPS, StepId
from athena.platform.store import CapabilityStore
from athena.settings_file import SettingsFileError

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

BindAddress = Literal["0.0.0.0", "127.0.0.1"]


class StepOut(BaseModel):
    id: StepId
    done: bool


class NetworkSettings(BaseModel):
    host: BindAddress
    """`0.0.0.0` reaches Athena from other devices; `127.0.0.1` only from this host."""
    port: int = Field(ge=1, le=65535)


class OnboardingOut(BaseModel):
    completed: bool
    steps: list[StepOut]
    network: NetworkSettings
    restart_required: bool = False


def _admin(user: Authed) -> None:
    if not user.user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can do this")


def _language_set(raw: str | None) -> bool:
    try:
        return bool(raw) and Appearance.model_validate(json.loads(raw or "")).language != "auto"
    except (ValueError, ValidationError):
        return False


async def _out(
    request_store: CapabilityStore, user: Authed, db: DbSession, config: SettingsStore
) -> OnboardingOut:
    manifest = await request_store.get()
    containers = manifest.get("containers")
    server = config.get().server
    done: dict[StepId, bool] = {
        "account": True,
        "language": _language_set(user.user.appearance),
        "runtime": bool(containers and containers.available),
        "locations": db.exec(select(FileLocation)).first() is not None,
        "network": onboarding.is_completed(config),
        "ai": db.exec(select(AiProvider)).first() is not None,
    }
    return OnboardingOut(
        completed=onboarding.is_completed(config),
        steps=[StepOut(id=step, done=done[step]) for step in STEPS],
        network=NetworkSettings(host=server.host, port=server.port),  # pyright: ignore[reportArgumentType]
    )


def _capabilities(request: Request) -> CapabilityStore:
    return request.app.state.capabilities


@router.get("", operation_id="getOnboarding")
async def get_onboarding(
    request: Request, user: Authed, db: DbSession, config: SettingsStore
) -> OnboardingOut:
    _admin(user)
    return await _out(_capabilities(request), user, db, config)


@router.put("/network", operation_id="setOnboardingNetwork")
async def set_network(
    body: NetworkSettings, request: Request, user: Authed, db: DbSession, config: SettingsStore
) -> OnboardingOut:
    """Save where Athena listens (`server.host` and `server.port` in athena.json).
    It applies when Athena restarts."""
    _admin(user)
    try:
        config.check()
        server = config.section("server")
        changed = (server.host, server.port) != (body.host, body.port)
        server.host, server.port = body.host, body.port
        config.save("server", server)
    except SettingsFileError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    audit.record(db, user.user.username, "onboarding.network", f"{body.host}:{body.port}")
    out = await _out(_capabilities(request), user, db, config)
    out.restart_required = changed
    return out


@router.post("/complete", operation_id="completeOnboarding", status_code=status.HTTP_204_NO_CONTENT)
def complete(user: Authed, db: DbSession, config: SettingsStore) -> None:
    """Finish (or dismiss) the wizard; the dashboard stops offering it."""
    _admin(user)
    onboarding.mark(config, True)
    audit.record(db, user.user.username, "onboarding.complete", "")


@router.post("/reset", operation_id="resetOnboarding", status_code=status.HTTP_204_NO_CONTENT)
def reset(user: Authed, db: DbSession, config: SettingsStore) -> None:
    """Open the wizard again (the dashboard offers it until it's finished)."""
    _admin(user)
    onboarding.mark(config, False)
    audit.record(db, user.user.username, "onboarding.reset", "")
