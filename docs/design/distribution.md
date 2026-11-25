# 8. Distribution (MVP)

- **Dev:** `pnpm dev` (Next on :3000, proxying `/api` to :8420) plus `uv run athena --reload`.
- **Release:** release-please tags a version from Conventional Commit PR titles. The release workflow then:
  1. builds the web app and copies `out/` into the Python package;
  2. builds the `athena_server-<version>-py3-none-any.whl` wheel;
  3. attaches the wheel and the install scripts to the GitHub release.
- **One-line install, CasaOS-style:**
  - Linux/macOS: `curl -fsSL https://github.com/Promethean-Works/athena/releases/latest/download/install.sh | bash`. It needs `sudo` on Linux.
  - Windows: `irm …/install.ps1 | iex`.
  - The scripts install the runtime where the decisions allow it (Docker Engine on Linux, Colima on macOS; Windows is detect only), plus uv and the wheel through `uv tool install`, in Athena-owned directories.
  - They support `--version`, `--dry-run`, `--no-runtime`, and `--uninstall [--purge]`, plus `--wheel <path|url>` (`-Wheel` on Windows) to install an unreleased build from `scripts/build-wheel.sh`.
- **End-to-end check:** the `E2E` workflow builds the wheel from the commit and runs the real installers on Ubuntu, macOS and Windows runners. It checks the service starts, runs `scripts/e2e/smoke.py` (Playwright: setup, sign-in, every page, the host terminal, phone width and dark mode), then uninstalls with `--purge` and checks that nothing is left. Locally, the same steps run in a Lima VM (see CONTRIBUTING).
- **Service install:** `athena service install --data-dir [--port]` registers a systemd unit on Linux, a launchd agent on macOS, or a Scheduled Task at logon on Windows. The unit has no `--port`: `--port` is saved as `server.port` in `<data-dir>/athena.json`, so a hand edit plus a restart changes it.
- **Update notice:** `athena/updates.py` asks GitHub's `releases/latest` (never prereleases or drafts) at start and then daily, and `GET /api/system/update` serves the remembered answer, so the UI (`UpdateNotice` in the app shell) never waits on the network. The request is a bare GET with a generic User-Agent: no version, host or settings. Admins switch it off with `update_check` (Settings → System; audited); an empty `ATHENA_UPDATE_CHECK_URL` disables it too. Offline hosts retry hourly and show nothing. Upgrading is re-running the installer, which the notice shows as a copyable command.
- **Self-update:** `self_update.py`, `update_helper.py`, `update_launch.py` (spec `docs/specs/self-update.md`). The `self_update` capability is ready for `uv tool` installs run by the service; the UI (**Update now**, Settings → System) and `athena update` download the release, check it against `SHA256SUMS`, save the database and settings, then a detached helper stops Athena, installs offline, starts it, checks `/api/health` and goes back to the old wheel on failure. Progress lives in `<data-dir>/updates/state.json` because the server is down mid-swap; the new server audits the outcome. In the UI, **Back up Athena first** runs just Athena's item of the first enabled backup plan that includes it (a failure offers "Update anyway"); an update whose helper vanished shows as `interrupted` (warning banner). `athena update` has no backup step yet.
- **Later:** single-file binaries (PyInstaller/Nuitka) and native installers.
