# Spec: Backup and restore

**Status:** Approved (2026-11-21) · **Milestone:** Backlog (competitor review, `docs/plans/improvements.md` → Phase 2 item 1) · **Design:** `docs/design/backup.md` (new section §4.9)

## Goal

The admin can back up Athena and its apps on a schedule, encrypted and deduplicated, to a local folder or disk or to any rclone remote, and restore them later:

- **See every version** of Athena and of each app (when it was taken, its size, how much was new), on a Backups page and on each app's page, and **restore any version** (a broken update, deleted data).
- **All of Athena** on a new or reinstalled host (dead disk, moving to new hardware), starting from a fresh install's first-run screen.

It also adds **Restart Athena** to the user menu, which a full restore needs and which hand edits to `athena.json` already need.

Today nothing is backed up. Losing the data folder loses every app's data, the settings, the users and the secrets. Cosmos, Umbrel, ZimaOS and Homeio have backups; CasaOS and Runtipi users ask for them.

## Non-goals

- Backing up the host itself: the OS, home folders, or arbitrary folders that no app uses. Athena isn't a general backup tool. Restic or Time Machine already do that job.
- Database-aware dumps (`pg_dump`, `mysqldump`) inside app containers. Stopping the app gives a consistent copy of its files, which is enough for home apps. Dumps can come later as a per-app hook.
- Restoring single files from a version in the first version. The UI shows a version's file list (read-only) and restores the whole version. Restic can still restore single files from the CLI.
- Restoring onto a different OS family (a Linux backup onto Windows). It's best effort with a warning, not guaranteed: bind-mount paths and the runtime differ.
- Replication or sync between two Athena hosts.

## Platforms

New capability `backup`, reported on every host. Backups run the [restic](https://github.com/restic/restic) binary, which exists for every OS and architecture Athena supports. Athena downloads a pinned release into `<data-dir>/bin/` and checks it against a SHA-256 pinned in code, using the shared helper in `athena/downloads.py`, as for lego. A restic already on `PATH` isn't used, so every host runs the same tested version.

- **Local folder or disk:** every OS. The path is validated on the server (absolute, writable, not inside the data folder).
- **rclone remote:** only when the `cloud` capability is ready. Restic's `rclone:` backend runs `rclone serve restic --stdio` with Athena's rclone binary and config file, so every remote the cloud page knows works with no new setup. Without rclone, the destination picker offers local folders only and links to Cloud.
- **Named Docker volumes:** need a ready container runtime. They're read through a short-lived helper container, because on macOS (Colima) and Windows (WSL) the volume files live inside a VM that the host can't read.

## Design

### What a backup contains

A backup plan picks **Athena** (on by default), **User files** (on by default) and any number of **apps**. Each item becomes its own restic snapshot, tagged `athena`, `users` or `app:<name>`, so one app can be restored without the others and retention applies per item.

- **Athena:** a consistent copy of `athena.db` made with SQLite's online backup API (never the live file), plus `athena.json` (the settings file, `settings_file.py`), `secret.key` (which decrypts the `enc:` values in both) and `tls/`. Not included: `athena.json.bak`, `athena.schema.json` (written again at start), `bin/` (downloaded again), logs, caches.
- **User files:** `<data-dir>/users/` as it is (every account's "My files", `users/<id>/files`), snapshotted live without stopping anything. No folder yet means nothing to back up, not a failure. The update's "back up first" step leaves it out (Athena only). Browsable under Versions. **Restore** (`POST /api/backup/restore/users`, admin only, no stop): restic restores into staging, only `<id>/` folders of accounts that still exist are kept (a deleted account's folder stays deleted), then the current `users/` is moved aside to `<data-dir>/users.before-restore-<time>/` (swept after `before_restore_keep_days`). Run it when nobody is uploading. No button in the UI yet.
- **App:** `<data-dir>/apps/<name>/`, meaning `compose.yaml`, `compose.prev.yaml`, `.env` and `data/`. Also:
  - **Named volumes** that the compose file declares: each is streamed as a tar through a helper container (`docker run --rm -v <vol>:/v:ro <helper> tar -C /v -cf - .`) into `restic backup --stdin --stdin-filename volumes/<vol>.tar`. Nothing is staged on disk.
  - **Bind mounts outside the app folder** (`/srv/media:/media`): listed in the plan. The admin opts in to each one, and they're off by default because they're often huge media libraries. Device and socket mounts (`/var/run/docker.sock`, `/dev/...`) are never offered.
- **Consistency:** by default an app is stopped before its snapshot and started again afterwards, one app at a time, so the downtime is that app's backup only. Each app in a plan has a "Back up while running" switch for apps that can't stop. The app is always started again, even when the backup fails, and a failure to start is reported as its own error.

### Destinations and encryption (`athena/backup/repository.py`)

- A **destination** is a restic repository: `{name, kind: "local" | "rclone", path | remote + path}`. Several plans can share one. Adding a destination runs `restic init`, or opens the repository when it already exists, which is how a new host finds old backups.
- Every repository is encrypted with a **password**. Athena generates a strong one, or the admin types their own. It's stored encrypted with `SecretBox`, and it's never returned by the API after creation.
- The password is shown **once** at creation in a "recovery kit" (password, destination, restic version, how to restore with plain restic). The admin has to download or copy it and tick "I saved this" before the destination is created. Without the kit, a dead host means the backups can't be read, because the copy of the password in the DB is encrypted with `secret.key`, which is inside the backup itself.
- The password reaches restic only through the `RESTIC_PASSWORD` environment variable of the child process. It's never on the command line or in logs. The same applies to `RCLONE_CONFIG` and the rclone config password.

### Where the backup settings live

- **Destinations and plans are rows in SQLite** (`backup_destinations`, `backup_plans`), like AI providers and shares: they're relational (plans point at destinations and apps), they hold encrypted secrets, and they carry run state (last run, last error). This follows the `athena.json` spec's split, which keeps that kind of data in the database.
- **Host-wide knobs go in a new `backup` section of `athena.json`** (`BackupSettings` in `athena/backup/settings.py`, loaded through `SettingsFile` like `https`): `paused` (true stops every scheduled run, the escape hatch when a backup misbehaves; editable by hand), `prune_interval_days` (7), `check_interval_days` (30), `before_restore_keep_days` (7) and `default_retention`. No secrets in it.

### Plans, schedule and retention (`athena/backup/service.py`)

- `backup_plans` table: `name`, `destination_id`, `items` (Athena flag, apps with their opt-in bind mounts and the running switch), `schedule` (cron, optional), `retention` (keep last / daily / weekly / monthly; default 7 / 7 / 4 / 6), `enabled`, and the result and error of the last run.
- **Scheduling reuses the automation scheduler loop** (`automation/service.py` `scheduler_loop` and `compute_next_run`). Each run also writes a row to `automation_job_runs`, so the job history stays in one place. There's also a new automation action `backup.run {plan_id}`, so webhooks and n8n can start a backup.
- **A run is one job** (`jobs.py`): for each item in turn, stop the app, snapshot, start it again, then `restic forget --tag <item> --keep-…`. `restic prune` runs at most once a week per destination, and `restic check` (metadata only) runs once a month. Progress comes from `restic backup --json`. A cancelled job still starts every app it stopped.
- Two runs on the same destination never overlap (a per-destination lock). Restic's own lock protects against another restic process.
- Audit entries: `backup.destination.*`, `backup.plan.*`, `backup.run.failed`, `backup.restore`.

### Restore

- **One app** (`POST /api/backup/restore/app`): pick a snapshot, then restore into the same app or into a new name. Restoring into the same app stops it, moves the current folder aside to `apps/<name>.before-restore-<time>/` (deleted after 7 days, or with a button), restores the files and volumes, and starts the app. The restore uses the snapshot's compose file. Volumes are recreated empty and filled through the helper container.
- **All of Athena** (disaster recovery):
  - The first-run screen of a fresh install gets **Restore from a backup**. The admin picks a local folder, or enters an rclone remote's config. Then they enter the repository password from the recovery kit and pick an Athena snapshot.
  - Athena restores the DB, `athena.json`, `secret.key` and `tls/`, restarts itself (see Restart Athena), and logs in with the old accounts. The Backups page then offers to restore every app from the newest snapshots, as one job.
  - The CLI does the same: `athena restore --data-dir … --repo … [--snapshot …]`. It reads the password from a prompt or from `RESTIC_PASSWORD`, and it's the fallback when the UI can't start.
  - The `server` section of the restored `athena.json` is replaced with this host's (host and port were chosen at this install; the old ones may clash), and the HTTPS certificate is reissued by the usual daily check because the addresses changed.
  - The restored DB's schema is upgraded by the usual Alembic migration on start. A snapshot from a **newer** Athena than the one installed is refused, with a message to upgrade first.
- **Cross-OS:** the snapshot records the source OS. Restoring onto a different one shows a warning listing the bind-mount paths that don't exist on this host.

### Restart Athena (user menu)

- **Restart Athena** in the user menu (`nav-user.tsx`), admins only, behind a confirm dialog ("Running jobs are stopped; the page reconnects in a few seconds").
- `POST /api/system/restart` (`restartAthena`), admin, CSRF, audited as `system.restart`. It answers 202, then shuts the server down cleanly (lifespan cleanup: rclone, tunnel client, scheduler).
- **How it comes back, on every OS and with or without a service:** `athena serve` becomes a small supervisor. It runs the server in a child process and starts a new one when the child exits with a dedicated restart code (75), and exits itself on any other code. That doesn't depend on systemd's `Restart=on-failure`, launchd's `KeepAlive` or the Windows scheduled task (which has no restart policy), and it works in a terminal too. The restart re-reads `athena.json`, so hand edits apply.
- The web shows a full-screen "Restarting Athena…" state, polls `GET /api/health` until it answers with a new start time, then reloads the page.
- Used by the full restore, and offered where a change needs a restart (the Settings → System "saved in athena.json" hint).
- No assistant or MCP tool: a restart would cut its own conversation.

### Server routes (`api/backup.py`, admins only)

- `GET/POST /api/backup/destinations` (`listBackupDestinations`, `createBackupDestination`), `DELETE /api/backup/destinations/{id}` (`deleteBackupDestination`; forgets it in Athena and leaves the data in place unless "delete the backups too" is ticked).
- `GET/POST /api/backup/plans`, `PUT/DELETE /api/backup/plans/{id}` (`listBackupPlans`, `createBackupPlan`, `updateBackupPlan`, `deleteBackupPlan`). `POST /api/backup/plans/{id}/run` (`runBackupPlan`) returns a job id.
- `GET /api/backup/versions?destination_id=&item=` (`listBackupVersions`): every version (restic snapshot) of an item or all items: time, size, how much was new, files added/changed/removed against the previous version (`restic diff` stats, cached), the Athena version and the OS.
- `GET /api/backup/versions/{id}/files?path=` (`listBackupVersionFiles`): one folder level of a version (`restic ls --json`), read-only.
- `POST /api/backup/restore/app` (`restoreBackupApp`) returns a job id. `POST /api/backup/restore/athena` (`restoreBackupAthena`) is allowed only before the first user exists (the first-run screen).
- `GET /api/backup/apps/{name}/sources` (`getBackupSources`): the folders, volumes and bind mounts an app would back up, with their sizes when they're cheap to get, for the plan form.

### Web: the Backups page

A **Backups** page in the sidebar (gated by `backup`), with three tabs:

- **Versions:** every version, newest first, filterable by item (Athena or an app) and destination. Each row shows the time, the plan, size and new data, files changed, and the actions **View files** (a read-only folder browser using the Files page's list components) and **Restore** (a dialog: same app or a new name, what will be replaced, the "moved aside to" folder). A version from another OS shows the cross-OS warning in the dialog.
- **Destinations:** a list with free space where it's known, plus Add (local path with the folder picker, or an rclone remote from the cloud list), and the recovery-kit step.
- **Plans:** cards with the schedule, last run (ok / failed with the error) and next run, plus Run now (opens the job log), Edit and Delete. The plan form has the destination, Athena, app checkboxes with their bind mounts and the running switch, the schedule (presets: daily 03:00, weekly; or cron), and retention.
- **Each app's page** (`/apps/view`) gets a **Backups** tab: that app's versions with Restore and View files (the same components, filtered to `app:<name>`), "Back up now" when a plan includes it, and "Add to a plan" when none does.
- Dashboard: the "remote access" style card pattern gets a **Backups** card showing the last run per plan and failures. It's optional and comes in the last part.
- Gated by the `backup` capability. rclone destinations are hidden without `cloud`, and named volumes are hidden without a container runtime.

### Assistant / MCP

- `backup_status` (read-only: plans, last runs, newest snapshots): no approval.
- `run_backup_plan`: **needs approval** (it stops apps).
- No restore tool: a mistake overwrites live data. Restores stay in the UI and the CLI.

### Security

- Admin-only routes, CSRF on writes. Repository passwords and rclone secrets are encrypted at rest, write-only through the API, and passed to restic only through its environment.
- Local paths are validated: absolute, not inside `<data-dir>` (a backup of itself), and not a system folder.
- Restores write only inside `<data-dir>/apps/<name>/` and the app's own volumes. Restic's restore target is a staging folder under the data dir, and files are moved into place only after the checks pass. Bind-mount paths from a snapshot are restored only when the admin ticks each one.
- The helper container is a pinned, digest-referenced small image (busybox), run with `--network none`, read-only volumes for backups, and no other mounts.
- Logs and job output never include passwords. Restic's JSON output carries file paths but no contents.

### Dependencies

- restic (BSD-2-Clause), downloaded at runtime and recorded in `docs/design/licenses.md`.
- busybox image (GPL-2.0, used unmodified as a separate program in a container), recorded the same way.
- No new Python packages: `sqlite3` backup API, `croniter`, `downloads.py` and the job system already exist.

## Parts

1. **Restart Athena.** The `athena serve` supervisor, `POST /api/system/restart`, the user-menu item with its confirm dialog and reconnect screen. Tests: the supervisor restarts on code 75 and exits on others (Linux, macOS and Windows in CI), the route is admin-only and audited. Verified with `athena-ui-verify`, and under the service with `athena-host-test` (systemd and the Windows task).
2. **Server: destinations, Athena and app-folder backups, restore one app.** `athena/backup/`, the restic download, migration (`backup_destinations`, `backup_plans`), local and rclone repositories, the password and recovery kit, plans with manual runs, stop/start around snapshots, retention, prune and check, the `backup` section of `athena.json`, listing versions and their files, restoring one app (same name or new), routes, the `backup` capability, audit, and `pnpm gen:api`. Tests: snapshot contents for a fake app against a real restic in a temp folder (restic is a single binary; CI downloads it), the password never in argv or logs, apps started again after a failure or cancellation, and path validation.
3. **Web: the Backups page and the app's Backups tab.** Versions (with View files and Restore), destinations with the recovery-kit step, plans, run now with the job log. Verified with `athena-ui-verify` using a local destination and an `athena-test-*` app.
4. **Volumes, bind mounts, schedule and automation.** Named volumes through the helper container, opt-in bind mounts, the cron schedule on the shared scheduler, the `backup.run` automation action, the `backup_status` / `run_backup_plan` tools, and the dashboard card.
5. **Disaster recovery and real hosts.** Restore from the first-run screen and `athena restore`, the schema version check, the cross-OS warning, the design section and decision row, gotchas, `athena-host-test`: a full back up, wipe and restore on a Linux VM, plus the Windows E2E workflow.

## Acceptance checks

- A plan with Athena and an `athena-test-*` app backs up to a local folder. `restic snapshots` with the recovery-kit password lists both, and running it again adds almost nothing (dedup).
- Deleting a file in the app's `data/` and restoring the snapshot brings it back. The app is running afterwards, and the old folder sits in `*.before-restore-*`.
- Killing the backup mid-run (cancelling the job) leaves the app running and the repository usable (`restic check` passes).
- A named volume's contents survive a backup, `docker volume rm` and a restore, on Linux and on macOS (Colima).
- Disaster recovery: back up, delete the data folder, run a fresh install, restore from the first-run screen, and log in with the old account. Every app comes back with its data.
- An rclone destination (a `local` rclone remote in tests, a real cloud remote by hand) works the same as a folder.
- The password never appears in `ps` output, the job log, the server log or any API response after creation.
- The Versions tab and the app's Backups tab list every version with correct sizes. Restoring an older version (not the newest) gives that version's files.
- Restart Athena from the user menu: the page reconnects by itself, `athena.json` hand edits apply, and it works under systemd, launchd and the Windows task.
- Setting `backup.paused` in `athena.json` and restarting stops scheduled runs; an invalid `backup` section refuses startup like any other section.
- Retention keeps the configured number of snapshots per item, and prune runs only weekly.
- Server tests run on Linux, macOS and Windows in CI. Volume tests need Docker and run only on Linux CI.

## Decisions (2026-11-21)

- restic as the engine (encryption, dedup, versions, retention; reaches every rclone remote).
- Apps are stopped during their backup by default, one at a time; a per-app switch opts out.
- Athena keeps the repository password encrypted for scheduled runs; the admin must save a recovery kit when a destination is created.
- Versions are visible and restorable from the Backups page and each app's page; single-file restore is a follow-up.
- Bind mounts outside the app folder are off by default, opted in per path.
- New plans default to daily at 03:00 with 7 daily / 4 weekly / 6 monthly.
- A missing local destination (unplugged USB disk) skips the run with "destination not connected".
- Restart Athena goes in the user menu, through a supervisor in `athena serve`.
- Destinations and plans live in SQLite; host-wide backup knobs in `athena.json` → `backup`.
- **Disaster recovery refuses a newer Athena version.** A snapshot tagged with an `athena-version` newer than the installed version is rejected with a message to upgrade first. This prevents a broken restore where the DB schema is ahead of the code.
- **The `server` section of `athena.json` is replaced on full restore.** The old host/port may clash with the new install; the current host's settings are kept so Athena starts on the expected address. The HTTPS certificate is reissued by the daily check (or manually with `athena https status`).
- **Cross-OS restores warn about bind mounts.** If the backup's `os:` tag differs from the current host, the job logs a warning listing the bind-mount paths that may not exist.

## Gotchas

- **The recovery kit is essential.** Without it, a dead host means unreadable backups because the repository password is encrypted with `secret.key`, which is inside the backup itself. The kit is shown once at destination creation and must be saved externally.
- **Full restore replaces `athena.json`'s `server` section.** Hand-edited host/port settings from the backup are discarded in favour of the new host's settings. Other sections (`system`, `https`, `ai`, `webdav`, `backup`) are kept from the backup.
- **Alembic migrations run on the first start after restore.** If the restored DB is from an older Athena, migrations upgrade it. If it's from a newer Athena (which is blocked), the server would fail to start.
- **Cross-OS bind mounts are not rewritten.** A backup from Linux with `/srv/media:/media` will restore that path on macOS or Windows, where it likely doesn't exist. The app will fail to start until the bind mount is edited or removed.
- **The `athena restore` CLI requires an existing data dir with `athena.db`.** It's designed for the first-run fallback where the install created a fresh data dir. To restore onto a truly empty host, run the installer first (it creates the data dir and DB), then run `athena restore`.
- **Restic's `--host` is fixed to `athena`.** This ensures a snapshot's parent is found after the host is renamed or the data is restored onto new hardware. Changing it would break incremental backups after a restore.
