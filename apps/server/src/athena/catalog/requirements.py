"""Host requirements of an app's optional parts (``x-athena.profiles[].requires``).

The ids are not capability ids: they are small checks over what the manifest already
says about the container runtime.
"""

from athena.catalog.model import ProfileMeta
from athena.platform.capabilities import CapabilityManifest

KNOWN_REQUIREMENTS: dict[str, str] = {
    "docker-socket": "needs the Docker socket, which this host's container runtime doesn't offer",
    "same-path-mounts": (
        "needs folders mounted at the same path inside and outside the container, "
        "which Windows host paths can't do"
    ),
}


def unmet_requirements(requires: list[str], manifest: CapabilityManifest) -> list[str]:
    """Reasons the host can't meet ``requires`` (empty when it can)."""
    containers = manifest.get("containers")
    ready = containers is not None and containers.available
    reasons: list[str] = []
    for need in requires:
        if need == "docker-socket":
            ok = ready
        elif need == "same-path-mounts":
            ok = ready and manifest.os != "windows"
        else:
            ok = False
        if not ok:
            reasons.append(KNOWN_REQUIREMENTS.get(need, f"needs {need}, which isn't available"))
    return reasons


def profile_problem(profile: ProfileMeta, manifest: CapabilityManifest, host_platform: str | None):
    """Why a profile can't be switched on here, or None."""
    reasons = unmet_requirements(profile.requires, manifest)
    if profile.platforms and host_platform and host_platform not in profile.platforms:
        reasons.append(f"isn't available for {host_platform}")
    return "; ".join(reasons) or None
