# Spec: Self-update

**Status:** Draft · **Milestone:** Backlog (after the 0.1.0 release: the update notice, release plan §7) · **Design:** `docs/design/distribution.md` (new bullet)

## Goal

The admin updates Athena with one click (**Update Athena** in Settings → System and on the update notice) or with `athena update` in a terminal, instead of re-running the installer. Athena downloads the release, checks it, swaps itself, restarts, and goes back to the old version when the new one doesn't come up. Apps keep running the whole time (their containers don't depend on the server).

## Non-goals

- Updating the container runtime, Docker, rclone, restic or lego (Athena downloads those itself, pinned per release).
- Silent or scheduled updates. The admin always asks for one; the notice only announces.
- Installs that aren't `uv tool` installs (pip, a source checkout, Docker). They keep their own way of upgrading, and the UI says so.
- A signed-update framework (TUF). Verification is the release's `SHA256SUMS`, as in the installers (#226); signing is an open question.
- Downgrades through the UI.

## Platforms

New capability `self_update`, in the manifest like the others. It is **ready** when all of these hold, and otherwise carries a reason that the UI shows instead of the button:

- Athena runs from a `uv tool` environment (the tool dir has `uv-receipt.toml` for `athena-server`, and `sys.executable` is inside it) and `uv` is found (the receipt's location, `PATH`, then `~/.local/bin`, `%USERPROFILE%\.local\bin`, Homebrew; launchd's `PATH` is minimal).
- The process is the one the installed service runs (systemd unit active with our PID in its cgroup; `launchctl print` shows it; the Windows task's `pythonw.exe`). Without it, the **CLI** still works but ends with "restart Athena yourself", and the UI button is hidden ("Athena was started from a terminal").
- The data dir and the tool dir are writable by the server's user (the systemd service runs as root, launchd and the task as the user, as the installers set them up).

Per OS, the swap uses what `athena service install` already does (`service/platforms.py`): systemd `stop`/`restart`, launchd `bootout` (with its wait) plus `bootstrap`, the Windows `schtasks /End` plus `WINDOWS_STOP_SERVER` plus `/Run`. Nothing branches on `sys.platform` in a router.

## Design

### Finding the release (reuses the update notice)

Depends on `feat/update-notice` (`athena/updates.py`: `UpdateChecker`, `UpdateInfo`, `GET /api/system/update`, `update_check_url`, the `update_check` switch). Not on `main` yet; part 1 below waits for it. Self-update **does not repeat the daily check**:

- The button is shown when `UpdateInfo.available` is true; `latest` and `release_url` come from it. The notice's copyable installer command stays as the fallback for hosts where `self_update` isn't ready.
- It needs one thing the notice doesn't do: asset URLs. A new `updates.resolve(tag)` asks `releases/tags/v<ver>` (or `releases/latest`) when the admin starts an update, finds `athena_server-<ver>-py3-none-any.whl` and `SHA256SUMS` among the assets, and returns their URLs. It reuses the notice's `fetch_json`, User-Agent and `update_check_url` setting (so forks and tests redirect both). If the daily check is switched off, an explicit update still works: the switch only controls the background request.
- The repository is a server setting, never a request field.

### Who does the swap: a helper that outlives the server

The server can't replace itself: it runs from the venv being replaced (Windows locks the files; the supervisor from #215 and its child both live there) and the service manager kills its whole process tree when it stops it. So the work in the swap window is done by a **helper**:

- `athena/update_helper.py`, **standard library only**, shipped in the wheel. Before every update it is **copied** to `<data-dir>/updates/run/` and started with `-I` by the **base** interpreter that uv uses (`uv python find 3.13`, not the venv's `python.exe`, which is a launcher that holds the venv). Nothing it runs is inside the tool venv.
- The helper is dumb. `athena` writes `<data-dir>/updates/plan.json` and the helper only runs it: the argv lists for stop, install, start (built by `service/platforms.py` as new `build_stop` / `build_start` plans, so the per-OS logic stays in one tested place), the health URL, the expected version, the rollback steps, and where to write `state.json`. It never imports `athena`.
- **The CLI uses the same helper**, in the foreground: `athena update` prepares, then runs the helper and prints its progress. One engine, one set of tests. (`athena.exe` can't replace itself on Windows either.)

### The sequence

All of 1–5 run **while the old version still serves**, so a failure there costs nothing:

1. **Resolve** the release (above). Refuse a version that isn't newer (`--allow-downgrade` on the CLI only, with a warning that migrations don't go back).
2. **Download** the wheel and `SHA256SUMS` to `<data-dir>/updates/<ver>/` (HTTPS only; hosts limited to `github.com` and GitHub's release CDN, including redirects; size cap; a temp file renamed when complete), using the shared helper in `athena/downloads.py`. **Verify** the wheel against its `SHA256SUMS` entry; a missing entry or a mismatch aborts and deletes the files ("refusing to install an unverified wheel", the installers' wording).
3. **Pre-flight the new wheel:** `uv tool run --python 3.13 --from <wheel> athena --version` and `athena config check`. That downloads its dependencies into uv's cache (so the swap can run with `--offline`: no network failure in the dangerous window) and proves it imports.
4. **Prepare rollback:** copy the current `athena.db` with SQLite's online backup API to `updates/pre-<old>/athena.db` (always, a few MB), plus `athena.json` and `secret.key`. Fetch the **current** version's wheel and `SHA256SUMS` the same way (verified) into `updates/previous/`. A source or unreleased build has no release to go back to: the CLI refuses unless `--no-rollback`, and the UI hides the button (capability reason).
5. **Optional backup:** with the `backup` capability ready and a plan that includes Athena, the dialog offers "Back up Athena first" (default on) and runs that plan's Athena item as a job, waiting for it (see Backup). Skipped without a plan.

Then the swap, in the helper:

6. **Stop** the service (per OS, as above) and wait until the port is free.
7. `uv tool install --force --offline --python 3.13 <wheel>`. The venv path is unchanged, so the service file stays valid.
8. **Start**: `athena service install --data-dir <dir>` from the new venv (rewrites the unit/plist/task for the new version and restarts, which `docs/agents/gotchas/installers.md` says it does on every OS). Migrations run on start as always.
9. **Health check:** poll `GET /api/health` on the port from `athena.json` for up to 90 s (migrations on a big DB can take a while) until it answers with the **new** version and a new `started_at`. Success: write `state.json` `done`, delete `previous/` after 7 days, keep the last two `<ver>/` folders.

**Rollback** when the install fails or the health check times out or answers the wrong version: stop the service, restore the saved `athena.db` (the new version may have migrated it forward, and an old server refuses a newer schema), `athena.json` and `secret.key`, `uv tool install --force --offline <previous wheel>`, start, health check again. `state.json` ends as `rolled_back` with the reason and the last log lines, or `failed` when even the old version doesn't come up (then the log says to run the installer one-liner; the helper never leaves the service stopped without trying to start something). Writes made between the stop and the failed start are none, because the server was stopped, so restoring the DB loses nothing.

### How the helper outlives the server (per OS)

The server starts the helper, answers 202, then stops itself like Restart Athena (`restart.py`) except it asks the supervisor to **exit** rather than restart. Starting it detached is the part that breaks:

- **Linux:** `systemctl stop` kills the whole cgroup, including a child with its own session. The helper starts as a transient unit: `systemd-run --unit athena-update --collect --quiet <python> -I helper.py plan.json` (the service runs as root, so that's allowed). Fallback `setsid` only when `systemd-run` is missing (then not under systemd, and the capability wouldn't be ready anyway).
- **macOS:** `start_new_session=True` should leave launchd's process group, which `bootout` signals. Verified on a real Mac in part 2; the fallback is a one-shot `launchctl submit -l io.github.tiagozaccaro.athena-update` job.
- **Windows:** the logon task runs `pythonw.exe` with no console and possibly invalid standard handles (the `WinError 6` lessons in `docs/agents/gotchas/windows.md`). The helper is started with `stdin`, `stdout` and `stderr` **all explicitly** `DEVNULL` (its output goes to `logs/update.log` by its own file handle), `close_fds=True` (no inherited handles: an inherited socket or the supervisor's pipe would also keep the port or the venv busy), and `creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`. The task's job object can kill children on `/End`, and `CREATE_BREAKAWAY_FROM_JOB` is refused if the job doesn't allow it, so the **primary** way is a one-shot scheduled task (`schtasks /Create /TN AthenaUpdate /SC ONCE … /RL LIMITED` then `/Run`, deleted by the helper at the end), which belongs to the Task Scheduler and not to our tree. Part 2 tries both on a real Windows host and keeps the one that survives `WINDOWS_STOP_SERVER` (which kills every `pythonw.exe` with `-m athena serve`; the helper's command line must not match it).
- The helper never touches a console, ConPTY or the terminal module, so it needs no keep-a-console trick; the E2E runs it under `pythonw`.

Concurrency: one update at a time (`updates/lock` with the helper's PID; a stale lock from a dead PID is ignored). A crash of the helper between stop and start can't be undone by itself, so the **next server start** reads `state.json`; a `phase` that isn't `done`, `rolled_back` or `failed` shows "An update was interrupted" with the log, and the installer one-liner.

### Pre-releases and versions

- `athena update --version 0.2.0-rc.1` (and `--pre` for the newest pre-release) resolves `releases/tags/v0.2.0-rc.1` and maps the tag to the wheel's PEP 440 name (`0.2.0rc1`). The daily check and the UI button never offer pre-releases (the notice already ignores them).
- No pre-release channel in the UI in the first version; the CLI flag is the escape hatch. A pre-release host still gets the stable notice when a newer stable exists.
- The version string is validated (`^\d+\.\d+\.\d+([-.]?(a|b|rc)\.?\d+)?$`) and then looked up as a release, so it never reaches a URL or argv unchecked.

### Backup before the update

Optional until the backup feature (`docs/specs/backup.md`) ships and is used. Part 4 adds "Back up Athena first" when `backup` is ready and some plan includes Athena: it starts that plan's Athena item and waits (failure asks "update anyway?" in the UI, `--yes` on the CLI continues, `--no-backup` skips). The always-on pre-update copy of the DB, `athena.json` and `secret.key` (step 4) is separate and doesn't need the feature: it exists so rollback works, not as a backup.

### Progress and failure reporting

The server dies in the middle, so progress can't be a server job. It lives in `<data-dir>/updates/state.json` (`phase`, `step`, `from`, `to`, `started_at`, `error`, `log_tail`), written atomically by the helper, plus `logs/update.log`.

- Steps 1–5 run as a normal job in the server (download progress, checksum, pre-flight, optional backup), so the dialog shows a progress bar and can cancel.
- `GET /api/system/update/status` (`getUpdateStatus`, admin) returns `state.json` (or idle). The **Updating Athena** dialog, in the same full-screen style as Restart Athena, lists the steps with a check mark per step and polls `/api/health`; while the server is down it shows "Restarting…", and when it's back it reads the status once to say "Updated to 0.2.0" and reloads, or "Update to 0.2.0 failed, still on 0.1.4: <reason>" with the log in a collapsible block and the copy button. A rolled-back state shows as a warning, not a success, and the notice stays so the admin can retry.
- The CLI prints the same steps and ends with the exit code: 0 updated or already current, 1 failed before the swap, 2 rolled back, 3 failed and not running.
- Audit: `system.update.start` (from → to, `via: ui|cli`), `system.update.done`, `system.update.rolled_back`. The finished/rolled-back entries are written by the new server on start, from `state.json`, because the old one is gone.

### Server and CLI surface

- `POST /api/system/update` (`startUpdate`, admin, CSRF) `{version?}`: 202 with a job id for steps 1–5, then the server hands over and shuts down. 409 when one is running, 422 with the capability's reason when not ready. `GET /api/system/update/status` (`getUpdateStatus`).
- `athena update [--check] [--version V] [--pre] [--yes] [--dry-run] [--no-backup] [--no-rollback] [--allow-downgrade] [--data-dir D]`. `--check` prints current, latest and whether the host can self-update (works without a server, using the same `updates` code). `--dry-run` prints the plan (the argv lists) like `athena service install --dry-run`.
- `self_update` capability in `platform/` (probe never raises, as for the other capabilities).

### Web

- The update notice (from the notice PR) gets **Update now** when `self_update` is ready, else keeps the copyable command with the reason. Settings → System has an **Updates** card: current and latest version, "Check now" is not added (the daily check is enough; the card shows the last check time), Update button.
- Confirm dialog: from → to, release notes link, a list of running jobs and open terminals that will be stopped ("apps keep running"), the "Back up first" switch when available. Phone width and dark mode as everywhere (`athena-ui-verify`).

### Security

- Admin only, CSRF, audited. The request carries at most a version string; the repository, hosts and file names are fixed by the server.
- **No unverified code runs:** the wheel is checked against `SHA256SUMS` before anything is stopped or installed, and the helper re-checks the file's hash right before `uv tool install` (a swap between check and use). `SHA256SUMS` comes from the same release as the wheel, so it detects corruption and a bad mirror but not a compromised release; that is the same trust as the installers. Stronger checks (GitHub artifact attestations, `gh attestation verify`-style) are an open question, not a silent gap.
- `uv` resolves the wheel's dependencies from PyPI, as the installers do (`uv tool install`). Pre-flight (step 3) exercises that before the stop.
- **Tunnel exposure:** the route is as exposed as the rest of the admin API. A hijacked admin session can already use the terminal and the shell, and an update only installs a checked official release, so it adds no new power; but it can interrupt service, so it asks the same confirm as Restart Athena and is rate limited to one start per minute. No assistant or MCP tool (it would cut its own conversation, like restart); the assistant may read `GET /api/system/update` through an existing read-only status tool.
- The helper and `plan.json` live in `<data-dir>/updates/` with the data dir's permissions (0700 on POSIX); `plan.json` is written by the server and contains no secrets.
- Logs never include tokens. The release request sends no version or host info (same as the notice).

### Dependencies

None new. `uv` (Apache-2.0/MIT) is already required by the installers.

## Parts

1. **Core, CLI-first** (waits for `feat/update-notice` to merge): `updates.resolve`, download and verify, `build_stop`/`build_start`, `update_helper.py`, plan and state files, `athena update` (`--check`, `--dry-run`, `--version`, rollback). Verified with unit tests plus a Lima VM and the CI E2E on three OSes against a local fake release.
2. **Detached start from the server per OS:** `systemd-run`, macOS session or `launchctl submit`, Windows one-shot task vs `DETACHED_PROCESS`; the exit-not-restart path in `restart.py`. Verified on real hosts (this is the risky part, so it ships before any UI).
3. **API, capability and UI:** `self_update` capability, `startUpdate`/`getUpdateStatus`, the notice button, Settings card, progress dialog, audit entries, `pnpm gen:api`. Verified in a browser and E2E smoke.
4. **Backup integration and polish** (after the backup feature): "Back up first", interrupted-update banner, docs move to `docs/design/distribution.md` plus a decisions row, spec marked Done.

## Acceptance checks

- **Unit tests:** version parsing and pre-release mapping; checksum match, mismatch, missing entry (nothing installed, files deleted); plans per OS (`build_stop`/`build_start`, like the existing service plan tests, built on any OS); capability gating with `FakeProbe` (pip install, no uv, terminal-started, no rollback wheel); the helper in-process with fake commands and a fake health server: success, install failure, health timeout, wrong version (each rolls back, DB restored byte for byte), rollback failure (`failed`, still tries to start); API: admin only, CSRF, 409, 422 reason, version validation, no URL in the body.
- **E2E workflow (all three runners):** build wheel A, and wheel B with a bumped version; serve a fake release (wheel, `SHA256SUMS`, JSON for `releases/latest`) from a local HTTP server through `ATHENA_UPDATE_CHECK_URL`; install A with the installer's `--wheel`; create data (admin, an app folder); run `athena update`; assert the server answers as B on the same port, data intact, service file rewritten, no leftover helper or `AthenaUpdate` task. Then a **bad** wheel C (server exits at start; a sentinel in the build) and a wheel with a wrong checksum: assert rollback to B with the original DB, and that the checksum case never stops the service. Then the **UI route** under the real service (`pythonw.exe` on Windows) driven by `scripts/e2e/smoke.py`: the helper survives the stop, the page shows the success state.
- **`athena-host-test`:** a Lima Ubuntu VM (systemd, `systemd-run`, cgroup kill) and Fedora, and a macOS host for launchd (session escape vs `launchctl submit`). Windows: the E2E run plus a manual `schtasks /Query` and process check that no `athena-update` helper survives and the handle lessons hold (`WinError 6` never appears in `logs/update.log` or `athena.log`).
- **Browser (`athena-ui-verify`):** notice, confirm dialog with running jobs listed, progress states, rolled-back state, hidden button with the reason on a non-uv install, phone width, dark mode, console clean.
- **Failure cases by hand:** unplug network after pre-flight (install uses `--offline`, must still succeed); kill the helper mid-install (next start shows "interrupted"); full disk at download (nothing stopped).

## Open questions

- **Where does rollback get the old wheel?** Recommendation: download the current version's release wheel (verified) in pre-flight. Costs one extra download (tens of MB) but works for every released install; unreleased builds can't self-update. The alternative (copying uv's cache) isn't a stable interface.
- **Signature or attestation checks beyond `SHA256SUMS`?** Recommendation: not in the first version (parity with the installers); add GitHub artifact attestations to the release workflow and verify them in both the installers and the updater as one later change.
- **UI pre-release channel?** Recommendation: CLI `--version`/`--pre` only for now; revisit when there is a real pre-release audience.
- **Windows helper start: one-shot scheduled task or `DETACHED_PROCESS`?** Recommendation: the one-shot task (it can't be killed with the service's tree, and it needs no handle inheritance); part 2 confirms on a real host before committing.
- **Require the admin's password again to start an update?** Recommendation: no, the confirm dialog is enough (the terminal gives the same power, and the update installs only verified releases).
- **Hosts started from a terminal (no service):** hide the UI button, or let the helper start `athena serve` detached afterwards? Recommendation: hide it; `athena service install` is the supported way, and the CLI tells the user to restart.
- **Show the update in the UI during a running backup or transfer?** Recommendation: allow, but list the running jobs in the confirm dialog and stop them (they stop on restart anyway); don't add a "wait until idle" mode yet.
