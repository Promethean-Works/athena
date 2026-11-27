"""Installing a package manager Athena doesn't have yet (docs/specs/package-manager-ui.md).

Only official installers, downloaded to a temporary file from the vendor's own https site and
then run: never `curl | sh`. MacPorts' installer is checked against the SHA-256 GitHub
publishes for the release. Installers that need root run through `sudo` with the admin's
password (used once, never logged or stored).
"""

import platform
import re
import stat
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from athena.jobs import Job, run_or_fail
from athena.packages import http
from athena.packages.base import PackageError, command_env, resolve
from athena.platform.capabilities import Capability, OsName
from athena.platform.probe import Probe

MACPORTS_RELEASE = "https://api.github.com/repos/macports/macports-base/releases/latest"
HOMEBREW_SCRIPT = "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"
SCOOP_SCRIPT = "https://get.scoop.sh"
CHOCO_SCRIPT = "https://community.chocolatey.org/install.ps1"
FLATHUB_REPO = "https://dl.flathub.org/repo/flathub.flatpakrepo"

# Installing flatpak with the distro's own manager, by the manager that is ready here.
FLATPAK_PACKAGE_ARGV: dict[str, list[str]] = {
    "apt": ["apt-get", "install", "-y", "flatpak"],
    "dnf": ["dnf", "install", "-y", "flatpak"],
    "pacman": ["pacman", "-S", "--noconfirm", "--needed", "flatpak"],
    "zypper": ["zypper", "--non-interactive", "install", "flatpak"],
    "apk": ["apk", "add", "flatpak"],
}


class Requirement(BaseModel):
    label: str
    met: bool
    hint: str | None = None
    """What to do when it isn't met."""


class InstallableOut(BaseModel):
    id: str
    label: str
    summary: str
    site: str
    """The vendor's site, shown so the admin knows where it comes from."""
    requirements: list[Requirement]
    ready: bool
    """Every requirement is met."""
    needs_password: bool
    """The computer's password is needed (sudo), because Athena isn't root."""
    has_logo: bool = True


@dataclass(frozen=True)
class Installer:
    id: str
    label: str
    systems: tuple[OsName, ...]
    summary: str
    site: str
    logo_url: str
    hosts: tuple[str, ...]
    """Where its downloads (and its logo) may come from."""
    root: Literal["sudo", "refuses", "windows-admin", "no"]
    """sudo: installs system-wide, needs root or the password; refuses: its installer won't run
    as root; windows-admin: needs an elevated Athena; no: runs as the current user."""
    run: Callable[["Context"], Awaitable[None]] = field(repr=False, compare=False)
    checks: Callable[[Probe, dict[str, Capability]], list[Requirement]] = field(
        repr=False, compare=False
    )


@dataclass
class Context:
    job: Job
    probe: Probe
    capabilities: dict[str, Capability]
    password: str | None

    async def run(self, argv: list[str], what: str, env: dict[str, str] | None = None) -> None:
        """Run a command, with `sudo` when a password was given."""
        stdin = None
        if self.password:
            argv = ["sudo", "-S", "-k", "-p", "", *argv]
            stdin = self.password + "\n"
        await run_or_fail(self.job, resolve(argv), what, env=command_env(env), stdin=stdin)


# ---------------------------------------------------------------- requirements


def _req(label: str, met: bool, hint: str | None = None) -> Requirement:
    return Requirement(label=label, met=met, hint=None if met else hint)


def _command_line_tools(probe: Probe) -> Requirement:
    return _req(
        "Xcode command line tools",
        probe.run(["xcode-select", "-p"]).ok,
        "Run `xcode-select --install` on the Mac, then come back.",
    )


def _brew_checks(probe: Probe, caps: dict[str, Capability]) -> list[Requirement]:
    out = [
        _req(
            "Athena isn't running as root",
            not probe.is_root(),
            "Homebrew refuses to run as root. Run Athena as a normal user.",
        ),
        _req("git", bool(probe.which("git")), "Install git first."),
    ]
    if probe.os == "darwin":
        out.insert(0, _command_line_tools(probe))
    else:
        out.append(_req("curl", bool(probe.which("curl")), "Install curl first."))
    return out


def _macports_checks(probe: Probe, caps: dict[str, Capability]) -> list[Requirement]:
    return [_command_line_tools(probe), _req("sudo", bool(probe.which("sudo")), "sudo is missing.")]


def _flatpak_checks(probe: Probe, caps: dict[str, Capability]) -> list[Requirement]:
    system = [
        m
        for m in FLATPAK_PACKAGE_ARGV
        if (c := caps.get(f"packages.{m}")) and c.status != "missing"
    ]
    return [
        _req(
            "A system package manager",
            bool(system),
            "Athena found none of apt, dnf, pacman, zypper or apk.",
        ),
        _req("root or sudo", probe.is_root() or bool(probe.which("sudo")), "sudo is missing."),
    ]


def _scoop_checks(probe: Probe, caps: dict[str, Capability]) -> list[Requirement]:
    return [
        _req("PowerShell", bool(probe.which("powershell")), "Windows PowerShell is missing."),
        _req(
            "Athena isn't running as administrator",
            not probe.is_admin(),
            "Scoop refuses to install from an elevated session. Run Athena as your normal user.",
        ),
    ]


def _choco_checks(probe: Probe, caps: dict[str, Capability]) -> list[Requirement]:
    return [
        _req("PowerShell", bool(probe.which("powershell")), "Windows PowerShell is missing."),
        _req(
            "Athena is running as administrator",
            probe.is_admin(),
            "Chocolatey installs for every user. Start Athena as an administrator.",
        ),
    ]


# ---------------------------------------------------------------- installers


async def _fetch_script(ctx: Context, url: str, hosts: tuple[str, ...], dest: Path) -> None:
    await ctx.job.log(f"Downloading {url}")
    digest = await http.download(url, dest, hosts)
    await ctx.job.log(f"Saved {dest.name} (sha256 {digest})")


async def _install_brew(ctx: Context) -> None:
    env = {"NONINTERACTIVE": "1", "CI": "1"}
    with tempfile.TemporaryDirectory(prefix="athena-brew-") as tmp:
        script = Path(tmp) / "install.sh"
        await _fetch_script(ctx, HOMEBREW_SCRIPT, ("githubusercontent.com",), script)
        if ctx.password:
            # The installer needs sudo but must not run as root: it asks through SUDO_ASKPASS.
            # The script holds no password; it reads it from this process's environment.
            askpass = Path(tmp) / "askpass.sh"
            askpass.write_text('#!/bin/sh\nprintf "%s\\n" "$ATHENA_SUDO_PASSWORD"\n')
            askpass.chmod(stat.S_IRWXU)
            env |= {"SUDO_ASKPASS": str(askpass), "ATHENA_SUDO_PASSWORD": ctx.password}
            check = await ctx.job.run_command(["sudo", "-A", "-v"], env=command_env(env))
            if check != 0:
                raise PackageError("That password didn't work")
        code = await ctx.job.run_command(["/bin/bash", str(script)], env=command_env(env))
        if code != 0:
            raise PackageError(f"The Homebrew installer failed (exit code {code})")


async def _install_macports(ctx: Context) -> None:
    major = platform.mac_ver()[0].split(".")[0]
    release = await http.fetch_json(MACPORTS_RELEASE, {"Accept": "application/vnd.github+json"})
    pattern = re.compile(rf"^MacPorts-[\d.]+-{re.escape(major)}-[A-Za-z]+\.pkg$")
    asset = next((a for a in release.get("assets", []) if pattern.match(a.get("name", ""))), None)
    if asset is None:
        raise PackageError(
            f"MacPorts {release.get('tag_name', '')} has no installer for macOS {major} yet"
        )
    digest = str(asset.get("digest", ""))
    sha = digest.removeprefix("sha256:") if digest.startswith("sha256:") else None
    if sha is None:
        await ctx.job.log("GitHub published no checksum for this file; relying on https only")
    with tempfile.TemporaryDirectory(prefix="athena-macports-") as tmp:
        pkg = Path(tmp) / asset["name"]
        await ctx.job.log(f"Downloading {asset['name']} ({release.get('tag_name')})")
        got = await http.download(
            asset["browser_download_url"], pkg, ("github.com", "githubusercontent.com"), sha
        )
        await ctx.job.log(f"Checksum {got}" + (" matches GitHub's" if sha else ""))
        await ctx.run(
            ["/usr/sbin/installer", "-pkg", str(pkg), "-target", "/"], "MacPorts installer"
        )


async def _install_flatpak(ctx: Context) -> None:
    manager = next(
        (
            m
            for m in FLATPAK_PACKAGE_ARGV
            if (c := ctx.capabilities.get(f"packages.{m}")) and c.status != "missing"
        ),
        None,
    )
    if manager is None:
        raise PackageError("No system package manager found to install Flatpak with")
    await ctx.run(FLATPAK_PACKAGE_ARGV[manager], f"{manager} install flatpak")
    await ctx.run(
        ["flatpak", "remote-add", "--if-not-exists", "flathub", FLATHUB_REPO],
        "add the Flathub remote",
    )


async def _powershell_script(ctx: Context, url: str, hosts: tuple[str, ...], what: str) -> None:
    with tempfile.TemporaryDirectory(prefix="athena-ps-") as tmp:
        script = Path(tmp) / "install.ps1"
        await _fetch_script(ctx, url, hosts, script)
        argv = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
        await ctx.run(argv, what)


async def _install_scoop(ctx: Context) -> None:
    await _powershell_script(
        ctx, SCOOP_SCRIPT, ("scoop.sh", "githubusercontent.com"), "Scoop installer"
    )


async def _install_choco(ctx: Context) -> None:
    await _powershell_script(ctx, CHOCO_SCRIPT, ("chocolatey.org",), "Chocolatey installer")


INSTALLERS: dict[str, Installer] = {
    i.id: i
    for i in (
        Installer(
            "brew",
            "Homebrew",
            ("darwin", "linux"),
            "The missing package manager for macOS and Linux: command-line tools and apps.",
            "brew.sh",
            "https://brew.sh/assets/img/homebrew-256x256.png",
            ("brew.sh", "githubusercontent.com"),
            "refuses",
            _install_brew,
            _brew_checks,
        ),
        Installer(
            "macports",
            "MacPorts",
            ("darwin",),
            "Open-source ports collection for macOS, installed under /opt/local.",
            "macports.org",
            "https://www.macports.org/img/macports-logo.png",
            ("macports.org", "github.com", "githubusercontent.com"),
            "sudo",
            _install_macports,
            _macports_checks,
        ),
        Installer(
            "flatpak",
            "Flatpak",
            ("linux",),
            "Sandboxed desktop apps from Flathub, installed with your distribution's own manager.",
            "flatpak.org",
            "https://flatpak.org/favicon.ico",
            ("flatpak.org", "flathub.org"),
            "sudo",
            _install_flatpak,
            _flatpak_checks,
        ),
        Installer(
            "scoop",
            "Scoop",
            ("windows",),
            "A command-line installer for Windows that installs for your user only.",
            "scoop.sh",
            "https://scoop.sh/favicon.ico",
            ("scoop.sh",),
            "no",
            _install_scoop,
            _scoop_checks,
        ),
        Installer(
            "choco",
            "Chocolatey",
            ("windows",),
            "The package manager for Windows software, installed for all users.",
            "chocolatey.org",
            "https://community.chocolatey.org/favicon.ico",
            ("chocolatey.org",),
            "windows-admin",
            _install_choco,
            _choco_checks,
        ),
    )
}


def installable(probe: Probe, caps: dict[str, Capability]) -> list[InstallableOut]:
    """The managers Athena can add on this host (not already there), with what each needs."""
    out = []
    for inst in INSTALLERS.values():
        cap = caps.get(f"packages.{inst.id}")
        if probe.os not in inst.systems or (cap is not None and cap.status != "missing"):
            continue
        reqs = inst.checks(probe, caps)
        # Root or the admin's password: only one is needed.
        needs_password = inst.root in ("sudo", "refuses") and not probe.is_root()
        out.append(
            InstallableOut(
                id=inst.id,
                label=inst.label,
                summary=inst.summary,
                site=inst.site,
                requirements=reqs,
                ready=all(r.met for r in reqs),
                needs_password=needs_password,
            )
        )
    return out


def password_for(probe: Probe, inst: Installer, password: str | None) -> str | None:
    """The password to run `inst` with: needed only when it installs system-wide and Athena
    isn't root. Raises `PackageError` when it is needed and missing."""
    if inst.root in ("sudo", "refuses") and not probe.is_root():
        if not password:
            raise PackageError("Enter your computer's password to continue")
        return password
    return None


async def run_installer(
    job: Job,
    inst: Installer,
    probe: Probe,
    caps: dict[str, Capability],
    password: str | None,
    refresh: Callable[[], Awaitable[object]],
) -> None:
    """The job body: run the installer, then re-detect so the new tab appears."""
    unmet = [r for r in inst.checks(probe, caps) if not r.met]
    if unmet:
        raise PackageError(f"{unmet[0].label}: {unmet[0].hint or 'not met'}")
    await inst.run(Context(job, probe, caps, password))
    await job.log(f"{inst.label} installed. Looking for it…")
    await refresh()
