# Plan: release 0.1.0

_Written 2026-11-21 from `docs/STATUS.md`, `docs/plans/improvements.md`, `docs/design/milestones.md`, the open PRs (#3 release, #216 backup part 2) and a sweep of the code, workflows and gotchas. Tick items off here as they merge; the release-please PR #3 is merged by the maintainer only when every **Must** item is ticked._

## Goal

0.1.0 is the first build anyone can install with the one-line installer. It has to install cleanly on Linux (amd64 and arm64), macOS and Windows, every page it shows has to work on that host, nothing it offers may be a dead toggle, and a user who loses their disk can get their apps back. Everything else waits for 0.2.0.

**Scope rule:** M0–M8 are the feature set. 0.1.0 adds backup and restore (spec approved) and otherwise only fixes, hides or verifies what exists. New features from the competitor review (2FA, users with roles, app updates, alerts, stats history, disks) are 0.2.0+ unless the maintainer pulls one in (see [Decisions](#decisions-maintainer-2026-11-21)).

**Tiers:** **Must** blocks the release. **Should** goes in if it's ready, otherwise it moves to 0.1.x. **Later** is out of 0.1.0.

## 1. Release pipeline (Must)

The installers download `athena_server-<version>-py3-none-any.whl` from `releases/latest`, so a broken first release breaks every install.

- [x] **uv.lock version bump.** _Done: CI on #3 failed on the lock and on `packages/api-client/openapi.json`; fixed with a release-please `extra-files` entry for the lock and a pinned spec version._ release-please bumps `apps/server/pyproject.toml` but not `apps/server/uv.lock` (`athena-server` stays `0.0.0`), and CI runs `uv sync --locked`. Check CI on #3; if it fails, have the release workflow (or a release-please `extra-files` entry for the lock's `version`) keep the lock in step.
- [x] **No half-published release.** _Done: `draft` + `force-tag-creation`; the assets job publishes after the upload._ `release.yml` publishes the release first and uploads the wheel after; if the upload fails, `releases/latest` points at a release with no wheel and the installers 404. Create the release as a draft (release-please `draft: true` or `force-tag-creation`), upload the assets, then publish.
- [x] **Checksums.** _Done in #226 (not yet run against a published release; see the smoke item)._ Upload `SHA256SUMS` with the wheel and scripts; `install.sh` and `install.ps1` check the wheel against it before `uv tool install`.
- [ ] **Smoke the published release.** After publishing, run the `E2E` install + smoke on Ubuntu, Ubuntu arm64, macOS and Windows against the real release URL (not a local wheel).
- [ ] **Dry run before the real tag.** Run the asset job on a throwaway tag in a fork (or with `workflow_dispatch` and a `0.1.0-rc.1` pre-release) so the first real release isn't the first time the job runs.
- [ ] **Upgrade path.** Re-running the installer (`uv tool install --force`) must stop the service, replace the wheel, run migrations and start it again, on all three OSes. Test 0.1.0-rc.1 → 0.1.0-rc.2 with real data. Document it in the README.

## 2. Backup and restore (Must)

Spec `docs/specs/backup.md`, approved 2026-11-21. Part 1 (Restart Athena) merged in #215; part 2 is split 2a–2e; 2a (foundation) merged in #216.

- [ ] Part 2: 2a foundation (destinations, restic download, `backup` capability) merged in #216; still open: 2b snapshots and plans, 2c retention and versions, 2d restore one app, 2e rclone.
- [ ] Part 3: Backups page and the app's Backups tab.
- [ ] Part 4: named volumes, bind mounts, schedule, `backup.run` automation action, assistant tools, dashboard card.
- [ ] Part 5: restore from the first-run screen and `athena restore`, real-host back up → wipe → restore (Linux VM and Windows E2E).
- [ ] `athena-host-test` for Restart Athena under systemd, launchd and the Windows task (part 1 acceptance check, not done yet).

## 3. Known bugs (Must)

- [x] **Windows `WinError 6`.** _Fixed in #224; still to confirm with three clean Windows E2E runs in a row._ `GET /api/containers` sometimes 500s under the logon task: python-on-whales starts `docker` without `stdin=DEVNULL` under `pythonw.exe` (also on `main`, run 44856906030). Pass `stdin=DEVNULL` (or give every child process `DEVNULL` handles) and get three clean Windows E2E runs in a row.
- [x] **Tunnel auto-start does nothing.** _Done in #223 (UI default) and #225 (lifespan start)._ `tunnel_auto_start` (default `True`) is saved but never read at startup, and the UI falls back to `false` (`tunnel-card.tsx`). Start the tunnel in the lifespan when it's on, and make the UI default match.
- [x] **ngrok service files** _(#230: token in a 0600 file, not tested with a real account)_ hold a literal `${NGROK_AUTHTOKEN}` placeholder, so the service can't authenticate. Write the real token (file mode 0600) or don't offer the service for ngrok. <!-- docs-check: ignore -->
- [x] **cloudflared named-tunnel service** _(#230: runs with `--token-file`; quick tunnels are refused)_ points at `/etc/cloudflared/config.yml`, which nothing writes. Write it, or offer named-tunnel services only after it exists.
- [x] **Automation jobs hang.** _Fixed in #229 (SQLite writes moved off the event loop); the 10 min Colima restart itself wasn't reproduced._ A webhook app restart once took 10 min and `GET /api/automation/jobs` hung meanwhile. Reproduce; a running job must never block reads.
- [x] **ESLint skips `apps/web` `.tsx`** _(#233)_ (`docs/agents/gotchas/web.md`). Fix the config and fix what it then reports, so CI lints the UI.
- [x] **Flaky macOS test** _(#232)_ `test_terminal.py::test_pty_output_and_exit_code` (`docs/agents/gotchas/git-ci.md`). Fix it; don't skip it.
- [x] **HTTPS renewal state is in memory** _(#228)_, so after a restart Settings → HTTPS forgets the last renewal and its error. Persist it (the data dir or `athena.json`'s runtime state).

## 4. No dead switches (Must)

- [x] **Browser tool toggle** (`browser_use_enabled`) does nothing while #89 is blocked on the pydantic-ai-harness / google-genai conflict. Hide it until it works. _Done: hidden unless an old setting left it on._
- [x] **Drop the `coder` extra** of pydantic-ai-harness from `apps/server/pyproject.toml`: `Coder` isn't used on purpose (its shell bypasses `ShellGuard`), and the extra adds install weight. Settles the STATUS open question. _Done._
- [x] **Tunnel warning** (instead of 2FA, decision 2): while a tunnel is on, Settings → System and the dashboard's remote-access card say the terminal, package installs and the assistant are reachable from the internet with one password, and link to turning them off. _Done (Settings → System card and dashboard card)._
- [x] **Durable execution:** label it "Experimental" in Settings → AI unless the crash/kill/resume flow is tested before the release. _Done: labelled experimental._

## 5. Verification on real hosts (Must)

Things marked "not verified" in STATUS that a first user hits on day one.

- [ ] **Install + service + dashboard + three store apps** on a Raspberry Pi 4/5 with 64-bit Pi OS (or an arm64 Lima VM first), Ubuntu amd64, macOS (Colima) and Windows 11 (Docker in WSL).
- [ ] **Catalog smoke `--all`** with the `Catalog smoke` workflow on amd64 and arm64; fix or mark `smoke: skip` what fails.
- [ ] **Apps with no arm64 image** (improvements.md phase 1: handbrake, logseq, motioneye, petio, pocketbase, ragflow, vocechat, webdav and the rest): set `platforms` to amd64 or switch to a multi-arch image.
- [ ] **Browser checks** (`athena-ui-verify`) of the pages never checked: `/files/smb`, the compose variant picker, the cloud wizard and remote cards with a real rclone remote.
- [ ] **Windows terminal** (ConPTY + PowerShell) and the container shell through Docker in WSL, by hand.
- [ ] **Package managers:** install/uninstall on dnf, pacman and apk in Lima VMs (apt is done); winget and Scoop by hand on Windows. Anything that fails and can't be fixed gets its capability turned off.
- [ ] **Tunnels:** a Cloudflare named tunnel, Tailscale Funnel and ngrok, each once, plus a quick tunnel on Windows.
- [ ] **HTTPS:** Let's Encrypt with a real domain (DNS-01, Cloudflare) once, and trusting the local CA on an iPhone and an Android phone.

## 6. Docs and first impression (Must)

- [ ] **README:** drop "pre-alpha" and "Planned features"; say what 0.1.0 does, supported OSes and CPUs (64-bit only), requirements (RAM, disk, Docker/Colima/WSL), install, upgrade, uninstall (`--uninstall [--purge]`), screenshots of the dashboard, store and assistant, and the full CLI list (`https`, `config`, `restore`).
- [ ] **CONTRIBUTING:** the release section says "install scripts and packages"; it's the wheel, the scripts and `SHA256SUMS`.
- [ ] **Post-release policy in AGENTS.md:** once 0.1.0 is out, data and settings changes need real migrations (Alembic and `athena.json`) instead of "convert the dev data once". Update the rule in the same PR that merges #3.

## 7. Should (in if ready, else 0.1.x)

- [ ] **Update notice:** the server checks the latest GitHub release once a day (a Settings → System switch, on by default, nothing sent but the request) and the UI shows "Athena x.y.z is available" with the upgrade command.
- [ ] **Pi health:** under-voltage and throttling on the dashboard (`vcgencmd get_throttled` or the sysfs file); cache the `nvidia-smi` lookup in `monitor.py`.
- [ ] **Memory on 1 GB boards:** measure RSS on a Pi after the lazy assistant imports (HISTORY); fix the next biggest eager import if it's still over ~200 MB idle.
- [ ] **Own-certificate upload** for HTTPS.
- [ ] **Phone fixes:** the assistant's question card sitting under the plan bar, dashboard touch dragging on a real phone.
- [x] **Vertex AI provider** (`google-vertex` kind: service-account JSON key and location, `GoogleCloudProvider`; models from models.dev).

## 8. Later (0.2.0+)

From `docs/plans/improvements.md` phase 2 and the backlog: 2FA and passkeys, users with roles, app updates (image version checks, one-click update, the "update available" badge), alerts, stats history, disk management, the browser tool (#89, blocked upstream), the rest of M7 D stage 3 (`ipython_code_mode`, `smart_search`, …), Settings → AI notes and skills page, cloud mounts and scheduled syncs, folder uploads and file search, NFS, PyInstaller binaries and native installers, a Docker image of Athena.

## Release checklist

1. Every **Must** item above is ticked and `main` is green on all CI OSes, E2E and CodeQL.
2. Pre-release `0.1.0-rc.1` published; E2E against the published assets passes on all four runners; one by-hand install on a real Pi and a real Windows PC.
3. Upgrade rc.1 → rc.2 with apps and a backup in place; restore still works.
4. README and screenshots updated; STATUS points at 0.2.0.
5. The maintainer merges #3. The release workflow uploads assets and publishes; the post-release E2E passes.
6. Announce (README badge, GitHub release notes edited for humans on top of the generated changelog).

## Decisions (maintainer, 2026-11-21)

1. **Backup is in 0.1.0**, all five parts.
2. **No 2FA in 0.1.0.** The tunnel warning (§7) ships instead; 2FA is the first 0.2.0 item.
3. **A package manager or tunnel that fails §5 and can't be fixed quickly** gets its capability turned off and a line under "Known limitations" in the README; fix in 0.1.x.
4. **A `0.1.0-rc.1` pre-release comes first** (release-please `prerelease: true` and a `Release-As` footer). A pre-release isn't `releases/latest`, so test it with the installers' `--version 0.1.0-rc.1`.
