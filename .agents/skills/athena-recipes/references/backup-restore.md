# Backup & restore recipes

## Schema version check on full restore

In `restore_athena()`:

```python
# Read the snapshot's tags
result = await tool.run_ok(repo, "snapshots", "--json", version_id)
snap = json.loads(result.stdout or "[]")[0]
tags = [t for t in snap["tags"] if isinstance(t, str)]
backup_version = versions._tag_value(tags, "athena-version:")
backup_os = versions._tag_value(tags, "os:")

# Refuse if backup is newer than installed version
if backup_version:
    current_key = version_key(__version__)
    backup_key = version_key(backup_version)
    if current_key is not None and backup_key is not None and backup_key > current_key:
        raise ResticError(
            f"This backup was made by Athena {backup_version}, which is newer than "
            f"the installed version ({__version__}). Upgrade Athena first, then restore."
        )
```

Use `athena.updates.version_key()` (PEP 440 aware) for comparison.

## Cross-OS warning

```python
current_os = platform.system().lower()
if backup_os and backup_os != current_os:
    await job.log(
        f"warning: this backup was taken on {backup_os}, but this host is {current_os}. "
        "Bind-mount paths in the restored apps may not exist on this host."
    )
```

## Replace server section in athena.json

After restoring the data folder, replace the `server` section with the current host's settings:

```python
restored_settings = (data_dir / SETTINGS_FILE).read_text(encoding="utf-8")
restored = json.loads(restored_settings)
current_settings = (aside / SETTINGS_FILE).read_text(encoding="utf-8")
current = json.loads(current_settings)
if "server" in current:
    restored["server"] = current["server"]
    (data_dir / SETTINGS_FILE).write_text(
        json.dumps(restored, indent=2, ensure_ascii=False), encoding="utf-8"
    )
```

This prevents host/port clashes after restore. The HTTPS certificate is reissued by the daily check (or manually with `athena https status`).

## CLI snapshot listing with version/OS tags

In `athena restore`:

```python
found = await versions.list_versions(tool, repo, "athena")
print("Available Athena snapshots:")
for v in found:
    ver = f" (Athena {v.athena_version})" if v.athena_version else ""
    os_info = f" [{v.os}]" if v.os else ""
    print(f"  {v.id[:8]}  {v.time}{ver}{os_info}")
```

## Restic tags for snapshots

Each snapshot gets tags:
- `athena` or `app:<name>` (item tag)
- `athena-version:<version>` (from `athena.__version__`)
- `os:<linux|darwin|windows>` (from `platform.system().lower()`)
- Fixed host: `athena` (so parent snapshots are found after hostname change or restore to new hardware)

```python
def snapshot_tags(*tags: str) -> list[str]:
    tags = (*tags, f"athena-version:{__version__}", f"os:{platform.system().lower()}")
    return [arg for tag in tags for arg in ("--tag", tag)]
```

## Recovery kit

- Generated once at destination creation: password, destination, restic version, restore instructions
- Shown once; admin must tick "I saved this"
- Without it, a dead host = unreadable backups (password encrypted with `secret.key` which is inside the backup)

## Full restore flow

1. First-run screen → "Restore from a backup" → enters repo location, password, picks snapshot
2. Calls `POST /api/backup/restore/athena` → job runs `restore_athena()`
3. Stages snapshot, validates, stops server via `restart.request()` (supervisor restarts)
4. Moves current data dir aside, moves restored data in place
5. Replaces `server` section in `athena.json`
6. Server restarts, runs Alembic migrations
7. CLI fallback: `athena restore --data-dir … --repo … [--snapshot …]`

## Gotchas

| Pitfall | Rule |
|---|---|
| Backup from newer Athena | Refuse with clear upgrade message; prevents broken DB schema |
| Cross-OS bind mounts | Warn only; don't rewrite paths; app may fail to start until admin edits bind mounts |
| `server` section in `athena.json` | Always replace with current host's settings on full restore |
| Recovery kit | Essential — without it, backups are unreadable after host loss |
| `athena restore` CLI | Requires existing data dir with `athena.db` (installer creates it first) |
| Restic `--host` | Fixed to `athena` — changing it breaks incremental backups after restore |
| Alembic migrations | Run automatically on first start after restore; older DB → upgraded, newer DB → blocked by version check |
| HTTPS certificate | Reissued by daily check after `server` section replacement changes host/port |

## Acceptance checks

- Restore from first-run screen works on fresh install
- `athena restore` CLI works with and without `--snapshot`
- Newer-version backup refused with actionable message
- Cross-OS backup shows warning in job log
- `server` section replaced, Athena starts on correct host/port
- HTTPS certificate reissued automatically
- Password never appears in logs, argv, or API responses after creation
- All versions listed with correct sizes; restoring older version gives that version's files
- Restart Athena from user menu works under systemd, launchd, Windows task
- `backup.paused` in `athena.json` stops scheduled runs
- Retention keeps configured snapshots per item; prune runs weekly
- Server tests pass on Linux, macOS, Windows in CI
- Volume tests (need Docker) run on Linux CI only

## Related specs

- `docs/specs/backup.md` (Part 5: Disaster recovery and real hosts)
- `docs/design/backup.md` (section §4.9)
- `docs/plans/release-0.1.0.md` (Must items for backup)

## Files to touch

| Area | Files |
|---|---|
| Restore logic | `apps/server/src/athena/backup/restore.py` |
| CLI | `apps/server/src/athena/cli.py` (`_restore` function) |
| Snapshot tags | `apps/server/src/athena/backup/snapshots.py` (`snapshot_tags`) |
| Version parsing | `apps/server/src/athena/backup/versions.py` (`parse_versions`) |
| Version comparison | `apps/server/src/athena/updates.py` (`version_key`) |
| First-run UI | `apps/web/app/(auth)/setup/page.tsx` (`restore` step) |
| Spec | `docs/specs/backup.md` (Decisions, Gotchas for Part 5) |
| Tests | `apps/server/tests/test_backup_restore.py` |