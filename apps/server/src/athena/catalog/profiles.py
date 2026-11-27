"""Optional parts of a catalog app (Compose profiles): what's on, what can be switched on.

The choice lives in the app's ``.env`` as ``COMPOSE_PROFILES`` (Docker Compose reads it
on its own, so ``docker compose up`` by hand behaves the same), plus the values a
profile declares under ``env``.
"""

from pydantic import BaseModel

from athena.catalog.loader import InstallValueError
from athena.catalog.model import CatalogApp
from athena.catalog.requirements import profile_problem
from athena.platform.capabilities import CapabilityManifest

COMPOSE_PROFILES = "COMPOSE_PROFILES"


class ProfileState(BaseModel):
    id: str
    label: str
    description: str | None
    default: bool
    enabled: bool
    """On now (an installed app) or on by default (the install form)."""
    docker_access: bool
    """Its services mount the Docker socket."""
    disabled_reason: str | None
    """Why this host can't run it; None when it can."""


def states(
    app: CatalogApp,
    manifest: CapabilityManifest,
    host_plat: str | None,
    enabled: set[str] | None = None,
) -> list[ProfileState]:
    """Every profile of ``app`` with its state. ``enabled`` None means the defaults."""
    docker = set(app.variants[0].docker_access_profiles)
    out = []
    for p in app.meta.profiles:
        problem = profile_problem(p, manifest, host_plat)
        on = (p.id in enabled) if enabled is not None else p.default
        out.append(
            ProfileState(
                id=p.id,
                label=p.label,
                description=p.description,
                default=p.default,
                enabled=on and problem is None,
                docker_access=p.id in docker,
                disabled_reason=problem,
            )
        )
    return out


def choose(
    app: CatalogApp,
    chosen: list[str] | None,
    manifest: CapabilityManifest,
    host_plat: str | None,
) -> list[str]:
    """The profile ids to switch on. ``chosen`` None takes the defaults the host can run.

    Raises InstallValueError (field ``profiles``) for an unknown id or one this host can't run.
    """
    known = {s.id: s for s in states(app, manifest, host_plat)}
    if chosen is None:
        return [s.id for s in known.values() if s.default and s.disabled_reason is None]
    errors = []
    for pid in chosen:
        if pid not in known:
            errors.append(f"{pid}: no such option")
        elif known[pid].disabled_reason:
            errors.append(f"{known[pid].label} {known[pid].disabled_reason}")
    if errors:
        raise InstallValueError({"profiles": "; ".join(errors)})
    # Keep the app's own order, and drop duplicates.
    return [p.id for p in app.meta.profiles if p.id in set(chosen)]


def env_for(app: CatalogApp, enabled: list[str]) -> dict[str, str]:
    """The ``.env`` entries for a set of profiles: ``COMPOSE_PROFILES`` and their ``env``."""
    if not app.meta.profiles:
        return {}
    values: dict[str, str] = {COMPOSE_PROFILES: ",".join(enabled)}
    for p in app.meta.profiles:
        if p.id in enabled:
            values.update(p.env)
    return values


def profile_keys(app: CatalogApp) -> set[str]:
    """Every ``.env`` key profiles can set, so a switch-off can clear the ones it set."""
    keys = {COMPOSE_PROFILES} if app.meta.profiles else set()
    for p in app.meta.profiles:
        keys.update(p.env)
    return keys


def enabled_in(env: dict[str, str]) -> set[str]:
    return {x.strip() for x in env.get(COMPOSE_PROFILES, "").split(",") if x.strip()}
