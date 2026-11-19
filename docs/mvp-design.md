# Athena — MVP Design

Athena is a self-hosted home server control panel in the spirit of CasaOS, that runs on **Linux, macOS and Windows**. It manages containers (Docker/Compose), host package managers, files, shares and cloud storage, and includes an AI assistant that can drive all of it.

Hard rules that shape every decision below:

1. **Cross-platform.** Every feature goes through a platform provider. Nothing in the API or UI assumes Linux.
2. **Show only what exists.** The backend detects what the host has and publishes a *capability manifest*. The UI renders navigation, pages and actions from that manifest. If `apt` isn't on the box, the user never sees an apt option.
3. **Open-source dependencies only.** No Docker Desktop, no macFUSE, no proprietary SDKs. Licenses are listed in [§9](#9-dependency--license-inventory).

---

## 1. MVP scope

| Area | In the MVP | Later |
|---|---|---|
| Dashboard | Host stats (CPU, RAM, disk, network, uptime), running apps grid, runtime status | Custom widget layout, multi-node |
| Container runtime | Detect, report status, start the runtime (Colima on macOS), guided setup when missing | One-click runtime install on every OS |
| Apps (containers) | List, start/stop/restart, logs, stats, remove, update image | Backups, auto-update policy |
| App store | Built-in catalog plus remote catalogs (Git/HTTP), install with editable env/ports/volumes | Ratings, signed catalogs |
| Custom apps | Import a `docker run` command, paste/upload a `compose.yaml`, edit before deploy | Import from a Git repo |
| Package managers | Search, install, uninstall, list installed, upgrade, for each detected manager | Scheduled upgrades |
| Terminal | Web terminal to the host shell (bash/zsh/PowerShell) and `exec` into containers | Session sharing, recordings |
| Files | Browse, upload, download, rename, move, delete, preview text and images | Thumbnails, search index |
| File sharing | Public/expiring share links, WebDAV share of chosen folders, SMB shares on Linux | SMB on macOS and Windows, NFS |
| Cloud storage | Add remotes via rclone (Google Drive, OneDrive, Dropbox, S3, WebDAV…), browse, copy/sync jobs | Mounts as local drives, scheduled sync |
| AI assistant | Chat that can query state and do actions through Athena's own services, with approval for destructive actions | Proactive alerts, runbooks |
| Settings | Appearance (style, base color, theme, chart color, heading font, body font, radius), users, AI provider, catalogs | RBAC, SSO |
| Auth | Single admin account, created in a first-run wizard | Multiple users with roles |
| Automation (M8) | Cron and webhook triggers that run app and package actions, and an MCP server for outside agents (§4.7) | Event triggers |
| Remote access | Cloudflare Tunnel, Tailscale Funnel or ngrok, set up from Settings → System (§4.8) | Athena starting the tunnel itself at boot |

---

## 2. Architecture

```
┌──────────────────────────── Browser ───────────────────────────┐
│  Next.js (static export) + shadcn/ui  ·  xterm.js  ·  AI chat  │
└───────────────▲──────────── REST / SSE / WebSocket ────────────┘
                │                 MCP clients, webhooks, tunnels
┌───────────────┴─────────── athena-server (Python, uv) ─────────┐
│ api/ (thin FastAPI routers) → the area packages below          │
│                                                                │
│ platform/    probe · detect ─► CapabilityManifest              │
│ containers/  Docker-compatible CLI: Docker Engine, Colima,     │
│              Podman, Docker in WSL                             │
│ apps/ catalog/   compose apps, built-in and remote catalogs    │
│ packages/    apt dnf pacman zypper apk brew flatpak snap       │
│              winget scoop choco                                │
│ terminal/    stdlib pty (POSIX) · pywinpty (Windows)           │
│ files/       locations · share links · WebDAV · SMB            │
│ cloud/       rclone rcd (sidecar process)                      │
│ assistant/   pydantic-ai Agent + harness + Athena tools        │
│ automation/  cron and webhook triggers                         │
│ mcp/         Athena's MCP server at /api/mcp                   │
│ tunnel/      cloudflared · tailscale · ngrok                   │
│ service/     athena service install (systemd, launchd, Task)   │
│ auth/ db/ jobs.py (in memory) audit.py monitor.py crypto.py    │
│ SQLite: users, sessions, apps, settings, file locations,       │
│         shares, AI chats, audit log, automation triggers/runs  │
└────────────────────────────────────────────────────────────────┘
        │ Docker-compatible CLI   │ CLI subprocess       │ HTTP
   Docker Engine / Colima /   package managers       rclone rcd
   Podman / Docker in WSL
```

### Decisions

- **One backend process serves everything.** Next.js is built with `output: "export"` and the static files are served by FastAPI. Users don't need Node.js on their server and packaging stays simple. The trade-off is no SSR or server actions; every page is a client component that calls the API. That's acceptable for a LAN dashboard.
- **Typed contract.** FastAPI generates OpenAPI. `openapi-typescript` and `openapi-fetch` generate the TS client in `packages/api-client`, so the frontend never hand-writes request types.
- **Realtime.** Server-Sent Events carry stats, logs, job progress and the AI chat stream. WebSockets are used only where input is two-way, which means the terminal.
- **Long operations are jobs.** Image pulls, package installs and rclone syncs return a `job_id` right away and stream progress over SSE. A small in-memory job runner (`athena/jobs.py`, keeping the last 100 finished jobs) is enough; no Celery or Redis. Jobs don't survive a restart: the durable records are the audit log and, for automation, `automation_job_runs`.
- **Talk to container engines through a Docker-compatible CLI** (`docker --host <endpoint>`, `podman --url <endpoint>`, or `wsl.exe -e docker`), using `python-on-whales` for structured reads and direct subprocesses for streamed operations (logs, compose up, pulls). Revised in M2 from "Docker API via the docker SDK": Docker inside WSL2 has no socket reachable from Windows, and the CLI is the one path that covers it, Docker Engine, Colima, Podman and Rancher Desktop alike. Detection still pings the Docker API socket directly (no CLI needed for that).

---

## 3. Platform layer and capability manifest

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

### Container runtime per OS

| OS | Default | Alternatives detected | Notes |
|---|---|---|---|
| Linux | Docker Engine (Moby, `docker-ce`) | Podman (rootful socket) | Native socket `/var/run/docker.sock`. |
| macOS | **Colima** (`brew install colima docker docker-compose`) | Podman machine | Athena can run `colima start` and `colima status`. The socket is `~/.colima/default/docker.sock`. Volume paths must be under `$HOME` or a mount configured in Colima. |
| Windows | **Docker Engine inside WSL2** | Podman machine (WSL2 backend), Rancher Desktop (dockerd mode) | Docker Desktop is excluded because it isn't open source. Athena connects over a TCP/npipe endpoint or a relayed socket exposed by the WSL distro. Windows paths are translated to `/mnt/<drive>/…` for bind mounts. |

**Windows (decided: detect only).** Athena does not install a runtime. It detects Docker Engine in a WSL2 distro, Podman machine, or Rancher Desktop (dockerd mode), in that order of preference, and connects to the first one that responds. When none is found, the `containers` capability is `missing`, and the setup wizard shows step-by-step instructions for installing Docker Engine in WSL2 or Podman. Provisioning a WSL distro automatically is a possible post-MVP feature. Windows containers are out of scope; only Linux containers are supported.

### Package managers per OS

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

### Privilege model

| OS | Athena runs as | Privileged ops |
|---|---|---|
| Linux | `root` systemd service, which is what CasaOS does too | Direct |
| macOS | The logged-in user, as a launchd agent | Not needed: brew refuses to run as root and Colima is per-user |
| Windows | The logged-in user, through a Scheduled Task at logon | winget/scoop are per-user. Machine-wide installs raise UAC on the desktop, and the UI warns about that |

The manifest reports `needs_privilege` when an operation can't be done as the current user.

---

## 4. Feature design

### 4.1 Apps and the app store

**App definition format.** A standard `compose.yaml` plus an `x-athena` extension, so any compose file works as a custom app with zero metadata. The full format (every field, rules, checks) is in `catalog/README.md`; in short:

```yaml
x-athena:
  title: Jellyfin
  description: Stream your movies, shows and music to any device.
  category: media
  icon: https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/svg/jellyfin.svg
  web_port: WEB_PORT          # env key (or a number) that "Open" links to
  env:                        # the install form; answers go to .env
    - key: WEB_PORT
      label: Web port
      type: port              # text, password, port, path, number, boolean, select (needs options)
      default: "8096"
    - key: TZ
      label: Timezone
      default: "@timezone"    # tokens: @timezone @uid @gid @app_data[/sub]
      advanced: true
services:
  jellyfin:
    image: jellyfin/jellyfin:10.10
    ports: ["${WEB_PORT}:8096"]
    volumes:
      - ${ATHENA_APP_DATA}/config:/config
```

- **Catalogs** are Git repos or HTTP URLs that contain `apps/<id>/compose.yaml`. Athena ships one built-in catalog, `catalog/` in this repo, with about 200 apps, and users can add more. An app folder can also hold variants (`compose.<slug>.yaml`, e.g. FreshRSS with PostgreSQL), offered as a picker on the install page.
- **CasaOS compatibility.** An importer maps CasaOS `x-casaos` metadata to `x-athena`, so a CasaOS-style store archive can be added as a catalog. The CasaOS AppStore (Apache-2.0) apps are now part of the built-in catalog (#120), so the one-click CasaOS catalog was removed (#121). Umbrel's store is **not** included because its license is non-commercial.
- **Install flow:** render the form from `env`, resolve the default tokens and generated secrets, write `.env` (0600) next to `<data>/apps/<id>/compose.yaml`, then run `compose up -d` as a job and record the app in SQLite.
- **Custom apps:**
  - *Paste or upload compose* → validated, then edited in a CodeMirror editor before deploy.
  - *Import `docker run …`* → a Python parser (shlex plus a flag map, the same idea as `composerize`) turns it into compose that the user reviews.
- **Path portability.** `${ATHENA_APP_DATA}` is the app's own folder under the data dir, which resolves per OS: `/var/lib/athena` on Linux, `~/Library/Application Support/Athena` on macOS (inside Colima's shared mount) and `%LOCALAPPDATA%\Athena` on Windows.

### 4.2 Terminal

- Backend: a WebSocket at `/api/terminal/ws?target=host|container:<id>`. On POSIX it uses the stdlib pty, and on Windows it uses `pywinpty` (ConPTY) running PowerShell 7, or Windows PowerShell when 7 isn't installed. A container shell runs `docker exec -it` through the same CLI as the rest of Athena, so Docker in WSL works too.
- Frontend: `xterm.js` with the fit and web-links addons, themed from the active CSS variables.
- Admin only, and it can be turned off globally in settings.

**As built (M5):**
- `athena/terminal/pty.py` (`PtySession`) gives one async interface over both OSes.
  - A reader thread feeds a bounded queue, so a slow browser stalls the program instead of filling memory.
  - Writes run in a thread.
  - Closing hangs up the whole session (SIGHUP to the process group, then SIGKILL).
  - POSIX doesn't use `pty.fork()` or ptyprocess. Forking the multi-threaded server and running Python in the child can deadlock it. `subprocess.Popen(start_new_session=True)` forks and execs in C, and a two-line shim (`TIOCSCTTY`, then `execvp`) makes the pty the controlling terminal, so Ctrl+C and job control work. A missing program exits 127.
- `athena/terminal/shells.py` chooses what to run:
  - On the host, the service user's login shell (`-l`); `/bin/sh` if it's missing or `nologin`.
  - In a container, bash if the image has it, otherwise sh, with `TERM=xterm-256color`.
- The protocol:
  - After connecting, the browser sends `{"type":"auth","csrf","cols","rows"}` with the session's CSRF token. Browsers can't set headers on a WebSocket, and a cross-site page can't read the token.
  - The server sends `{"type":"ready"}`, then output as binary frames.
  - The browser sends `{"type":"input"}` and `{"type":"resize"}` text frames.
  - When the program exits, the server sends `{"type":"exit","code"}` and closes with 1000.
- Close codes, shown to the user with their reason:
  - 4401: no session, or signed out.
  - 4403: bad CSRF token, or not an admin.
  - 4404: bad target.
  - 4409: turned off, unsupported, or the runtime isn't ready.
  - 4429: more than 10 open terminals.
  - 4500: the program couldn't start.
- Session checks while a terminal is open:
  - Signing out, or the session expiring, closes it within 60 s.
  - Turning the terminal off (`PUT /api/settings/system`) closes every open terminal at once.
- Audit: `terminal.open` and `terminal.close` (exit code or reason, duration), with target `host` or `container:<ref>`; `settings.terminal` on/off.
- UI:
  - `/terminal` (nav item gated by `terminal.host`) with a status badge and New session.
  - A **Shell** action on running containers, both on the Containers page and in app detail, opening a sheet.
  - Settings → System holds the switch.
  - `<Terminal>` in `packages/ui/.../athena/terminal.tsx` themes xterm.js from the CSS variables (converted to rgba through a canvas so oklch works) and re-themes when `<html>` attributes change. The ANSI hues are two fixed palettes, chosen by background lightness. Links in output (OSC 8 and plain URLs) open only if they're http(s), in a new tab with no opener; program output is untrusted, and xterm's default OSC 8 handler would also follow `javascript:`.

### 4.3 Files and sharing

- **File manager** API rooted at configured "locations", never the entire filesystem by default. Endpoints: list, stat, read, upload (chunked), download, mkdir, move, copy, delete (to trash where the OS supports it via `send2trash`).
  - **Locations (M6).** `file_locations` table (migration 0008). On first start Athena adds Home (`/home` when Linux runs it as root, otherwise the user's home) and App data (`<data-dir>/apps`); removing them sticks (a `files_defaults_seeded` marker in `system_settings`). Only admins add, edit or remove locations, which must be existing absolute folders. Removing a location never touches its files.
  - **Paths (M6).** The API names a file by location id plus a `/`-separated relative path. `athena/files/paths.py` refuses `..`, empty and `.` segments, and anything whose real path leaves the location's real path, so a symlink pointing outside can be listed but not followed. Acting on an entry itself (delete, rename, move) resolves only its parent, so deleting a link removes the link, never its target. The entry's path is then normalized and must keep exactly the requested name directly inside that parent: Windows drops trailing dots and spaces, so `...` would otherwise name the parent folder (a permanent delete removed a location's folder in CI before this check). New names must be valid on every OS (no `<>:"/\|?*`, control characters, Windows device names or trailing dots and spaces); existing names are read as they are.
  - **Operations (M6).** `/api/files`: `locations` (CRUD), `list` (folders first, `hidden` flag, capped at 10,000 entries), `text` (read/write UTF-8 up to 2 MB, with a version check against concurrent edits), `download` (files; folders as a streamed, uncompressed zip that skips links leaving the location), `folder`, `rename`, `delete` (trash by default, `permanent` optional, per-item results), `transfer` (copy or move, also across locations, as a job; on a name clash: keep both as "name (1)", skip, or replace files but never folders; links copied as links), and `upload` (raw 8 MB pieces with `offset`/`total` into `.athena-upload-<id>` in the target folder, renamed into place after the last piece; hidden from listings; stale pieces cleared after a day; free space checked first). Deletes, moves and location changes are audited.
  - **Downloads never run as the app.** Everything is `Content-Disposition: attachment` with `nosniff` and a sandboxing CSP, except images, audio and video with `inline=true` for the preview. HTML, SVG and PDF are never inline.
  - **Web (M6).** `/files/?loc=&path=`: location picker, breadcrumbs, table with multi-select, row menu, drag and drop upload with a progress panel (Replace on a name clash), New folder, rename, copy/move with a folder picker, delete (trash or permanent), hidden files toggle, and a preview sheet (images, audio, video; text opens in the CodeMirror editor with Save). Admins manage locations from a dialog.
- **Share links (M6):** a token, an optional password, expiry and read-only or upload-only modes. Served by `/s/<token>`.
  - `shares` table (migration 0009, cascades with its location). The token (24 random bytes, URL-safe) is the link and is stored as is, so the admin can copy it again later. Passwords are argon2 hashes.
  - `/api/shares` (admin, signed in): list (all, or by location and path), create, `PUT` (mode, expiry, new or removed password), delete. All audited as `share.create|edit|remove`.
  - `/api/public/shares/{token}` is public (the other public routes are listed in §7): info, `unlock`, `list`, `download` and, for upload links, `upload` (the same 8 MB pieces as the file manager). Every path resolves against the **shared item itself**, not its location, so a symlink inside a shared folder pointing elsewhere in the location is refused too. Expired links are 410, removed ones 404; a wrong password is 403 (not 401, which the UI treats as "signed out") and is throttled to 10 per client and link per 5 minutes.
  - Unlocking sets an HttpOnly, SameSite=Strict cookie scoped to `/api/public/shares/<token>`, valid 7 days, whose value is HMAC-SHA256(key = the password hash, token). No server state; changing or removing the password invalidates it.
  - Read links show the item: a file (with media preview) or a folder (browse, preview media, download files or a streamed zip). Downloads count in `downloads` (previews don't). Upload links are drop boxes: visitors can't list or download, a taken name gets " (1)" and nothing is ever replaced; each upload is counted and audited as `share.upload` by `link #<id>` with the client address.
  - The page is the static `/s/` export, served by FastAPI for any `/s/<token>` with `Referrer-Policy: no-referrer` (the page also sets the referrer meta). It reads the token from the address.
  - Web: Share… in a file or folder's menu (existing links, plus mode, optional password, expiry Never/1/7/30 days; the new link is copied), `/files/shares/` lists every link, and `/s/` is the visitor's page.
- **Network share (M6):** WebDAV via `wsgidav`, mounted inside the server at `/dav/` (through `a2wsgi`, as an ASGI middleware in front of the app). It's one implementation that works on all three OSes and is mountable from Finder, Windows Explorer and Linux file managers. SMB and NFS are post-MVP and only offered where the OS has them, through the capability manifest: the `shares.smb` capability detects the host's Samba server (Linux) and `/api/shares/smb` creates, lists and removes SMB shares for a file location (macOS and Windows report it as unsupported until their share creation is wired).
  - The root lists the file manager's locations as folders; nothing else is reachable or can be created there. Paths go through `athena.files.paths` (no `..`, no names that normalizing changes, real path inside the location), and symlinks are neither listed nor followed. A location's own folder can't be deleted, moved or replaced; this is checked in `handle_delete`/`handle_copy`/`handle_move`, because when a collection's `delete()` refuses, wsgidav falls back to deleting everything inside it item by item (found in testing: `DELETE /dav/One/` emptied the location).
  - Off by default (`webdav` row in `system_settings`); `/dav` is 404 while it's off. HTTP Basic with the admin's username and a **separate, generated WebDAV password** (argon2, shown once, `POST /api/webdav/password`), so the account password, which also opens the terminal, isn't sent on every request. Successful checks are cached for 5 minutes (keyed by the password hash, so a new password applies at once); failures are throttled per client. Settings → System says when it's plain HTTP.
  - Every `/dav` response carries `Content-Security-Policy: default-src 'none'; sandbox` and `nosniff`, because the files are served from Athena's origin. wsgidav's HTML directory browser is off. Locks and dead properties are kept in memory (Finder needs Class 2 to mount read-write).
  - WebDAV changes aren't audited per file; turning it on or off and new passwords are (`settings.webdav`).

### 4.4 Cloud storage

- Run `rclone rcd` as a managed child process, bound to localhost with random credentials, and drive it over its HTTP API.
- MVP: add, edit and remove remotes (OAuth handled by rclone's config flow), browse a remote in the same file manager UI, and copy/sync jobs between local and remote with progress over SSE.
  - **Sidecar (M6).** `athena/cloud/rclone.py` starts `rclone rcd --rc-serve` on 127.0.0.1 with a free port, user `athena` and a random password, on the first cloud request (hosts that never use it don't run rclone). It uses Athena's own config `<data-dir>/rclone/rclone.conf` (rclone writes it 0600; the folder is 0700), never the host user's, and drops `RCLONE_CONFIG*`/`RCLONE_RC_*` from its environment. A dead process is restarted on the next call; the server stops it on shutdown. Calls are stdlib HTTP in a worker thread. Everything is gated by the `cloud.rclone` capability (503 with its detail otherwise).
  - **Remotes (M6).** `/api/cloud/providers` is rclone's `config/providers`, minus backends that reach the host's disks (`local`, `alias`, `memory`, `cache`, which the API also refuses to create) and options hidden from the configurator. `/api/cloud/remotes` lists, creates, edits and deletes remotes (admins only, audited as `cloud.remote.create|edit|remove`). The detail never returns passwords or anything rclone marks sensitive (that includes WebDAV users and S3 keys); a secret sent empty when editing keeps its value. Creation uses rclone's non-interactive flow: each follow-up question goes to the UI and its answer to `POST /api/cloud/remotes/{name}/answer` with rclone's `state`. Athena answers "use a browser on this machine?" with no, so OAuth always goes through `rclone authorize "<backend>"` on the person's computer and a pasted token (the browser flow would redirect to the server's own 127.0.0.1). A refused answer comes back as `error` with no new question, and the UI asks again. Cancelling a new remote halfway deletes it.
  - **Browsing (M6).** `/api/cloud/files/*` mirrors the file manager for a remote (`?remote=` instead of `?location=`, same `Listing`/`FileEntry` shapes): list, download (files only, streamed from `--rc-serve`, same attachment and CSP rules), folder, rename, delete (permanent; remotes have no trash Athena can use), and chunked uploads that are staged in `<data-dir>/rclone/uploads/<id>` and moved to the remote after the last piece. Remote paths refuse `..`, `.`, empty parts and backslashes, because rclone would let `name:..` leave an alias's folder. Text editing, share links and WebDAV stay local-only.
  - **Transfers (M6).** `POST /api/cloud/transfer` copies or moves items between a location and a remote, or between remotes; location to location stays with `/api/files/transfer`. A file that's already there is replaced when it differs (rclone's rules, no "keep both"). `POST /api/cloud/sync/preview` lists both folders recursively and compares them (not `operations/check`, whose file lists rclone 1.60 leaves empty), returning which files sync would delete (exact) and how many it would copy (new files and size changes); `POST /api/cloud/sync` then mirrors. Each step is an async rclone call in one stats group per Athena job; the job polls `job/status` and `core/stats`, reports progress, and can be cancelled (`job/stop`). Audited as `cloud.copy|move|sync|delete`.
  - **Web (M6).** `/cloud` lists remotes (Browse, Edit, Remove), Add remote (searchable storage picker, a form built from the backend's options with an Advanced switch, then rclone's questions one at a time), and Sync folders (two folder pickers, Check changes, then Sync, which says how many files it deletes). Remotes appear under "Cloud" in Files' location picker and in Copy/Move's destination picker. Without rclone the page shows per-OS install commands.
- **Mounts come later** because they need FUSE: libfuse on Linux and WinFsp (GPL with FLOSS exception) on Windows. On macOS the open-source path is `rclone nfsmount`, since macFUSE is not open source.

### 4.5 AI assistant

- `pydantic-ai` (slim, with the OpenAI, Anthropic, Google, Groq, Mistral, Bedrock and Cohere clients) plus `pydantic-ai-harness` (from part C), which pins the exact same pydantic-ai version, so the two are upgraded together. Harness capabilities are added in stages (see Parts below). The model is picked **per run**, so one agent serves every provider and a conversation can switch model halfway; the stored history doesn't depend on the provider.
- **Providers**, OpenCode/Hermes style: set up once, then pick any model from any of them. Each kind is a form with an API key and, where it applies, a base URL:
  - Native kinds (`NATIVE_KINDS` in `assistant/kinds.py`, 12): Anthropic, OpenAI, Google Gemini, OpenRouter, Groq, Mistral, DeepSeek, xAI, Azure OpenAI, Amazon Bedrock and Cohere in the cloud, and Ollama locally.
  - Every other OpenAI-compatible provider listed on models.dev (`assistant/models_dev.py`), minus routers, gateways and token plans (`SKIP_PATTERNS`). They're fetched from `https://models.dev/api.json` at startup and cached for 24 h in the `models_dev_cache` table; `GET /api/assistant/kinds` returns native plus cached kinds, and `POST /api/assistant/kinds/refresh` forces a refetch (automatic refreshes run at most every 5 minutes). The old generic "OpenAI-compatible" kind was replaced by these.
  - A kind can be added more than once (two Ollama hosts, a work key and a home key). Providers belong to the whole server and only the admin manages them; per-user keys can come later. API keys only: subscription sign-ins (Claude Pro/Max, GitHub Copilot) are left for later (pydantic-ai has a `github-copilot` provider).
  - xAI, DeepSeek, OpenRouter and Ollama go through the OpenAI client (xAI's own SDK pulls in gRPC). Azure takes an endpoint and API version; Bedrock takes an access key id, secret key and region.
- **Keys at rest:** encrypted with Fernet (`cryptography`) using a key file `<data-dir>/secret.key` (0600, created on first use). That protects keys in database copies and backups, not against someone who can read the data folder. The API never returns a key; editing works like cloud remote passwords (an empty field keeps the stored value, shown as "Unchanged").
- **Model list:** native kinds list live from the provider (Anthropic's models API, OpenAI-style `/v1/models`, Gemini's model list, Ollama's `/api/tags` + `/api/show`, Cohere's, Bedrock's foundation models); models.dev kinds use the cached models.dev list (tool support and context window included), falling back to `/v1/models` at the base URL. Lists are cached for 10 minutes, and a model id can always be typed by hand (Azure deployments are only typed).
- **Tool support:** the assistant only works with models that can call tools. Where the provider reports it (Ollama's `capabilities`, OpenRouter's `supported_parameters`, Mistral's `function_calling`), models without it are marked "can't use tools" and can't be picked; elsewhere it's unknown and allowed.
- **Ollama detection:** an `ai.ollama` capability on every OS, found like the container engine: `GET /api/version` on `$OLLAMA_HOST` or `http://127.0.0.1:11434`. `stopped` when the `ollama` binary exists but doesn't answer. When it's ready, an empty Settings → AI offers "Use Ollama on this server" (one click adds it); otherwise "Add a cloud provider". Neither is suggested by default (closes the old §12 question).
- **Setup wizard step (part C):** after the admin account, `/setup` shows an optional "Set up the AI assistant" step (`AiSetupStep`) with the same choices as the empty Settings → AI: "Use Ollama on this server" when `ai.ollama` is ready, any other provider, or "Skip for now". A saved provider is tested at once (connected, or the error with "Edit provider"), then a default model can be picked from that provider's models. No server changes: it uses the providers and `/api/settings/ai` endpoints.
- **Settings → AI** (admin only): providers (add, edit, test connection, remove), the default model, an optional small model for chat titles, an optional advisor model (part D), the assistant-shell switch (off by default, part C) and a spend limit per conversation in USD (`UsageLimits.cost_limit`, enforced for models with known prices). Stored in the `system_settings` row.
- **Tools are Athena's service layer, not raw shell by default.** They're registered from the capability manifest (no container tools without a ready `containers` capability, no package tools without a ready `packages.*` one).
  - Read-only (part A, plus store and package lookups in part B): `get_capabilities`, `get_system_stats`, `list_apps`, `app_logs`, `search_store`, `get_store_app`, `list_file_locations`, `list_files`, `read_text_file`, `list_package_managers`, `search_packages`, `list_upgradable_packages`.
  - Actions (part B, `assistant/actions.py`): `install_store_app`, `create_app`, `change_app` (start, stop, restart, update), `remove_app`, `install_package`, `uninstall_package`, `upgrade_packages`, `write_text_file` (existing files only), `create_folder`, `rename_file`, `delete_files` (trash unless `permanent`), `copy_or_move_files`. Each calls the same route helper as the UI, so validation, one-job-per-resource and the area's own audit row are unchanged. Actions that start a job wait for it (up to 15 min), send a `job` event so the card can open the live log, and return the job's status and last log lines; a failed job is a failed tool call.
- **Safety:**
  - Read-only tools run freely.
  - Mutating tools (part B) are *deferred tools* (`requires_approval=True`) that need human approval. The run ends with `DeferredToolRequests`, which the saved `Conversation` keeps; the stream sends an `approval` event with each call's id, arguments, a one-line summary ("Create the folder photos in Share", with location ids resolved to names) and a destructive flag. The UI shows an Approve/Deny card (the AI Elements Confirmation pattern) with the summary and the exact arguments. `POST /api/assistant/conversations/{id}/approvals` takes an answer for every waiting call (422 otherwise, 409 when nothing waits), audits each as `assistant.approve` / `assistant.deny`, and resumes the run with `DeferredToolResults` on the same SSE stream. A denial tells the model "The admin denied this" (plus an optional reason).
  - A new message while actions wait denies them all (the model is told the admin sent a message instead), since a run can't start with calls unanswered.
  - **Shell (part C, `assistant/workspace.py`, `assistant/shell.py`):** off by default (Settings → AI, audited as `settings.assistant_shell`). The `assistant.shell` capability says where it runs: `posix` (Linux, macOS: the harness `Shell` in a `LocalWorkspace` at the service user's home), `wsl` (Windows with a WSL distro: the same `Shell` in `WSLWorkspace`, our backend that runs each command through `wsl.exe -e /bin/sh -c`, because the harness's local workspace is POSIX-only) or `powershell` (Windows without WSL: Athena's own `actions.run_command` with PowerShell). Either way the model calls `run_command(command, timeout_seconds)` (the harness also has `start_command`, `check_command` and `stop_command` for background jobs). Before any card, `ShellGuard` checks that every program in the line (the first word, and the first word after each `|`, `&&`, `||`, `;`, `&` or new line) is on the allowlist (`shell_commands`, a default per OS of mostly read-only programs); `$( )`, backticks, `<( )` and subshells are refused. A refused command fails back to the model and never reaches the admin. Allowed ones are asked about by the harness's `Permissions` in read-only mode (every command), through the same approval cards; the allowlist is checked again after approval, and each run is audited as `assistant.shell` with its exit code. Timeouts kill the command's whole process group (in WSL: `setsid`, or job control checked with `ps`, then a second `wsl.exe` call). The allowlist guards against mistakes, not a hostile model: an allowed program can start others.
  - Spend limit and loop detection are on; prompt caching (`Caching()`) is on for providers that support it.
  - **Robustness (part D stage 1, `assistant/robustness.py`):** every run gets three harness capabilities, always on with no settings. `RepairToolArguments` (with `json-repair`) fixes malformed tool-call JSON from small local models before validation. `DetectLoops` nudges the model (a `<system>` note on the next request) when it repeats a call or result; the per-turn request and tool-call limits stay the hard stop. `ToolOutputLimits` saves any tool result over 24,000 characters to `<data-dir>/assistant/tool-output` (`LocalFileStore`, pruned after 7 days) and gives the model a preview and a handle it reads back with `read_tool_result`, falling back to truncation. Athena's own tools cap their output at 20,000; the shell keeps up to 400,000 characters (`shell.MAX_OUTPUT`, was 20,000 and cut from the start), so a long command output is saved whole and the model sees a preview.
  - **Compaction (part D stage 1, `assistant/compaction.py`, `assistant/context.py`):** before each model request, once the history passes 75% of the model's context window, the harness blanks old tool results (the newest 4 stay), then, if still over, has the chat's own model summarize older messages (keeping the newest 20% of the window), stopping once under 50%. When summarizing fails (an API error or an empty summary) the oldest messages are dropped instead (`FallbackCompaction` over `TieredCompaction`, then `SlidingWindowCompaction`). The window is looked up per turn: the provider's optional "Context window" field (Ollama, OpenAI-compatible, Azure), then what the provider reports (Ollama's `/api/ps` for a loaded model; `context_length`, `context_window`, `max_context_length` or `max_model_len` in OpenRouter, Groq, Mistral and vLLM model lists, also returned as `ModelInfo.context_window`), then pydantic-ai's profile (genai-prices), then a guess: 4,096 for an unloaded Ollama model (its default; its OpenAI-style API ignores `num_ctx`), 8,192 for other local servers, 128,000 in the cloud. Compaction rewrites the stored `history` (the model's view), so `ai_conversations.transcript` keeps every message as the admin saw it once a chat has been compacted (null until then); the chat page reads the transcript.
  - **Untrusted tool results (part D stage 1, `assistant/safety.py`):** always on, no settings. `PromptInjectionDefender` (StackOne `defender`, pattern detection only; the ML tier would add ONNX Runtime) classifies every tool result and withholds high-risk ones: the model gets a notice to tell the admin, and each detection writes an `assistant.injection` audit row. It reads bare strings and string fields with known names (`content`, `name`, `description`, `notes`, …) but not lists of strings, so `app_logs` returns `[{container, content}]` with each container's log as one text. A `ToolGuardrail` replaces API keys, tokens and private keys in results with `[redacted:<kind>]` (the harness `redact_secrets`, walked through Athena's dict and list results) before the model, often a cloud provider, sees them; the UI shows the redacted result too. `RedactionGuard` fails any call whose arguments contain `[redacted:` before the approval card, so editing a file the model read can't overwrite a real key with the placeholder; its message tells the model not to retry without those lines either (that deletes the key: a browser check saw qwen2.5 try it), so the edit goes back to the admin. Personal-data redaction is off (emails and paths in logs are what an admin asks about), and so are input and output guardrails (the admin's own prompt is trusted, and output is streamed before an output guard could act). `artifact_scanning` only scans `Memory` and `Skills`, so it arrived with them in stage 2.
  - **Memory and skills (part D stage 2, `assistant/knowledge.py`):** the harness `Memory` keeps a notebook across chats in `<data-dir>/assistant/memory.db` (`SqliteMemoryStore`: safe with two chats writing at once, unlike `FileStore`'s one writer per folder). Each admin has their own notes (namespace `user-<id>`, never a tool argument). The model gets `write_memory`, `read_memory`, `search_memory` and `delete_memory`, and a short excerpt of `MEMORY.md` is added to history with the turn's first request (a user-prompt part tagged with the harness's memory origin, which the chat UI hides). "Remember across chats" in Settings → AI (`memory_enabled`, on by default, audited as `settings.assistant_memory`) turns it off without deleting notes. `Skills` loads `<data-dir>/assistant/skills/<name>/SKILL.md` (the folder is created on the first turn) through `SkillsFolder`, our read-only backend that shows the folder as `/skills` (the harness `LocalWorkspaceBackend` refuses to start on Windows): the model sees names and descriptions and loads a body with `load_capability`. Skills are added by hand in this PR; a page to list and upload them can come later. Both get `AuditingScanner` (the harness `ArtifactScanner`, which reports to us): a flagged memory write is refused, a flagged memory file is withheld, a flagged skill is left out, and each new finding writes one `assistant.injection` audit row (repeats in the same process are skipped, since the injected `MEMORY.md` and every skill are scanned on every turn).
  - **Planning and questions (part D stage 2, `assistant/plans.py`, `assistant/questions.py`):** always on, no settings. `Planning` gives the model only `write_plan` (it restates the whole plan to add a step or change a status, so it never tracks or guesses step ids, and the tool schema costs about half of the six-tool set). Each chat has its own plan in `<data-dir>/assistant/plans.db` (`SqlitePlanStore`, session `conv-<id>`), kept between turns and after compaction (the harness re-adds the plan when `write_plan`'s results are gone from the model's view) and deleted with the chat. The stream sends a `plan` event after each `write_plan`, the chat detail returns `plan`, and the UI shows it as a checklist above the prompt bar (`PlanChecklist`; open while steps are left), with no `write_plan` rows in the trace. `AskUser(answerer=None)` gives `ask_user_question` (1–10 multiple-choice questions, 2–6 options each, `multi_select` allowed): the run pauses with the call in `DeferredToolRequests.calls` (kind `question`), the stream sends `question` with the ids, and the UI shows a card per call (radio or checkboxes, "Or type your own answer" up to 500 characters, Skip). `POST .../approvals` answers everything a paused chat waits on in one body, `decisions` for actions and `answers` for questions; answers are checked against the questions with the harness's `ask_user_result` (422 when a label or header doesn't fit). A new message declines waiting questions as it denies waiting actions. The card says the question comes from the assistant and warns against answering with a password or key, since the model writes the questions. Answers aren't audited: they change nothing on the host.
  - **Delegation and background work (part D stage 2, `assistant/delegation.py`):** always on, no settings. `SubAgents` gives the model `delegate_task` with one helper, the `investigator`: a fresh run on the chat's own model, built per turn with only the read-only tools this host supports (`tools.read_only_tools`), plus the robustness and safety capabilities, since its tool results are just as untrusted. It never sees the chat and can't change anything, ask the admin, plan, remember or delegate again: a child that needed an approval card or a question would just stop, because the parent can't approve or resume it. Not `include_self`, because Athena's capabilities are passed per run and a `self` delegate would come up without the injection defender and redaction. Limits per delegation: 10 requests, 20 tool calls, 5 minutes; 3 delegations per turn; crashes are contained as a retry. Its usage is added to the chat's, so the spend limit counts it. `BackgroundTools` lets the model set `run_in_background` on `delegate_task` only (`SetToolMetadata` marks it `optional`). Actions don't get it, because a run that pauses for an approval or a question cancels its background tasks, which for an install would lose the result while the job kept going. `BackgroundTools` sits right after `RepairToolArguments` and before the safety capabilities, so the guards screen the real result, not the "started" notice. The stream skips that notice (the row stays running), `BackgroundResults` sends the real result as `tool-result` when it reaches the model, and `ui_messages` puts it on the call's row instead of showing a user bubble; a background call that never finished shows as stopped. The trace titles a delegation by its task. Nested delegate tool calls aren't shown yet.
  - **Advisor (part D stage 2, `assistant/delegation.py`):** off until Settings → AI names an "Advisor model" (`advisor_model`, audited as `settings.assistant_advisor` with `provider/model` or `off`; removing its provider clears it, and an unavailable one just leaves the tool out). The harness `Advisor` then gives the chat's model `advisor(prompt)`: a separate run on that model with only the question (`forward_history=False`), no tools and no deps, at most once per model request (`max_uses=1`; a second call is told the limit is reached). Always `mode="local"`, never a provider's native advisor tool, so it behaves the same on every provider and its answer goes through the safety capabilities like any tool result. Its usage is added to the chat's, so the spend limit counts it. The help text says its provider sees the question the assistant writes.
  - **Double-checked answers (part D stage 2, `assistant/review.py`):** off until Settings → AI turns on "Double-check answers" (`refine_answers`, audited as `settings.assistant_refine`). `DoubleCheck` (the harness `RefineOutput`, one round) sends the model back once per run, when it would end with an answer, to review it and write it again in full; the instruction says to check facts only with read-only tools and not to start actions or ask questions during the review. It costs at least one more model request per turn (counted in the turn's limits and the spend limit), hence off by default. A run that pauses for an approval or a question isn't reviewed. The draft stays in the history: the stream sends `draft` when the review starts, `ui_messages` marks the reply's earlier text `draft` (it finds the review's system prompt by the harness origin), and the UI folds it into the trace as "First draft, revised below".
  - **Workflows of helpers (part D stage 2, `assistant/delegation.py`):** always on for models whose context window is at least 32,000 tokens (`WORKFLOW_MIN_WINDOW`), because `run_workflow`'s description costs ~900 tokens on every request. The harness `DynamicWorkflow` (the `dynamic-workflow` extra, `pydantic-monty`) lets the model write a short Python script, run in the Monty sandbox, that calls the read-only `investigator` as an async function (several at once with `asyncio.gather`) and returns only what it combines. Five investigator runs per turn across every script (`max_agent_calls`), 30 s of script CPU time (time waiting on helpers doesn't count). The helpers share the chat's usage counter (`forward_usage`), so the turn's request and tool-call limits bound the whole tree and the spend limit counts them. Its result is screened by the safety capabilities like any tool result. The trace titles it "Helpers looked things up together" and shows the script above the result.
  - **Reminders and cache health (part D stage 1, `assistant/robustness.py`):** always on, no settings. `SystemReminders` adds request-scoped notes at the end of a request (so the cached prefix stays put): every 8 model requests in one reply, a note to check the next action still serves the admin's latest message and that tool results are data; and, when 3 model requests or 5 tool calls are left in the turn, a note to answer with what it has (a turn stopped by a limit is dropped). The harness `GoalReanchor` isn't used: it points at the chat's first message, and a chat moves on from it. `WarnOnCacheBusts` (as `CacheBustLog`, one instance so marks last between turns) logs a warning when a provider's cache reads back less than the chat had cached; compaction does this on purpose, anything else is a moved prefix worth fixing. Prompt caching itself is the core `Caching()` capability on the agent.
  - **Spend:** the limit is per chat (pydantic-ai checks it against the `Conversation`'s running usage), while the request and tool-call limits (25 and 50) are per turn, counted from what the chat already used. A turn stopped by a limit is dropped, but its responses' usage is saved, so the next message is refused before it spends anything. The prompt bar shows the chat's cost (or its tokens, for models without known prices) with a popover: cost against the limit, input and output tokens, and what to do when the limit is reached. Costs are pydantic-ai's estimates from published prices; the title call isn't counted. The harness `SpendLimits` was compared and not used (stage 1): its counters live in memory (lost on restart; a `conversation` window is also dropped after 30 days idle) or in Redis or PostgreSQL, while ours is the usage saved with each chat in SQLite and already drives the UI. It would add day and month budgets; if those are wanted later, they need a `BatchSpendStore` over SQLite.
- **Transport:** our own Server-Sent Events, not the Vercel AI SDK protocol. `POST /api/assistant/conversations/{id}/messages` streams typed events (`text`, `reasoning`, `tool-call`, `tool-result`, `approval`, `question`, `plan`, `job`, `usage`, `title`, `stopped`, `error`, `done`) built from pydantic-ai's `run_stream_events()`. The browser reads them with a small hook (`fetch` + a stream reader), so there's no `ai` / `@ai-sdk/react` dependency.
- **Chat UI:** shadcn's own chat components (`message`, `bubble`, `message-scroller`, `marker`, `input-group`, …) and the AI Elements patterns from ui.shadcn.com/docs/ai-elements (Chat, Prompt Input, Model Selector, Tool, Confirmation), which are copied in and need no package. `/assistant` page in part A; a side sheet from any page in part C (`AssistantSheet`, the header's Assistant button for admins, hidden on `/assistant`): the open chat is kept in the layout, so it survives closing the sheet and moving between pages, and a reply keeps running on the server while the sheet is closed. Reopened mid-reply, the chat says it's still working until the saved turn arrives (the server saves a turn only when it ends). The model picker in the prompt box remembers its choice per conversation.
- **Titles:** a chat's first message names it. The first line of the message, cut to 60 characters, is the title at once (the `title` event, before `done`). The title model from Settings → AI (else the chat's own model) then renames the chat in a background task after the turn ends, so the chat takes the next message meanwhile; `ConversationDetail.naming` is true until it's done (the UI polls) and a rename by the admin in between wins. It gives up after 120 s. The title call isn't counted in the chat's spend limit.
- **Local model queue:** every model on a local server (Ollama, or any provider whose base URL is loopback, a private or link-local address, `localhost` or a `.local`/`.lan` name: `providers.is_local`) is wrapped in pydantic-ai's `ConcurrencyLimitedModel` with one shared `ConcurrencyLimiter(max_running=1)` per server URL (`providers.queue_for`). Chat turns in every chat, titles, delegates, the advisor and reviews wait in that queue instead of hitting the server at once (Ollama answers one at a time and slows or times out otherwise). Cloud providers aren't queued.
- **Persistence:** `ai_conversations` (owner, title, model, created/updated, the history as pydantic-ai's `Conversation` JSON, which also carries running usage and pending deferred calls) and `ai_providers` (kind, name, base URL, options, encrypted secret).
- **Parts:**
  - A, providers and chat: tables, Settings → AI, model listing, `ai.ollama` detection, streaming chat with the read-only tools.
  - B, actions: tools that change things (install apps, deploy, packages, file operations) with approval cards and audit.
  - C, polish: the opt-in shell (done), spend shown in the UI (done), the side sheet everywhere (done), generated titles (done), the setup-wizard step (done).
  - D, the rest of pydantic-ai-harness (0.68.0), in stages. Each stage is its own PRs; every capability that needs a key, a service or a host tool gets a setting in Settings → AI (off by default, keys encrypted like provider keys) and, when it depends on the host, a capability. `permissions`, `shell` and `spend`-style limits are already in (part C and §4.5 Safety). `context`, `docs` and `runtime_authoring` are deprecated aliases of `repo_context`, `pydantic_ai_docs` and `capability_creation`.
    1. **Robustness:** `repair_tool_arguments` (small local models), `detect_loops`, `tool_output_limits` and `overflowing_tool_output`, `compaction`, `prompt_injection_defender` and `guardrails` (logs, files and web pages are untrusted input), `system_reminders`, `cache_stability` and `warn_on_cache_busts`, and the harness `spend` compared with our own spend limit (keep one). Done: `cache_stability` is now only a deprecated alias of `warn_on_cache_busts`, and we kept our own spend limit.
    2. **Agent features:** `memory` (a notebook across chats, stored in the data dir) and `skills`, both with `artifact_scanning`, `planning`, `ask_user` (a multiple-choice question card), `subagents`, `background_tools`, `advisor`, `refine_output`, `dynamic_workflow`, `step_persistence` with `conversation_search` and `media` (stores for large parts).
    3. **Extras with outside services:** web research (`exa`, `youdotcom`, `keenable`, `researcher`; API keys), a browser (`playwright`, which downloads Chromium; `browser_use`), and second-model reviews (`approval_reviewer`, `tool_call_judge`, `trajectory_judge`; one more model call per action).
    4. **Sandboxes and other workspaces** (where the shell runs): local ones first, because they give the shell real isolation without an account: `docker_sandbox` (through the `containers` capability), `bubblewrap_sandbox` (Linux), `boxlite_sandbox` and `smol_sandbox` (micro-VMs), `ssh_workspace` (another machine). Then the cloud ones, each with its account key: `modal_sandbox`, `e2b_sandbox`, `daytona_sandbox`, `sprites_sandbox`, `boxd_sandbox`, `render_sandbox`, `opensandbox_sandbox`, plus `localstack` (an emulated AWS).
    5. **Hosted integrations** (each the service's hosted MCP server, with its token or OAuth sign-in per server): `github`, `linear`, `notion`, `slack`, `google_workspace`, `day_ai`, `grain`, `ordinal`, `posthog`, `pylon`, `stackone`, `logfire_mcp`, `pixeltable`. Their actions go through the same approval cards.
    6. **Durable execution and operations:** `absurd`, `pgtask` (Postgres), `aws_lambda`, `azure_durable_task`, `render` (Render Workflows), `logfire` (managed variables), and the experimental ACP server (`experimental.acp`, so editors can talk to Athena's agent). These need outside infrastructure that a single home server usually lacks, so each one is checked first for whether it fits Athena's in-process turns.
    7. **Coding and code execution:** coding stack (`coding_stack_enabled`, POSIX-only — shell commands gated by `ShellGuard` allowlist + approval + audit, same as the assistant shell), `code_mode` (`code_mode_enabled` — read-only tools tagged `code_mode=True` batch behind a single `run_code` tool in a Monty sandbox; approval-gated tools stay as regular deferred calls needing approval), `filesystem` (beside Athena's own file tools, which keep their location rules), `repo_context`, `smart_search`, `macroscope`, `ipython_code_mode` (the model writes Python that calls tools), `capability_creation`, `pydantic_ai_docs`. These suit a server that hosts code (Forgejo, code-server apps) and need the same approval as the shell. `Coder` from pydantic-ai-harness is intentionally not used — its bundled shell is unrestricted and bypasses `ShellGuard`.

### 4.6 Dashboard

- `athena/monitor.py`: `psutil` for CPU, memory, swap, disks, network, disk I/O, load and temperatures, sampled every 2 s by a background task started in the app lifespan. A ring buffer keeps 1 h of samples (1800) for sparklines.
  - `GET /api/system/stats` returns the current stats plus the history; `GET /api/system/stats/stream` (SSE) sends a `stats` event after each sample. After a dropped stream the UI reloads the snapshot to fill the gap.
  - No capability: psutil covers all three OSes. Metrics a host can't report are `null` and hidden (temperatures exist only on Linux; disk I/O counters can be missing on Windows and in containers).
  - Memory "used" is total − available. Network totals skip loopback and container bridges (`veth*`, `docker*`, `br-*`, `vEthernet*`), which would double count.
  - Disks: physical partitions only, minus pseudo/snap/image filesystems, macOS `dontbrowse` volumes and read-only mounts other than `/`; partitions with identical total and free space (APFS volumes in one container, bind mounts) collapse to the shortest mount point; used = total − free. Refreshed every 30 s.
  - GPUs (#93): use, VRAM and temperature from `nvidia-smi`, Linux sysfs (AMD, Intel) and macOS `powermetrics` (`read_gpus`); `gpus` is empty when nothing reports.
- Cards: system stats (CPU, memory, network, disk activity, GPU when reported, each with a 5 min / 1 h sparkline), apps, storage, temperatures (when reported), server info with uptime, capabilities.
- Apps card: a CasaOS-style icon grid (#146), one tile per app with its store icon and title (`AppOut.title`/`icon`, looked up from the catalog; plain compose apps fall back to initials), a status dot, and a menu with start/stop/restart, update, open and remove. When the runtime isn't ready it shows the same Start/setup panel as the Apps page; it's hidden where containers are unsupported, like the Apps nav item.


### 4.7 Automation and the MCP server (M8)

- **Triggers** (`athena/automation/service.py`, `automation_triggers`): a cron expression (`croniter`) or an HTTP webhook fires an action, which is an app verb (start, stop, restart, update) or a package verb (install, uninstall, upgrade, refresh). A scheduler loop started in the lifespan fires due cron triggers; actions run as ordinary Athena jobs, and each execution is a row in `automation_job_runs` (the one durable job history; other jobs live in memory). `/api/automation/triggers` (CRUD, `validate-action`) and `/api/automation/jobs`, audited as `automation.trigger.*`.
- **Webhook:** `POST /api/automation/webhook/{token}` is public; the trigger's random token is the credential (n8n and other tools).
- **MCP server** (`athena/mcp/`, fastmcp, streamable HTTP at `/api/mcp`, mounted in the lifespan): tools to list apps, package managers, capabilities and host stats, run app actions, and list or create automation triggers and their runs. `MCPAuthMiddleware` accepts the session cookie or `Authorization: Bearer $ATHENA_MCP_TOKEN` (an environment variable; when unset, only sessions work); a bearer request acts as the oldest admin user (409 when there's none), and its audit rows add "via MCP token" to the detail. Tools that change something are audited (app actions through `apps.start_app_action`, shared with the route; trigger creation directly); read-only tools aren't.
- **UI:** `/automation` (gated by the built-in `automation` capability): triggers with create, enable/disable, webhook URL copy and delete, a job-run table refreshed every 5 s, and a card with the webhook and MCP addresses.

### 4.8 Remote access (tunnels)

Expose Athena outside the LAN without opening ports, through one of three providers. Planned in `TUNNEL_IMPLEMENTATION_PLAN.md` (folded in here and deleted), built in #128 with fixes in #133 and #144.

- **Capabilities** (`platform/detect.py`): `tunnel.cloudflare` (`cloudflared`), `tunnel.tailscale` (`tailscale`; reports whether it's logged in) and `tunnel.ngrok` (`ngrok`), each `ready`, `stopped` or `missing` with `start`/`setup` actions. Providers live in `athena/tunnel/` (`TunnelProvider` in `base.py`: `start`, `stop`, `status`, `get_config_schema`, `install`, `configure_service`), registered by capability id in `TUNNEL_PROVIDERS`.
- **Providers:**
  - *Cloudflare Tunnel:* a quick tunnel (`cloudflared tunnel --url`, an ephemeral `trycloudflare.com` address, no account) or a named tunnel with an API token, tunnel name and optional domain.
  - *Tailscale Funnel:* uses the host's tailnet (`tailscale funnel <port>`, `tailscale funnel off`, `tailscale funnel status`); the host must be logged in (`tailscale up`) with Funnel allowed in the admin console.
  - *ngrok:* an auth token, optional domain or subdomain (paid plans); `ngrok http <port>`, and its service files use `tunnel_port`. The UI warns about the free tier's limits.
- **Settings:** `tunnel_enabled` (off by default), `tunnel_provider`, `tunnel_config` (provider fields), `tunnel_auto_start` and `tunnel_port` (default 8420, the port every provider exposes) in the `system_settings` row. `tunnel_auto_start` is stored but Athena doesn't act on it at startup yet; `PUT service` is what makes a tunnel survive a reboot. A `tunnel_config` key ending in `token`, `secret`, `password` or `key` is encrypted with `app.state.secret_box` (stored with an `enc:` prefix) and decrypted only on start; it's never returned, and responses list the stored ones in `tunnel_secrets_set`. On save an empty value keeps the stored secret, `null` clears it, and old plaintext values are encrypted on the next save (#150).
- **API** (`/api/tunnel/*`; `PUT config`, `POST install`, `PUT service`, `POST start` and `POST stop` are admin-only, `GET status` is open to any signed-in user): `GET status` (running, public URL, capability status), `POST start` and `POST stop` (jobs), `PUT config`, `POST install` (downloads the provider's binary or runs its installer, as a job) and `PUT service` (registers the provider as a systemd unit, launchd agent or scheduled task so it survives a reboot).
- **UI:** `TunnelCard` in Settings → System: provider picker, the provider's form, status with the public URL, Start/Stop (job dialog), Install when the binary is missing, and the auto-start switch.

---

## 5. Frontend

### 5.1 Monorepo bootstrap

```bash
pnpm dlx shadcn@latest init --preset b0 --template next   # choose the monorepo option
```

This produces `apps/web` and `packages/ui`. Then:

- `apps/web/next.config.ts` → `output: "export"`, `images.unoptimized: true`
- add `packages/api-client` (generated)
- Turborepo tasks: `dev`, `build`, `lint`, `typecheck`, `gen:api`

### 5.2 App shell from the `dashboard-01` block

The sidebar, header and app layout come from the shadcn `dashboard-01` block, added to the web app:

```bash
pnpm dlx shadcn@latest add dashboard-01 -c apps/web
```

The CLI rewrites the block's Tabler icons to whatever icon library the preset uses. What happens to each file the block adds:

| Block file | What Athena does with it |
|---|---|
| `components/app-sidebar.tsx` | **Keep.** Replace the demo `data` object with nav built from the capability manifest. Missing features don't render. Put the Athena logo and name in the header |
| `components/nav-main.tsx` | **Keep.** Primary nav from `components/nav.ts`: Dashboard, Apps, Store, Packages, Automation, Files, SMB shares, Cloud, Containers, Terminal, Assistant, each gated by its capability. Swap the "Quick Create" button for "Add app" (store / custom) |
| `components/nav-secondary.tsx` | **Keep.** Settings, plus a link to help/docs |
| `components/nav-user.tsx` | **Keep.** Bind it to the logged-in user, with Account and Log out |
| `components/site-header.tsx` | **Keep.** Breadcrumb/page title, ⌘K command palette trigger, runtime status badge, assistant toggle |
| `components/nav-documents.tsx` | **Delete.** It's the block's demo document list |
| `app/dashboard/page.tsx` | **Delete.** Athena's own dashboard is `app/(app)/page.tsx` |
| `app/dashboard/data.json` | **Delete.** Demo data |
| `components/section-cards.tsx`, `chart-area-interactive.tsx`, `data-table.tsx` | **Delete.** They're demo dashboard content. Athena builds its own stats cards, charts and tables from shadcn `card`, `chart` and `table`, wired to the API |

Layout: `app/(app)/layout.tsx` holds `SidebarProvider` + `AppSidebar` (variant `inset`) + `SidebarInset` + `SiteHeader`. Every authenticated route lives under that layout. `/setup` and `/login` sit outside it.

Packages the block pulls in that Athena doesn't need, such as `@dnd-kit/*` (only the demo table's row drag uses it), are removed after the add.

### 5.3 Components: shadcn first, create only what's missing

| Need | Source |
|---|---|
| App shell, nav | `dashboard-01` block (see 5.2), plus shadcn `command` for the ⌘K palette |
| Stats | shadcn `card`, `chart` (Recharts), `progress`, `badge`, `skeleton` |
| Lists | shadcn `table` + TanStack Table (the shadcn *data-table* pattern), `empty`, `item`, `pagination` |
| Forms | shadcn `field`, `input`, `select`, `combobox`, `switch`, `textarea`, `input-group`, `radio-group` |
| Overlays | shadcn `dialog`, `sheet`, `alert-dialog`, `popover`, `tooltip`, `sonner` |
| Layout | shadcn `tabs`, `resizable`, `scroll-area`, `separator`, `accordion` |
| AI chat | **AI Elements** registry (shadcn-compatible, Apache-2.0): `conversation`, `message`, `prompt-input`, `tool`, `confirmation`, `reasoning` |
| Terminal | **Create:** `<Terminal>` wrapping xterm.js, themed from CSS vars |
| Code/compose editor | **Create:** `<CodeEditor>` wrapping CodeMirror 6 (YAML lang, lint) |
| File browser | **Create:** `<FileBrowser>` built from table, breadcrumb, context-menu, dropzone |
| App store card / app tile | **Create:** composed from card, badge, button |
| Log viewer | **Create:** virtualized `<LogStream>` (ANSI → spans) |
| Job progress | **Create:** `<JobToast>` on top of sonner + progress |

The rule: run `pnpm dlx shadcn@latest search` (and the AI Elements registry) before writing anything. Created components go into `packages/ui/src/components/athena/` and use only theme tokens.

### 5.4 Runtime appearance settings

shadcn presets are applied at *init/build time* by the CLI. Athena needs them switchable *at runtime* from Settings, so they're turned into data attributes and CSS variables:

| Setting | Runtime mechanism |
|---|---|
| Light/dark/system | `next-themes` (`class` attribute) |
| Base color | `[data-base="neutral|stone|zinc|mauve|olive|…"]` blocks that set `--background`, `--foreground`, `--muted`, `--border`… |
| Theme (accent) | `[data-theme="…"]` blocks that set `--primary`, `--ring`, `--sidebar-primary`… |
| Chart color | `[data-chart="…"]` blocks that set `--chart-1…5` |
| Body / heading font | All curated fonts loaded with `next/font` as CSS variables, then `[data-font="inter"]` → `--font-sans`, `[data-font-heading="…"]` → `--font-heading` |
| Radius | `[data-radius]` → `--radius` |
| Style (mira, luma, …) | **Spike needed.** See below |

- **Generated CSS (M4).** `scripts/gen-theme-css.mjs` (`pnpm gen:theme`) asks the registry's `/init` endpoint (what the shadcn CLI uses) for every base color, theme, chart color and radius, and writes `packages/ui/src/styles/themes.css` plus `themes.json` (the options and swatches the Settings page offers). Both are committed, so builds don't need the network; rerun after upgrading shadcn. Nothing is hand-copied.
  - The registry's model, found by probing: a theme is a colored accent (17) or the base color's own name ("match base", valid only with that base); explicit chart colors work the same way, and `neutral` charts means "follow the theme" (sent as no `chartColor`). `gray` is in the preset lists but the registry refuses it, so it's skipped.
  - Base blocks carry every variable; theme blocks carry what each theme actually sets, worked out per mode on two bases (most set primary, secondary, sidebar-primary and the charts; rose also sets the dark sidebar); chart blocks come last and override. The script verifies every colored theme on a third base, plus an explicit chart, against the registry and fails if they don't compose.
  - Selectors are `:root[data-base=…]` and `:root.dark[data-base=…]` (and the same for theme, chart, radius), which beat the `:root`/`.dark` defaults in `globals.css` without `!important`.
- **Fonts (M4).** All 26 preset fonts are self-hosted with `next/font` (`apps/web/lib/fonts.ts`) as `--font-<id>`; only Inter and Geist Mono are preloaded, so another font's files load the first time a page uses it. `[data-font]` sets `--font-sans`, `[data-font-heading]` sets `--app-font-heading`, and `globals.css` maps Tailwind's `font-heading` to it (Tailwind inlines `@theme inline` values, so the utility has to read a runtime variable). A `satisfies` check fails the build if shadcn adds a font.
- **Persistence (M4).** Saved per user (`users.appearance`, JSON; `GET/PUT /api/settings/appearance`). The server only checks the id shape; the UI normalizes unknown ids to the defaults. An inline script in `<head>` (`APPEARANCE_SCRIPT`) copies the browser's last-known settings onto `<html>` before first paint (verified: the attributes are set when `<body>` starts parsing); signed in, the account's settings are fetched and win. Changes apply instantly and are saved 400 ms after the last one. Dark/light/system stays with `next-themes`.
- **Preset codes (M4).** `shadcn/preset` (`encodePreset`/`decodePreset`, pure and browser-safe) runs in the browser. Export keeps b0's style, icons and menus; import applies colors, fonts and radius and reports what it skipped (another style, icon library, menu colors, or an option the registry doesn't serve).
- **Style (decided: one style in the MVP).** Styles change component class names and spacing, not just variables, so the MVP ships the style from preset `b0` only. The Style field in Settings shows the current style as read-only, with a "coming later" note. Post-MVP option: generate a `packages/ui` build per style and swap them by attribute-scoped CSS.

### 5.5 Routes

```
/setup                    first-run wizard (admin account, then optional AI provider)
/login
/                         dashboard
/apps                     installed apps
/apps/view?name=…         details · logs · shell · compose · settings
/apps/new                 custom app (compose / docker run import)
/store                    catalog browse/search
/store/view?catalog=…&id=…    app page + install (with variant picker)
/store/catalogs           remote catalogs
/packages                 tabs per detected manager
/automation               triggers, job runs, webhook and MCP addresses
/files                    file manager (locations + cloud remotes)
/files/shares             share links (WebDAV is in Settings → System)
/files/smb                SMB shares (Linux with Samba)
/s/<token>                a share link's public page (the /s/ export, served for any token)
/cloud                    rclone remotes + sync jobs
/containers               every container on the runtime
/terminal                 host terminal
/assistant                full-page chat (also available as a sheet everywhere)
/settings/{appearance,account,ai,system}
```

Static export doesn't allow dynamic segments without `generateStaticParams`. The workaround is query params (`/apps/view?name=…`) or a catch-all with client routing. **Decision: use query params for detail pages.**

---

## 6. Backend layout and API

```
apps/server/
  pyproject.toml            # uv project; entry point `athena`
  src/athena/
    main.py                 # create_app(): routers, app.state, static mount, lifespan
                            # (detection, monitor, scheduler, MCP, models.dev refresh)
    cli.py, config.py       # the CLI; settings (platformdirs data dir, ATHENA_* env)
    jobs.py                 # in-memory job runner, SSE events, cancel
    audit.py, monitor.py, system_settings.py, crypto.py, logging_setup.py
    api/                    # one thin router per area
    auth/                   # argon2 passwords, sessions, CSRF (deps.py)
    db/                     # models.py (SQLModel), engine.py, migrations/ (Alembic)
    platform/               # probe.py, detect.py, capabilities.py, store.py
    containers/             # runtime.py (Docker-compatible CLI per runtime), service.py
    apps/                   # store.py (compose apps on disk), docker_run.py (converter)
    catalog/                # model.py (x-athena), loader.py, registry.py, remote.py, casaos.py
    packages/               # base.py, linux.py, apps.py (brew, flatpak, snap), windows.py
    terminal/               # pty.py (POSIX pty and ConPTY), shells.py
    files/                  # paths.py, locations.py, ops.py, shares.py, smb.py, webdav.py
    cloud/                  # rclone.py (sidecar), remotes.py, transfers.py
    assistant/              # kinds.py, models_dev.py, providers.py, chat.py, tools.py,
                            # actions.py, and the harness capabilities (§4.5)
    automation/             # service.py: triggers, job runs, scheduler
    mcp/                    # server.py (tools), auth.py (session or bearer)
    tunnel/                 # base.py, cloudflare.py, tailscale.py, ngrok.py
    service/                # athena service install per OS (platforms.py, plan.py)
  tests/                    # pytest; parsers pinned by recorded CLI fixtures
catalog/                    # built-in app catalog
```

API surface (from the routers; the generated `packages/api-client/openapi.json` is the exact list):

```
GET  /api/health
GET  /api/auth/status   POST /api/auth/{setup|login|logout|password}
GET  /api/system/info   GET /api/system/stats   GET /api/system/stats/stream (SSE)
GET  /api/system/capabilities   POST /api/system/capabilities/refresh
GET  /api/jobs/{id}   GET /api/jobs/{id}/events (SSE)   POST /api/jobs/{id}/cancel
POST /api/containers/runtime/start
GET  /api/containers   GET/DELETE /api/containers/{ref}   POST …/{ref}/{start|stop|restart}
GET  /api/containers/{ref}/logs   GET …/{ref}/logs/stream (SSE)
GET/POST /api/apps   GET/PUT/DELETE /api/apps/{name}   PUT …/{name}/env   POST …/{name}/{action}
POST /api/apps/convert (docker run → compose)   POST /api/apps/validate
GET  /api/store/categories   GET /api/store/apps   GET …/apps/{catalog}/{app_id}   POST …/install
GET/POST /api/store/catalogs   POST …/{id}/refresh   DELETE …/{id}
GET/PUT /api/settings/{appearance|system|ai}
GET  /api/packages   GET …/{manager}/{search|installed|upgradable}
POST /api/packages/{manager}/{install|uninstall|upgrade|refresh} (jobs)
WS   /api/terminal/ws?target=host|container:{ref}
GET/POST /api/files/locations   PUT/DELETE …/{id}
GET  /api/files/{list|download}   GET/PUT /api/files/text
POST /api/files/{folder|rename|delete|transfer}   POST/DELETE /api/files/upload
GET/POST /api/shares   PUT/DELETE /api/shares/{id}   GET/POST /api/shares/smb   DELETE …/smb/{id}
GET  /api/public/shares/{token}[/list|/download]   POST …/unlock   POST/DELETE …/upload
GET/PUT /api/webdav   POST /api/webdav/password   /dav/… (WebDAV)   /s/{token} (share page)
GET  /api/cloud/providers   GET/POST /api/cloud/remotes   GET/PUT/DELETE …/{name}   POST …/{name}/answer
GET  /api/cloud/files/{list|download}   POST …/files/{folder|rename|delete}   POST/DELETE …/files/upload
POST /api/cloud/transfer   POST /api/cloud/sync/preview   POST /api/cloud/sync
GET  /api/assistant/kinds   POST /api/assistant/kinds/refresh
GET/POST /api/assistant/providers   PUT/DELETE …/{id}   POST …/{id}/test   GET …/{id}/models
GET  /api/assistant/models   GET /api/assistant/integrations/kinds
GET/POST /api/assistant/integrations   PUT/DELETE …/{id}
GET/POST /api/assistant/conversations   GET/PATCH/DELETE …/{id}
POST …/conversations/{id}/messages (SSE)   POST …/{id}/approvals (SSE)   POST …/{id}/stop
GET/POST /api/automation/triggers   GET/PATCH/DELETE …/{id}   POST …/triggers/validate-action
GET  /api/automation/jobs   GET /api/automation/jobs/{run_id}
POST /api/automation/webhook/{token} (public)
GET  /api/tunnel/status   POST /api/tunnel/{start|stop|install}   PUT /api/tunnel/{config|service}
     /api/mcp (MCP streamable HTTP)
```

---

## 7. Security baseline

- Binds to LAN by default. First run forces the admin account to be created before anything else is reachable.
- Public routes (no session): `/api/health`, `/api/auth/*`, share links (`/api/public/shares/{token}`, `/s/{token}`), the automation webhook `POST /api/automation/webhook/{token}` (the trigger's random token is the credential) and `/api/mcp` with the `ATHENA_MCP_TOKEN` bearer (acts as the admin; a session cookie works too). `/dav/` has its own sign-in. Everything else needs a session.
- Session cookies are `HttpOnly` and `SameSite=Strict`, with CSRF tokens on mutating requests and login rate limiting.
- The terminal, package installs and the assistant's shell are the most powerful features. They're admin-only and every use is written to the audit log. The terminal (Settings → System) and the assistant's shell (Settings → AI, off by default) can be turned off; package installs have no off switch yet.
- Remote access tunnels (§4.8) put the UI on the internet: off by default, admin-only, with their tokens encrypted at rest.
- The rclone rcd and container sockets are never exposed beyond localhost.
- Secrets: AI provider keys, integration tokens and tunnel tokens are encrypted at rest (Fernet) with a key file `<data-dir>/secret.key` (0600), not the OS keyring, which headless Linux hosts usually lack (M7, see §4.5). The rclone config is a 0600 file in a 0700 folder, with passwords obscured by rclone (reversible, not encryption). See §11.

---

## 8. Distribution (MVP)

- **Dev:** `pnpm dev` (Next on :3000, proxying `/api` to :8420) plus `uv run athena --reload`.
- **Release:** release-please tags a version from Conventional Commit PR titles. The release workflow then:
  1. builds the web app and copies `out/` into the Python package;
  2. builds the `athena_server-<version>-py3-none-any.whl` wheel;
  3. attaches the wheel and the install scripts to the GitHub release.
- **One-line install, CasaOS-style:**
  - Linux/macOS: `curl -fsSL https://github.com/tiagozaccaro/athena/releases/latest/download/install.sh | bash`. It needs `sudo` on Linux.
  - Windows: `irm …/install.ps1 | iex`.
  - The scripts install the runtime where the decisions allow it (Docker Engine on Linux, Colima on macOS; Windows is detect only), plus uv and the wheel through `uv tool install`, in Athena-owned directories.
  - They support `--version`, `--dry-run`, `--no-runtime`, and `--uninstall [--purge]`, plus `--wheel <path|url>` (`-Wheel` on Windows) to install an unreleased build from `scripts/build-wheel.sh`.
- **End-to-end check:** the `E2E` workflow builds the wheel from the commit and runs the real installers on Ubuntu, macOS and Windows runners. It checks the service starts, runs `scripts/e2e/smoke.py` (Playwright: setup, sign-in, every page, the host terminal, phone width and dark mode), then uninstalls with `--purge` and checks that nothing is left. Locally, the same steps run in a Lima VM (see CONTRIBUTING).
- **Service install:** `athena service install --data-dir --port` registers a systemd unit on Linux, a launchd agent on macOS, or a Scheduled Task at logon on Windows.
- **Later:** single-file binaries (PyInstaller/Nuitka) and native installers.

---

## 9. Dependency / license inventory

| Component | License |
|---|---|
| Next.js, React, shadcn/ui, Radix/Base UI, Tailwind, Recharts, TanStack Table | MIT |
| shadcn chat components and AI Elements patterns (copied in) | MIT |
| cryptography (Fernet for AI keys) | Apache-2.0 / BSD-3-Clause |
| react-markdown, remark-gfm (assistant replies), @shadcn/react (Message Scroller) | MIT |
| Provider SDKs pulled in by pydantic-ai-slim: openai, anthropic, google-genai, groq, mistralai, cohere (the `cohere` extra, #149) | Apache-2.0 / MIT |
| cohere's dependencies: fastavro, filelock (MIT); tokenizers, huggingface-hub, hf-xet, types-requests (Apache-2.0); fsspec (BSD-3-Clause); tqdm | MIT / Apache-2.0 / BSD-3-Clause; tqdm is MPL-2.0 AND MIT |
| boto3 (Bedrock, via pydantic-ai-slim) | Apache-2.0 |
| xterm.js, CodeMirror 6, next-themes, openapi-typescript | MIT |
| shadcn CLI package (`shadcn/preset` used at runtime) | MIT |
| Preset fonts via `next/font/google` (Inter, Geist, Lora, Roboto and the other 22) | SIL OFL 1.1 / Apache-2.0 |
| Base UI (`@base-ui/react`), `cn`, Turborepo, openapi-fetch, lucide-react, sonner, zod | MIT / ISC |
| pydantic-settings, platformdirs, hatchling | MIT |
| SQLModel, SQLAlchemy, Alembic, argon2-cffi | MIT |
| python-on-whales, PyYAML | MIT |
| croniter | MIT |
| mcp (MCP client and server SDK) | MIT |
| fastmcp (Athena's MCP server, §4.7) | Apache-2.0 |
| exa-py (web research) | MIT |
| pgtask (durable execution) | MIT |
| psycopg (pgtask's Postgres driver; used only when durable execution is configured) | LGPL-3.0-only |
| CodeMirror 6, @uiw/react-codemirror | MIT |
| js-yaml (compose form ↔ YAML), embla-carousel-react, embla-carousel-autoplay (store carousel), tw-animate-css | MIT |
| class-variance-authority | Apache-2.0 |
| dashboard-icons (catalog icons, loaded by URL) | Apache-2.0 |
| httpx2 (provider HTTP at runtime, and the test client) | BSD-3-Clause |
| Playwright for Python (e2e smoke test only, not shipped) | Apache-2.0 |
| pytest-cov, coverage.py (test coverage only, not shipped) | MIT / Apache-2.0 |
| FastAPI, SQLModel, Pydantic, pydantic-ai, pydantic-ai-harness, uvicorn | MIT / BSD |
| json-repair (the harness's `repair-tool-arguments` extra) | MIT |
| stackone-defender (the harness's `prompt-injection-defender` extra; no dependencies, an 18 MB wheel with an unused bundled model) | Apache-2.0 |
| pydantic-monty, pydantic-monty-client, pydantic-monty-runtime (the harness's `dynamic-workflow` extra: the Monty Python sandbox; wheels for Linux, macOS and Windows) | MIT |
| Docker Engine (Moby), Docker CLI, Compose v2 | Apache-2.0 |
| python-on-whales, psutil, platformdirs, pywinpty (Windows only), send2trash | MIT / BSD / ISC |
| wsgidav (with defusedxml, Jinja2, json5) | MIT / PSF / BSD-3 / Apache-2.0 |
| a2wsgi | Apache-2.0 |
| Colima, Lima | MIT / Apache-2.0 |
| Podman | Apache-2.0 |
| rclone | MIT |
| winget-cli, scoop, Chocolatey CLI | MIT / Unlicense / Apache-2.0 |
| Homebrew | BSD-2 |
| CasaOS AppStore (catalog data) | Apache-2.0 |
| Agent skills in `.agents/skills/` (dev tooling, not shipped): `shadcn`, `pydantic`, `building-pydantic-ai-agents`, `pydantic-ai-harness` / `frontend-design` | MIT / Apache-2.0 |
| ~~Docker Desktop, macFUSE, Umbrel apps~~ | Excluded (proprietary / non-commercial) |

---

## 10. Milestones

| # | Milestone | Done when |
|---|---|---|
| M0 | Monorepo skeleton | shadcn init done, uv server, turbo, API client generation, CI on all 3 OSes (GitHub Actions matrix) |
| M1 | Platform + capabilities | The manifest is correct on Linux, macOS and Windows, the UI hides missing features, and the first-run wizard and login work |
| M2 | Containers + apps | Runtime detection on all OSes (start for Colima), Windows setup instructions, app lifecycle, logs, compose and docker-run import |
| M3 | App store | Built-in catalog, remote catalogs, CasaOS importer, install form |
| M4 | Dashboard + appearance | Live stats and charts. Runtime theme/base/chart/font/radius switching, plus the style decision |
| M5 | Packages + terminal | All detected managers with jobs. Host terminal and container exec on all OSes |
| M6 | Files, shares, cloud | File manager, share links, WebDAV, rclone remotes and copy/sync |
| M7 | AI assistant | Agent with service tools, approval flow, provider settings, streaming chat UI |
| M8 | Automation | Cron and webhook triggers with job-run history, Athena's MCP server, the Automation page |

M2–M4 can proceed in parallel once M1 lands, and so can M5 and M6. M7 depends on the service layers it wraps, and M8 on the app and package services its actions call.

---

## 11. Decisions log

| Question | Decision |
|---|---|
| Untrusted tool results (M7 D1) | Always on, no setting: `PromptInjectionDefender` (patterns only, blocks high risk, audits every detection), secret redaction in tool results with a `ToolGuardrail`, and `RedactionGuard` refusing placeholders in arguments. `artifact_scanning` moves to stage 2 with `memory` and `skills`, the only things it scans. `app_logs` returns one text per container so the defender reads it |
| Planning and questions (M7 D2) | `Planning` with only `write_plan` (whole-plan replacement: no step ids, and ~3,000 characters of tool schema per request instead of ~6,500 for all six plan tools) on a `SqlitePlanStore` per chat; `AskUser(answerer=None)`, so a question pauses the run like an approval and is answered through the same `/approvals` endpoint, which takes every waiting action and question in one body (a run resumes only with every call answered). No settings and no audit for answers (they change nothing on the host) |
| Memory and skills (M7 D2) | `Memory` on `SqliteMemoryStore` in the data dir (concurrent chats; `FileStore` allows one writer per folder), one namespace per admin, on by default with a switch; `Skills` from `<data-dir>/assistant/skills`, added by hand for now; both behind an `ArtifactScanner` that audits each finding. The memory excerpt lives in history as a tagged user part, hidden from the chat UI |
| Delegation and background (M7 D2) | One explicit read-only `investigator` built per turn on the chat's model (not `include_self`: Athena's capabilities are per run, so `self` would lack the safety guards; and delegates can't use approval cards or questions). `run_in_background` on `delegate_task` only, because pausing for an approval cancels background tasks |
| Advisor (M7 D2) | Optional `advisor_model` in Settings → AI, off by default. Local mode only (same on every provider, answer screened like any tool result), the question only (`forward_history=False`), `max_uses=1` per request, counted in the spend limit |
| Double-checked answers (M7 D2) | `RefineOutput` (one round) behind a "Double-check answers" switch, off by default: it costs at least one extra request per turn, which roughly doubles reply time on local models. The draft is kept and folded in the UI, not deleted |
| Workflows (M7 D2) | `DynamicWorkflow` with only the read-only `investigator`, offered only when the model's context is ≥ 32K tokens (its description costs ~900 tokens per request). Helpers share the chat's usage, so the turn limits bound the tree; `max_agent_calls=5`. No approval-needing helpers: a workflow can't pause for a card |
| Compaction (M7 D) | Always on, no setting: clear old tool results, then summarize with the chat's model, else drop the oldest messages; triggered at 75% of the window looked up per turn (provider field, provider's own report, genai-prices, then a cautious guess). The full transcript is stored apart from the compacted history so the chat UI never loses messages |
| shadcn style switching | One style (from preset `b0`) in the MVP. Colors, theme, chart colors, fonts and radius switch live |
| Windows container runtime | Detect only: Docker Engine in WSL2, Podman, or Rancher Desktop. Show instructions when none is found |
| Linux privilege | Run as a root systemd service (CasaOS-style) |
| Next.js mode | Static export served by FastAPI |
| shadcn primitives (M0) | Base UI (`base-nova` style from preset `b0`), lucide icons |
| Dev API access (M0) | `next.config.ts` adds an `/api` rewrite to the server in `next dev` only; builds are static exports with `trailingSlash: true`, served by FastAPI `StaticFiles` |
| Python (M0) | 3.13 for the server and the installers (`requires-python >= 3.12`) |
| Versioning (M0) | release-please `simple` type with `extra-files` that bump `pyproject.toml` and both `package.json` files; first release is 0.1.0 |
| Capability detection (M1) | All host access goes through `athena.platform.probe.Probe` (never raises); the Docker-compatible API is pinged directly over a unix socket or Windows named pipe, with no Docker SDK; the manifest lists only capabilities relevant to the host's OS |
| Auth (M1) | One admin, created on first run at `/setup`. Passwords use argon2id. The session cookie `athena_session` is a random token (only its SHA-256 is stored), HttpOnly, SameSite=Strict, Secure on HTTPS, with a 30-day TTL. A per-session CSRF token goes in the `X-CSRF-Token` header on writes. Failed logins are limited to 5 per client per 5 minutes. Public routes: `/api/health`, `/api/auth/*`, and the static UI (later also share links, the automation webhook and `/api/mcp` with its bearer token; see §7) |
| Container access (M2) | One CLI-based path for every runtime via `python-on-whales` (see §2 Decisions). The `containers` capability carries the engine `endpoint`. Container refs are validated against `^[A-Za-z0-9][A-Za-z0-9_.-]*$` before reaching the CLI |
| Apps (M2) | An app is a compose project in `<data-dir>/apps/<name>/compose.yaml` (previous version kept as `compose.prev.yaml`) plus an `apps` row. Compose runs with `ATHENA_APP_DATA=<data-dir>/apps/<name>/data`, so files can use `${ATHENA_APP_DATA}`. Validation is a structural check plus `docker compose config --quiet`. Lifecycle (deploy, edit, start, stop, restart, update = pull + up, remove with optional `--volumes` and data folder) runs as jobs, one per app at a time. `docker run` import is a shlex + flag-map converter with warnings for unsupported flags. On macOS, Colima only mounts `$HOME`, which the default data dir is under |
| App store format (M3) | Catalog apps are plain compose files with `x-athena` metadata (`title`, `description`, `category`, `icon`, `homepage`, `web_port`, `notes`, `tagline`, `tags`, `features`, `screenshots`, `license`, `popular`, `env` fields). Install values use standard `${KEY}` interpolation and are written to `.env` (mode 600) next to `compose.yaml`; no custom template syntax. Default tokens: `@timezone`, `@uid`/`@gid`, `@app_data[/sub]`; `generate: secret` fills passwords. Every `${…}` must be declared or `ATHENA_APP_DATA`. The built-in catalog is `catalog/` at the repo root (49 apps then, about 200 now; see `catalog/README.md`), bundled into the wheel as `athena/catalog_builtin`. Icons come from dashboard-icons (Apache-2.0) via jsDelivr |
| Store presentation | Cards show the first screenshot as a cover (falling back to a tinted panel with the icon when it's missing or fails to load), the tagline and up to two tags; `popular: true` apps get an autoplay carousel at the top of `/store` (#103; it was a scrolling strip before). The app page adds a screenshot gallery with a lightbox, "What you get" features, license and a "More in <category>" row. Screenshots are hotlinked from the project's own repository or docs, so no images live in the repo or the wheel |
| Remote catalogs (M3) | Downloaded as an archive over HTTPS (no git): GitHub/Codeberg/GitLab repo URLs are turned into archive URLs; direct .tar.gz/.zip links work. Safe extraction (no traversal or links, 200 MB download, 50k files, 1 GB extracted). The folder holding `apps/` (Athena) or `Apps/` (CasaOS) is found up to 8 levels deep, normalized into `<data-dir>/catalogs/<id>/apps/*/compose.yaml`, and swapped in atomically; a failed refresh keeps the previous copy and records the error. Refresh runs as a job |
| CasaOS import (M3) | `x-casaos` converted to `x-athena`: `/DATA/AppData/$AppID` becomes `${ATHENA_APP_DATA}`, `/DATA/<X>` becomes a path field, `port_map` becomes `WEB_PORT`, `$PUID/$PGID/$TZ` become default-token fields, and other variables become fields (secrets generated). Parsed with YAML 1.2 booleans like compose. The one-click source was the official CasaOS-AppStore release `main.zip` (182 apps, all pass `compose config`); the full repo is too large and the pruned `_appstore` mirror is unlicensed. Imported files keep upstream specifics (e.g. Raspberry Pi device mappings). Since #120 those apps are in the built-in catalog, so #121 removed the one-click source; the importer still reads any CasaOS-style archive added as a remote catalog |
| Host stats (M4) | psutil sampled every 2 s into a 1 h ring buffer; JSON snapshot with history plus an SSE stream of `stats` events. No capability (psutil runs on all OSes); unavailable metrics are `null`. Disks are filtered and de-duplicated by (total, free) so APFS volumes show once |
| Package managers (M5) | One class per manager over a shared async runner and pure parsers pinned by fixtures (real recordings where a container could produce them). Machine-readable output where it exists (brew JSON, zypper XML, scoop export, choco `-r`), otherwise stable formats (`dpkg-query`, `rpm --qf`, `apt-get -s`). One job per manager at a time; installs, uninstalls, upgrades and refreshes are audited as `package.<action>` with `<manager>:<name>`. The Packages nav item shows when any `packages.*` capability is present (`capability: "packages.*"`) |
| Runtime appearance (M4) | Theme CSS generated from the shadcn registry's `/init` endpoint by `scripts/gen-theme-css.mjs` into committed `themes.css`/`themes.json`, verified against the registry when generated; data attributes on `<html>`, applied before paint by an inline script; saved per user in `users.appearance`; preset codes via `shadcn/preset` in the browser. Style, icons and menus stay b0's |
| Password change (M4) | `POST /api/auth/password` needs the current password (wrong one is 400, not 401, so the UI doesn't sign out; failures count toward the login throttle), signs out the user's other sessions and keeps this one; audited as `auth.password` |
| Server shutdown (M4) | `athena serve` sets uvicorn `timeout_graceful_shutdown` to 5 s. SSE streams never end on their own, so without it an open dashboard kept the server (and a service stop or restart) waiting forever |
| Jobs (M2) | In-memory job runner (`athena.jobs`) with output lines streamed over SSE (`/api/jobs/{id}/events`); the last 100 finished jobs are kept. The durable record of privileged actions is the `audit_log` table |
| Terminal pty (M5) | Stdlib pty with `subprocess.Popen(start_new_session=True)` and a `TIOCSCTTY` exec shim on POSIX, instead of ptyprocess. `pty.fork()` in the multi-threaded server runs Python in the child (Python 3.12+ warns that this can deadlock). pywinpty (ConPTY) on Windows |
| Terminal auth (M5) | The WebSocket checks the cookie itself (`require_user` can't apply to WebSockets), then requires the CSRF token in the first message. Admin only. Signing out closes open terminals within 60 s, and turning the terminal off closes them at once. Container shells use `docker exec -it` through the runtime CLI, not the Docker API, matching the M2 CLI decision |
| System settings (M5) | One JSON row in the `system_settings` table (migration 0007), behind `GET/PUT /api/settings/system`. Only admins can change it. It holds `terminal_enabled` and the tunnel settings (`tunnel_*`, §4.8). The assistant-shell switch lives with the AI settings instead; a package-install switch (§7) doesn't exist yet |
| End-to-end install check | A separate `E2E` workflow, not part of `ci-ok`: it's slow and changes the runner's service manager. It runs on pushes to main, on PRs that touch the installers or the service code, and on demand. It installs a wheel built from the commit (`--wheel`), because waiting for a release would only test code that has already shipped. Hosted runners can't run Colima's VM (macOS) or WSL2 (Windows), so containers are only checked on Linux there. Docker in WSL still needs a real Windows machine |
| Share links (M6) | `shares` table, token stored as is (it's the link). Public API `/api/public/shares/{token}` limited to the shared item. Passwords unlock with a path-scoped cookie holding HMAC(password hash, token), so there's no server state and a new password signs everyone out. Upload links never replace files. The page is the static `/s/` export served for any `/s/<token>` |
| WebDAV (M6) | wsgidav at `/dav/` through a2wsgi, off by default. Root = the file manager's locations; same path rules as the files API; location folders can't be deleted, moved or replaced. HTTP Basic with a generated WebDAV password, not the account password. Sandbox CSP on every response |
| SMB shares | The `shares.smb` capability detects the host's Samba server on Linux and `/api/shares/smb` creates, lists and removes SMB shares for a file location by writing a section to /etc/samba/smb.conf and reloading smbd (Athena runs as root there). macOS and Windows report `shares.smb` as unsupported until their share creation is wired. Tracked in a `smb_shares` table (migration 0013) so Athena can list and remove the shares it created. |
| Cloud storage (M6) | rclone rcd as a sidecar started on first use, localhost only, random credentials, Athena's own config file. Remotes appear as sources in the existing file manager instead of a second browser. OAuth via `rclone authorize` and a pasted token, because the redirect to the server's 127.0.0.1 only works with a browser on the server itself. Sync always offers a preview of what it deletes first. Config encryption with the OS keyring is postponed: headless Linux hosts usually have no keyring, and rclone's own config password would have to live next to the config anyway |
| Job progress and cancel (M6) | `JobOut` gained optional `progress` (fraction and text, also sent as SSE `progress` events) and `cancellable`; `POST /api/jobs/{id}/cancel` stops jobs started with `cancellable=True`. The job dialog shows a bar and a Cancel button when they're there |
| Automation triggers and job runs (M8 A) | Durable triggers (`automation_triggers`) fire background jobs on a cron expression or an HTTP webhook; each execution is recorded in `automation_job_runs` for audit and history. A scheduler loop started in the server lifespan fires due cron triggers; trigger actions run as normal Athena jobs over SSE. Triggers and job runs are managed through `GET/POST/PATCH/DELETE /api/automation/triggers` and `GET /api/automation/jobs`. HTTP triggers are fired externally through the public `POST /api/automation/webhook/{token}` (the token is the credential, no session needed — for n8n and other automation). |
| MCP server (M8 B) | Athena exposes its capabilities as MCP tools over streamable HTTP at `/api/mcp` (built on fastmcp): list apps, run app lifecycle actions, list package managers and capabilities, host stats, and create/list automation triggers and job runs. Auth is a session cookie (browser-based MCP clients) or the `ATHENA_MCP_TOKEN` bearer token (n8n MCP client node, external agents). Session clients act as the signed-in user; an `ATHENA_MCP_TOKEN` client acts as the oldest admin (409 with a clear error when no admin exists), and its audit rows carry that admin's username with "via MCP token" in the detail. Tools that change something are audited (app actions through `apps.start_app_action`, shared with the route; trigger creation directly); read-only tools aren't (#149) |
| AI providers (M7) | OpenCode/Hermes-style: any number of providers (10 cloud kinds, Ollama, OpenAI-compatible), the model picked per run and per conversation. Server-wide, admin-managed, API keys only. Keys encrypted with Fernet and a 0600 key file in the data dir (not the OS keyring). Model lists come live from each provider (cached); ids can be typed by hand. Later extended with models.dev (see "Provider kinds from models.dev") |
| Assistant shell (M7 C) | The harness `Shell` with `Permissions` (read-only mode: every command asks), in a `LocalWorkspace` on Linux and macOS and in our `WSLWorkspace` on Windows with a WSL distro; Athena's own PowerShell `run_command` only on Windows without WSL. Our `ShellGuard` capability checks every program in a pipe or chain against an editable allowlist before `Permissions` asks (the harness checks only the first word, and only after approval) and writes the audit row. First shipped as our own tool for every OS (#46), then moved onto the harness at the maintainer's request, with WSL for Windows. The rest of the harness follows in seven stages (§4.5 Parts, D), including sandboxes, hosted integrations, durable execution and the coding stack at the maintainer's request |
| AI actions (M7 B) | Mutating assistant tools are pydantic-ai deferred tools with an Approve/Deny card per call, answered all at once through `/approvals`; a new message denies what's waiting. Tools call the existing route helpers (same checks and audit), and job-starting tools wait for their job. No auto-approve or per-tool allowlist yet |
| AI chat transport (M7) | Own typed SSE events from `run_stream_events()`, read by a small hook. Not the Vercel AI SDK adapter / `useChat`: the UI uses shadcn's chat components and AI Elements patterns without the `ai` packages |
| First AI provider (M7) | No default. An empty Settings → AI offers "Use Ollama on this server" when `ai.ollama` is ready, "Add a cloud provider" otherwise |
| Assistant robustness (M7 D1) | `RepairToolArguments`, `DetectLoops` (nudge, not error) and `ToolOutputLimits` (spill over 24,000 characters to the data dir, then truncate) on every run, with no settings: they cost nothing on a run that doesn't need them. The spill threshold sits above Athena's own 20,000-character tool caps so existing tools are unchanged; the shell's cap went from 20,000 to 400,000 so its long output spills instead of being cut (found in browser testing: the old cap kept it under the threshold) |
| Reminders, cache health and spend (M7 D1) | Always on, no setting: `SystemReminders` (stay on task every 8 requests; a note when the turn's limits are close) and `WarnOnCacheBusts` sent to the log. Our per-chat spend limit (`UsageLimits.cost_limit` over the saved `Conversation` usage) stays; the harness `SpendLimits` isn't used, since its counters are in memory, Redis or PostgreSQL |
| AI in the setup wizard (M7 C) | An optional second step after the admin account: one provider (Ollama in one click when detected), a connection test and the default model. Skippable; everything else stays in Settings → AI |
| Database (M1) | SQLite at `<data-dir>/athena.db` (WAL, foreign keys on), SQLModel models, Alembic migrations run on every start from code. A test fails if models and migrations drift |
| Design tokens per feature (frontend-design rule) | A design's "compact token system" is picked from the existing theme tokens and fonts (preset `b0`, generated `themes.css`). A feature adds no colors or tokens of its own |
| Provider kinds from models.dev (#126) | 12 native kinds stay in `assistant/kinds.py` (now including Cohere); every other OpenAI-compatible provider comes from models.dev, fetched at startup and cached 24 h in `models_dev_cache` so the server works offline after one fetch, refreshable from Settings → AI (`POST /api/assistant/kinds/refresh`). Replaces the hand-kept list and the generic "OpenAI-compatible" kind; reverses the earlier "not models.dev" choice in exchange for one outside request per day |
| Remote access (§4.8) | Three providers behind capabilities (`tunnel.cloudflare`, `tunnel.tailscale`, `tunnel.ngrok`), driven through their CLIs. Settings in the `system_settings` row, not a new table; keys ending in token/secret/password/key encrypted with `SecretBox` (`enc:` prefix), decrypted only on start and never returned (`tunnel_secrets_set` says which are stored); every state-changing route admin-only, status open to signed-in users (#150). Cloudflare offers a no-account quick tunnel, so there's always one free option |
| Queue for local AI servers (§4.5) | Models on a local server (Ollama, LAN/loopback base URLs) share one `ConcurrencyLimitedModel` queue per server, one request at a time; cloud providers aren't queued. Chat titles are generated after the turn, outside it, so they never hold the chat |

## 12. Open questions

None open. The default AI provider question was settled in M7 (§11, "First AI provider").
