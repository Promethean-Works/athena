"""Container runtimes Athena can install for the admin (docs/specs/onboarding-wizard.md).

`options_for` lists what makes sense on a host (from its OS, arch and ready package
managers) and `plan_install` turns one choice into a fixed plan: argv lists and, for
Kiri, a pinned download. Package names, URLs and checksums are fixed here; nothing the
admin types reaches a command. `run_plan` runs a plan through whatever executes
commands (a job in the API, a plain subprocess in the CLI).
"""

import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from pydantic import BaseModel

from athena.downloads import DownloadError, fetch_verified
from athena.platform.capabilities import OsName

KIRI_VERSION = "0.2.2"
KIRI_BASE = f"https://github.com/libracoder/kiri/releases/download/v{KIRI_VERSION}/"
KIRI_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")
# From the release's SHA256SUMS, pinned here so a tampered download can't bring its own.
KIRI_FILES: dict[tuple[str, str], tuple[str, str]] = {
    ("deb", "x86_64"): (
        f"kiri_{KIRI_VERSION}_amd64.deb",
        "639f64abb7f3bd063a80ed1744e891156351c56cf2ad502633c47536c397a961",
    ),
    ("deb", "arm64"): (
        f"kiri_{KIRI_VERSION}_arm64.deb",
        "2b29a93a45f1597ed8c3239d3de28b7dbf91b813d61e53750ed9d6f216b09fb8",
    ),
    ("rpm", "x86_64"): (
        f"kiri-{KIRI_VERSION}-1.x86_64.rpm",
        "3b25696654deb1ea02858e7fb5798b709626f341aa2266db7cd3a606effe51ca",
    ),
    ("rpm", "arm64"): (
        f"kiri-{KIRI_VERSION}-1.aarch64.rpm",
        "a3237feaf4d0c98e131493c551a74de9310a8355f765678c964c57475bb9f603",
    ),
    ("msi", "x86_64"): (
        f"Kiri-{KIRI_VERSION}-x86_64.msi",
        "647128f8ca4831020da683f4301f16238d3417bc01519def687073e036271ca8",
    ),
    ("msi", "arm64"): (
        f"Kiri-{KIRI_VERSION}-arm64.msi",
        "6f759006c63a8be1d370b234062bf496b2799560a8f23c10f60eeaff2320dcd7",
    ),
}

FILE = "{file}"
"""In a plan's argv: the downloaded file's path."""


class RuntimeOption(BaseModel):
    id: str
    label: str
    description: str
    detected: bool = False
    """The host's current engine is this one."""
    recommended: bool = False
    tag: str | None = None
    """"new" or "experimental": shown next to the name."""
    can_install: bool = False
    """False: only `manual` steps (no package manager, or nothing to automate)."""
    manual: list[str] = []
    """Steps to do by hand when Athena can't install it."""


@dataclass(frozen=True)
class Download:
    url: str
    sha256: str
    filename: str


@dataclass(frozen=True)
class InstallPlan:
    option: str
    steps: list[list[str]]
    """Run in order; the first is the install, the rest set up the engine."""
    download: Download | None = None
    needs_root: bool = False
    """Linux package managers need root; brew and winget run as the user."""
    note: str | None = None


@dataclass(frozen=True)
class _Spec:
    id: str
    label: str
    description: str
    os: tuple[OsName, ...]
    tag: str | None = None
    recommended: dict[OsName, bool] = field(default_factory=dict)


SPECS: tuple[_Spec, ...] = (
    _Spec(
        "docker-engine",
        "Docker Engine",
        "The standard engine, from your distribution's packages.",
        ("linux",),
        recommended={"linux": True},
    ),
    _Spec(
        "wsl-docker",
        "Docker Engine in WSL2",
        "Docker running inside a WSL2 Linux distribution: open source, the usual choice here.",
        ("windows",),
        recommended={"windows": True},
    ),
    _Spec(
        "colima",
        "Colima",
        "A small Linux VM with Docker, installed with Homebrew.",
        ("darwin",),
        recommended={"darwin": True},
    ),
    _Spec(
        "podman",
        "Podman",
        "Daemonless, rootless-friendly engine from Red Hat.",
        ("linux", "darwin", "windows"),
    ),
    _Spec(
        "rancher-desktop",
        "Rancher Desktop",
        "SUSE's desktop app (use its dockerd mode).",
        ("windows",),
    ),
    _Spec(
        "kiri",
        "Kiri",
        "A fast container runtime written in Rust that speaks the Docker API.",
        ("linux", "darwin", "windows"),
        tag="new",
    ),
    _Spec(
        "ferrocrate",
        "FerroCrate",
        "A Rust container engine that runs containers on the Linux kernel, no VM. Alpha: "
        "install it yourself.",
        ("linux",),
        tag="experimental",
    ),
)

_MANUAL: dict[tuple[str, OsName], list[str]] = {
    ("docker-engine", "linux"): [
        "Install Docker Engine from https://docs.docker.com/engine/install/ for your distribution.",
        "Run: sudo systemctl enable --now docker",
    ],
    ("wsl-docker", "windows"): [
        "Open PowerShell as administrator and run: wsl --install -d Ubuntu",
        "Restart, open Ubuntu, then run: sudo apt-get update && sudo apt-get install -y docker.io",
        "Run: sudo usermod -aG docker $USER and restart the distro (wsl --shutdown).",
    ],
    ("colima", "darwin"): [
        "Install Homebrew (https://brew.sh), then: brew install colima docker docker-compose",
    ],
    ("podman", "linux"): [
        "Install Podman with your package manager, then run: "
        "sudo systemctl enable --now podman.socket"
    ],
    ("podman", "darwin"): ["Install Homebrew, then run: brew install podman docker"],
    ("podman", "windows"): ["Run: winget install -e --id RedHat.Podman, then podman machine init"],
    ("rancher-desktop", "windows"): [
        "Run: winget install -e --id SUSE.RancherDesktop, open it and pick the dockerd engine."
    ],
    ("kiri", "linux"): [
        "Download the .deb or .rpm from https://github.com/libracoder/kiri/releases and install it."
    ],
    ("kiri", "darwin"): ["Install Homebrew, then run: brew install --cask libracoder/kiri/kiri"],
    ("kiri", "windows"): ["Download the .msi from https://github.com/libracoder/kiri/releases."],
    ("ferrocrate", "linux"): [
        "Follow https://github.com/dgdev25/ferrocrate: install the .deb, then start the daemon "
        "with: ferro-cli daemon --docker-compat --socket /var/run/ferrocrate.sock",
    ],
}

_DOCKER_PACKAGE = {
    "apt": "docker.io",
    "dnf": "moby-engine",
    "pacman": "docker",
    "zypper": "docker",
    "apk": "docker",
}
_LINUX_MANAGERS = ("apt", "dnf", "pacman", "zypper", "apk")


def _normal_arch(arch: str) -> str:
    return "arm64" if arch.lower() in ("arm64", "aarch64") else "x86_64"


def _enable(manager: str, unit: str) -> list[list[str]]:
    if manager == "apk":
        return [["rc-update", "add", unit, "default"], ["service", unit, "start"]]
    return [["systemctl", "enable", "--now", unit]]


def _first(managers: set[str], wanted: tuple[str, ...]) -> str | None:
    return next((m for m in wanted if m in managers), None)


def _kiri_download(kind: str, arch: str) -> Download | None:
    entry = KIRI_FILES.get((kind, _normal_arch(arch)))
    return Download(KIRI_BASE + entry[0], entry[1], entry[0]) if entry else None


def plan_install(option: str, os_name: OsName, arch: str, managers: set[str]) -> InstallPlan | None:
    """The plan to install `option` here, or None when Athena can't (see `manual`)."""
    if os_name == "linux":
        return _plan_linux(option, arch, managers)
    if os_name == "darwin" and "brew" in managers:
        return _plan_darwin(option)
    if os_name == "windows":
        return _plan_windows(option, arch, managers)
    return None


def _plan_linux(option: str, arch: str, managers: set[str]) -> InstallPlan | None:
    if option == "docker-engine":
        manager = _first(managers, _LINUX_MANAGERS)
        if manager is None:
            return None
        install = {
            "apt": ["apt-get", "install", "-y", "docker.io"],
            "dnf": ["dnf", "install", "-y", "moby-engine"],
            "pacman": ["pacman", "-S", "--noconfirm", "docker"],
            "zypper": ["zypper", "--non-interactive", "install", "docker"],
            "apk": ["apk", "add", "docker"],
        }[manager]
        return InstallPlan(option, [install, *_enable(manager, "docker")], needs_root=True)
    if option == "podman":
        manager = _first(managers, _LINUX_MANAGERS)
        if manager is None:
            return None
        install = {
            "apt": ["apt-get", "install", "-y", "podman"],
            "dnf": ["dnf", "install", "-y", "podman"],
            "pacman": ["pacman", "-S", "--noconfirm", "podman"],
            "zypper": ["zypper", "--non-interactive", "install", "podman"],
            "apk": ["apk", "add", "podman"],
        }[manager]
        steps = [install] if manager == "apk" else [install, *_enable(manager, "podman.socket")]
        return InstallPlan(option, steps, needs_root=True)
    if option == "kiri":
        if "apt" in managers and (dl := _kiri_download("deb", arch)):
            return InstallPlan(option, [["apt-get", "install", "-y", FILE]], dl, needs_root=True)
        if (manager := _first(managers, ("dnf", "zypper"))) and (dl := _kiri_download("rpm", arch)):
            install = (
                ["dnf", "install", "-y", FILE]
                if manager == "dnf"
                else ["zypper", "--non-interactive", "install", "--allow-unsigned-rpm", FILE]
            )
            return InstallPlan(option, [install], dl, needs_root=True)
    return None


def _plan_darwin(option: str) -> InstallPlan | None:
    if option == "colima":
        return InstallPlan(option, [["brew", "install", "colima", "docker", "docker-compose"]])
    if option == "podman":
        return InstallPlan(
            option, [["brew", "install", "podman", "docker"], ["podman", "machine", "init"]]
        )
    if option == "kiri":
        return InstallPlan(
            option,
            [["brew", "install", "--cask", "libracoder/kiri/kiri"], ["brew", "install", "docker"]],
        )
    return None


def _plan_windows(option: str, arch: str, managers: set[str]) -> InstallPlan | None:
    if option == "podman" and "winget" in managers:
        return InstallPlan(
            option,
            [
                [
                    "winget",
                    "install",
                    "-e",
                    "--id",
                    "RedHat.Podman",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                ]
            ],
            note="Then run `podman machine init` and start the machine.",
        )
    if option == "rancher-desktop" and "winget" in managers:
        return InstallPlan(
            option,
            [
                [
                    "winget",
                    "install",
                    "-e",
                    "--id",
                    "SUSE.RancherDesktop",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                ]
            ],
            note="Open Rancher Desktop once and choose the dockerd (moby) engine.",
        )
    if option == "kiri" and (dl := _kiri_download("msi", arch)):
        return InstallPlan(option, [["msiexec", "/i", FILE, "/qn"]], dl)
    return None


def options_for(
    os_name: OsName, arch: str, managers: set[str], current_provider: str | None
) -> list[RuntimeOption]:
    """What to offer on this host, the detected one first, then the recommended one."""
    out = []
    for spec in SPECS:
        if os_name not in spec.os:
            continue
        plan = plan_install(spec.id, os_name, arch, managers)
        out.append(
            RuntimeOption(
                id=spec.id,
                label=spec.label,
                description=spec.description,
                detected=spec.id == current_provider,
                recommended=spec.recommended.get(os_name, False),
                tag=spec.tag,
                can_install=plan is not None,
                manual=[] if plan else _MANUAL.get((spec.id, os_name), []),
            )
        )
    return sorted(out, key=lambda o: (not o.detected, not o.recommended))


RunStep = Callable[[list[str]], Awaitable[None]]
Say = Callable[[str], Awaitable[None]]


async def run_plan(plan: InstallPlan, run_step: RunStep, say: Say) -> None:
    """Download (and verify) what the plan needs, then run its steps. Raises on failure."""
    steps = plan.steps
    if plan.download is not None:
        dl = plan.download
        with tempfile.TemporaryDirectory(prefix="athena-runtime-") as tmp:
            path = Path(tmp) / dl.filename
            try:
                data = await fetch_verified(
                    dl.url,
                    dl.sha256,
                    allowed=lambda url: any(
                        url.startswith(f"https://{host}/") for host in KIRI_HOSTS
                    ),
                    log_line=say,
                )
            except DownloadError as exc:
                raise RuntimeError(str(exc)) from exc
            path.write_bytes(data)
            await say(f"Checked {dl.filename} against its pinned SHA-256")
            for step in steps:
                await run_step([str(path) if part == FILE else part for part in step])
        return
    for step in steps:
        await run_step(step)


def with_privilege(plan: InstallPlan, is_root: bool) -> InstallPlan:
    """Prefix each root step with `sudo` when the caller isn't root (the CLI)."""
    if not plan.needs_root or is_root:
        return plan
    return replace(plan, steps=[["sudo", *step] for step in plan.steps])
