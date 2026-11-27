# 3. Platform layer and capability manifest

This is the core of the cross-platform requirement.

```python
# athena/platform/capabilities.py
class Capability(BaseModel):
    id: str                 # "containers", "packages.apt", "terminal.host", "shares.webdav"
    available: bool
    status: Literal["ready", "stopped", "missing", "unsupported", "needs_privilege"]
    provider: str | None    # "colima", "docker-engine", "winget"…
    detail: str | None      # human-readable reason / version
    actions: list[str]      # e.g. ["start", "setup"] for a stopped/missing runtime

class CapabilityManifest(BaseModel):
    os: Literal["linux", "darwin", "windows"]
    distro: str | None      # "ubuntu 24.04", "macOS 26", "Windows 11 24H2"
    arch: str
    capabilities: list[Capability]
```

- Detection runs at startup and on demand (`POST /api/system/capabilities/refresh`). It probes binaries (`shutil.which`), sockets and versions.
- `GET /api/system/capabilities` drives the UI. The sidebar, the package-manager tabs, the "Open terminal" buttons and the AI assistant's toolset are all filtered by it.
- **The AI agent gets the same filter.** Its tools are registered from the manifest, so it can't call `apt` on macOS.

## Container runtime per OS

| OS | Default | Alternatives detected | Notes |
|---|---|---|---|
| Linux | Docker Engine (Moby, `docker-ce`) | Podman (rootful socket) | Native socket `/var/run/docker.sock`. |
| macOS | **Colima** (`brew install colima docker docker-compose`) | Podman machine | Athena can run `colima start` and `colima status`. The socket is `~/.colima/default/docker.sock`. Volume paths must be under `$HOME` or a mount configured in Colima. |
| Windows | **Docker Engine inside WSL2** | Podman machine (WSL2 backend), Rancher Desktop (dockerd mode) | Docker Desktop is excluded because it isn't open source. Athena connects over a TCP/npipe endpoint or a relayed socket exposed by the WSL distro. Windows paths are translated to `/mnt/<drive>/…` for bind mounts. |

**Installing a runtime (onboarding wizard, `docs/specs/onboarding-wizard.md`).** The setup wizard, Settings and `athena onboard --runtime <id>` can install one on the admin's explicit click: Docker Engine / Podman through the distro package manager (Linux), Colima / Podman through Homebrew (macOS), Podman / Rancher Desktop through winget (Windows), and **Kiri** (Rust, Docker API, Apache-2.0) from a pinned release file checked against a pinned SHA-256 (`containers/installers.py`). Docker in WSL2 and FerroCrate (alpha) show manual steps only. Nothing is ever installed automatically. Detection also finds Kiri (via its `kiri` Docker context) and FerroCrate (its socket) after the usual ones.

**Windows (detect first).** Detection looks for Docker Engine in a WSL2 distro, Podman machine, or Rancher Desktop (dockerd mode), in that order of preference, and connects to the first one that responds. When none is found, the `containers` capability is `missing`, and the setup wizard shows step-by-step instructions for installing Docker Engine in WSL2 or Podman. Provisioning a WSL distro automatically is still not done (manual steps in the wizard). Windows containers are out of scope; only Linux containers are supported.

## Package managers per OS

| OS | Detected |
|---|---|
| Linux | apt, dnf, pacman, zypper, apk, flatpak, snap, brew (Linuxbrew) |
| macOS | brew (formulae + casks) |
| Windows | winget, scoop, choco |

Each one implements the same interface:

```python
class PackageManager(Protocol):
    id: str
    def search(self, q: str) -> list[PackageRef]: ...
    def installed(self) -> list[InstalledPackage]: ...
    def upgradable(self) -> list[InstalledPackage]: ...
    async def install(self, pkg: str, job: Job) -> None: ...
    async def uninstall(self, pkg: str, job: Job) -> None: ...
    async def upgrade(self, pkg: str | None, job: Job) -> None: ...
```

Use machine-readable output where it exists (`brew --json`, `winget --output json`…). Otherwise parse stable output formats, and pin those formats down in fixtures-based tests.

**As built (M5 part A).** `athena/packages/` (`base.py`, `linux.py`, `apps.py`, `windows.py`; `MANAGERS` keyed by capability id). Reads go through an async runner (no shell, `LC_ALL=C.UTF-8`, 120 s timeout) into pure parsers; changes are argv lists run as jobs, one job per manager at a time. Package names must start with a letter or digit, so nothing reaches a CLI as an option.

| Manager | Search | Installed | Upgradable | Notes |
|---|---|---|---|---|
| apt | `apt-cache search` (regex-escaped) | `dpkg-query -W -f` (tab format, `ii`/`hi` only) | `apt-get -s upgrade` `Inst` lines (`apt list` says its CLI isn't stable) | `DEBIAN_FRONTEND=noninteractive`, keeps existing conffiles; refresh = `apt-get update` |
| dnf | `dnf repoquery --qf` with real tab/newline characters (dnf5 doesn't expand `\t`; dnf4 adds a blank line) | `rpm -qa --qf` | `repoquery --upgrades` | Works on dnf4 and dnf5; refresh = `makecache` |
| zypper | `--xmlout search` (exit 104 = none) | `rpm -qa` | `--xmlout list-updates` | |
| pacman | `pacman -Ss` (regex-escaped) | `pacman -Q` | `pacman -Qu` | Installs use `-Syu --needed` and there's no single-package upgrade: Arch doesn't support partial upgrades |
| apk | `apk search -v` | `apk list --installed` (skips virtual `.deps`) | `apk list --upgradable` | |
| brew | `brew search`, then `brew info --json=v2` for the top 30 (`--desc` takes ~10 s) | `brew info --json=v2 --installed` | `brew outdated --json=v2` | Casks install with `--cask`; refresh = `brew update` |
| flatpak | `search --columns=…` (tabs) | `list --app --columns=…` | `remote-ls --updates` | Installs from the result's remote (default flathub) |
| snap | `snap find` (column table) | `snap list` | `snap refresh --list` | |
| winget | `winget search` (positional columns, so localized headers work) | `winget list` | `winget upgrade` | `--accept-*-agreements --disable-interactivity`; "no package found" isn't an error. Ids of locally installed apps contain spaces (`ARP\Machine\X64\Mozilla Firefox`); ids winget shortens with `…` can't be acted on, so the UI disables those rows |
| scoop | `scoop search` (dash-row table) | `scoop export` (JSON) | `scoop status` | `.cmd` shim resolved with `shutil.which` |
| choco | `--limit-output` (`name\|version`) | `choco list -r` | `choco outdated -r` | Machine-wide: needs an elevated Athena |

Fixtures (`tests/fixtures/packages/`, README says how each was captured): brew, apt, apk, dnf (4 and 5), zypper, pacman and flatpak search are real recordings, made in throwaway containers from the distros' own registries; winget's list is a real recording from the Windows CI runner; snap, Scoop, Chocolatey and the other winget files are hand-written from documented formats. Read-only tests run the real tool where it exists (brew on macOS, apt on Ubuntu, choco and winget on Windows CI). The first CI run caught a wrong assumption (winget ids can contain spaces), which is how the real winget fixture was captured.

## Privilege model

| OS | Athena runs as | Privileged ops |
|---|---|---|
| Linux | `root` systemd service, which is what CasaOS does too | Direct |
| macOS | The logged-in user, as a launchd agent | Not needed: brew refuses to run as root and Colima is per-user |
| Windows | The logged-in user, through a Scheduled Task at logon | winget/scoop are per-user. Machine-wide installs raise UAC on the desktop, and the UI warns about that |

The manifest reports `needs_privilege` when an operation can't be done as the current user.
