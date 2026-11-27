# Spec: Package manager UI

**Status:** Approved (2026-11-27) · **Milestone:** M5 follow-up · **Design:** `docs/design/platform.md` (Package managers per OS)

## Goal

The Packages page becomes a full package-manager UI: search finds what people mean (`vscode` finds Homebrew's `visual-studio-code`), each manager tab shows its logo, a search result opens a details view (description, homepage, license, versions, dependencies, icon) before installing, and an admin can install another package manager the OS supports (MacPorts on macOS, Homebrew on Linux, Scoop on Windows…). For the admin of a home server who wants to manage host software without a terminal.

## Non-goals

- No new package manager implementations beyond the install-a-manager list in part 3 (MacPorts is the only new one with search/install support; see open questions).
- No auto-installing a manager during setup, no managing manager config (taps, buckets, repos), no package pinning.
- No Docker/Compose apps (that's the store).

## Platforms

| OS | Managers offered to install | Needs |
|---|---|---|
| macOS | Homebrew, MacPorts | Homebrew: Xcode CLT; MacPorts: Xcode CLT, admin (sudo) |
| Linux | Homebrew (Linuxbrew), Flatpak, Snap where the distro's own manager can install them | root (the default service) |
| Windows | Scoop, Chocolatey, WinGet (App Installer) | Scoop: per-user; Chocolatey: elevated |

A new capability-style list `installable` on `GET /api/packages` says which managers *can* be installed here and why not if blocked (no curl, not root, no Xcode CLT). Hosts that can't install any show nothing.

## Design

### Part 1: search that finds what you mean (server)

- **Cause:** `brew search vscode` only matches token substrings; the cask is `visual-studio-code` with name `Microsoft Visual Studio Code` / `VS Code`.
- **Fix, Homebrew:** search Homebrew's own local API cache (`formula.jws.json`/`cask.jws.json` under `brew --cache`/`api`, refreshed by `brew update`; fall back to the current `brew search` if the files are missing). Match a normalized query (lowercase, punctuation and spaces removed) against token, display names and description, ranked: exact token, token prefix, name match (so `vscode` ≈ `VS Code`), then description. Merge with `brew search` hits.
- **Other managers:** a shared `expand_query()` adds common aliases (`vscode`→`visual studio code`, `chrome`→`google chrome`, `node`→`nodejs`…) from a small table in `athena/packages/aliases.py`, plus a second search with spaces/hyphens swapped. Results are merged and de-duplicated by name. Most managers already search descriptions (apt-cache, dnf, winget), so only the alias layer is needed there.
- Fixtures for the cask index (trimmed real recording) and tests: `vscode`, `vs code`, `visual studio code` all return `visual-studio-code` first.

### Part 2: details view + icons (server and web)

- **Server:** `GET /api/packages/{manager}/info?name=&source=` (`getPackageInfo`) returns `PackageDetails`: `name, title, version, description, homepage, license, source, installed, installed_version, size, dependencies, icon_url, maintainer, extra[]`. Per manager: `brew info --json=v2`, `apt-cache show`, `dnf info`/`rpm -qi`, `pacman -Si`, `zypper info`, `apk info -a`, `flatpak remote-info`, `snap info`, `winget show`, `scoop info`, `choco info -r`. Parsers are pure and fixture-tested like the existing ones. Info results are cached for 10 minutes.
- **Icons:** `icon_url` comes from the manager when it has one (Flatpak appstream icon, Snap `snap info` media, winget `Icon` field, Homebrew casks via the app's own favicon is *not* used); otherwise null and the UI shows a letter avatar. Remote icons are fetched through `GET /api/packages/icon?url=` (proxy that only allows `https` to a fixed allow-list of hosts per manager, size-capped, cached) so the browser never contacts third parties directly and CSP stays strict.
- **Web:** in `manager-panel.tsx` each search/installed row gets a "Details" action opening a sheet (shadcn `Sheet`): icon, title, version, description, links (homepage opens in a new tab), license, dependencies, size, and the same Install / Uninstall / Upgrade buttons. Install from search can go straight there ("Install" stays on the row).
- **Tab icons:** nothing is bundled in the repo. Each manager's logo and each package's icon comes from that manager or its own store, fetched through the icon proxy: Homebrew `brew.sh`, MacPorts `macports.org`, Flatpak the remote's appstream icon (Flathub), Snap the Snap Store media, winget the manifest `Icon`, Scoop/Chocolatey their site/package-feed icons. The proxy allow-list is per manager. Where the store gives none (or offline), the UI shows a letter avatar.

### Part 3: install a package manager (server and web)

- **Server:** `athena/packages/bootstrap.py` with an `INSTALLABLE` table per manager id: supported OSes, prerequisites checked with the existing probe, and an install **job** (argv, no shell). Official installers only, pinned URLs, downloaded to a temp file and run (never `curl | sh`): Homebrew `install.sh` (`NONINTERACTIVE=1`), Scoop `get.scoop.sh`, Chocolatey `install.ps1`, MacPorts the signed `.pkg` for the detected macOS version through `installer`. `POST /api/packages/{manager}/bootstrap` (`installPackageManager`, admin only, audited as `package.bootstrap`), rejects ids not offered for this OS/arch. After success the capability store re-detects, so the tab appears.
- **Web:** an "Add a package manager" card/dialog on the Packages page lists installable managers with logo, what it is, prerequisites (met or not), and a streaming job log (existing job UI). Confirmation dialog states what will be downloaded and run, and that it needs admin rights.
- **Assistant / MCP:** none (read-only search/info tools may be added later; bootstrap is never an assistant tool).
- **Security:** admin only; fixed installer URLs with SHA-256 pins where the vendor publishes one (MacPorts), HTTPS only otherwise; names validated by the existing patterns; icon proxy allow-listed; everything audited. Uninstalling a manager is out of scope.
- **Dependencies:** none new. No logo files are added to the repo.

## Parts

All in one branch and one PR (maintainer's rule), one commit per part:

1. Search quality (Homebrew index + aliases) with fixtures and tests.
2. Details endpoint, icon proxy, tab icons, details sheet.
3. Bootstrap endpoint + "Add a package manager" UI; MacPorts support (search/installed/upgradable/install/uninstall, `port` argv, `sudo`).

## Acceptance checks

- Unit: query expansion and ranking; each new info parser against fixtures; bootstrap rejects unsupported OS/id; icon proxy rejects non-allow-listed hosts, non-https, oversize.
- Browser (`athena-ui-verify`, fake runner, port 8421+): `vscode` search lists Visual Studio Code first; tabs show icons; details sheet opens with and without an icon; bootstrap dialog shows prerequisites and streams a faked job.
- Real host (`athena-host-test`): brew search + info on macOS now; Homebrew install on a Lima VM; MacPorts, Scoop and Chocolatey are **not** verifiable here and will be listed under "Not tested yet".
- Failure cases: manager missing, no network, installer fails (job error shown, no tab added), non-root on Linux.

## Open questions

- ~~Which logo marks?~~ Decided: the managers' own official logos/icons from their store, never bundled.
- **MacPorts depth?** Recommendation: full manager (part 3) so installing it is useful; its search needs `port search --name --glob`, `port installed`, `port outdated`.
- **Linux: offer Flatpak/Snap installs?** Recommendation: yes via the distro's own manager (`apt install flatpak`), as a later add-on if part 3 grows; Homebrew/Linuxbrew first.
- **Homebrew index vs. `brew search --desc`?** Recommendation: the local API index (instant, offline); `--desc` takes ~10 s.
- **Details icons for apt/dnf?** They have none; recommendation: letter avatar, no AppStream lookups for now.
