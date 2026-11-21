# Spec: settings in a JSON file

**Status:** Done (#204, #209, #210) · **Milestone:** none (infrastructure) · **Design:** `docs/design/backend.md`, `docs/design/security.md`

## Goal

Athena's settings live in one hand-editable file, `<data-dir>/athena.json`, instead of rows in SQLite. If a setting stops Athena from starting or locks the admin out (a bad port, broken HTTPS, a bad tunnel or MCP setting), they open the file in any editor, fix the value and restart. Today that needs SQL or a dedicated command such as `athena https off`, and the server's own host and port can only be set through environment variables, which a system service doesn't see.

## Non-goals

- Moving relational data out of the database: users, sessions, audit log, apps, catalogs, file locations, shares, SMB shares, AI providers (with their API keys), integrations, conversations and caches stay in SQLite.
- Live reload of hand edits. They apply on the next restart. Saves from the UI still apply right away, as they do now.
- Upgrade code. Athena hasn't been released, so there's no import from the old `system_settings` rows. The one existing development database is converted once by hand, and the rows are deleted.
- Comments in the file (JSON has none). The JSON schema gives descriptions in editors instead.

## Platforms

The same on Linux, macOS and Windows; no capability. The file lives in the data dir (`/var/lib/athena`, `~/Library/Application Support/Athena`, `%LOCALAPPDATA%\Athena\data`), so backing up that one folder backs up everything. On POSIX the file is mode 0600. That's a no-op on Windows, where the data dir is already per-user.

## Design

### The file

```json
{
  "$schema": "./athena.schema.json",
  "server": { "host": "0.0.0.0", "port": 8420, "feedback_repo": "...", "durable_execution_database_url": null },
  "system": { "terminal_enabled": true, "tunnel_enabled": false, "tunnel_config": {}, ... },
  "https":  { "mode": "off", "port": 8443, "redirect": true, "letsencrypt": { ... } },
  "ai":     { "default_model": null, "shell_enabled": false, "mcp_servers": [], ... },
  "webdav": { "enabled": false, "username": null, "password_hash": null }
}
```

- One section per settings model. The models stay as they are: `SystemSettings`, `AiSettings`, `HttpsSettings`, `WebDavConfig`, plus a new `ServerSettings`. A top-level `AthenaConfig` model holds them, and only `load()`/`save()` in each module change.
- Missing sections and fields take their defaults, so a file holding only `{"server": {"port": 8500}}` is valid. Unknown keys are errors (`extra="forbid"`), so a typo doesn't fail silently.
- Read-only fields (`tunnel_secrets_set`, `dns_secrets_set`) are never written.
- Secrets stay as they are now: tunnel and DNS tokens encrypted with `SecretBox` (the `enc:` prefix, key in `<data-dir>/secret.key`), WebDAV only as a hash. MCP `env`/`headers` and the durable-execution Postgres URL are plain text, as they are today in the database; 0600 protects them.

### Reading: strict, once, at startup

- `athena serve` reads and validates the whole file before anything else starts. A missing file means all defaults, and the server writes it so the admin can find it.
- If the file is invalid, Athena **refuses to start**. It exits with code 1 and prints one line per problem with the file, line and column where it can (`athena.json:14:12: https.port: Input should be less than or equal to 65535`). No fallback to defaults: quietly turning a disabled terminal back on is worse than not starting.
- The parsed document is kept in memory (`app.state.config`). Every `load()` reads from it, so hand edits made while Athena runs don't apply until a restart.
- `athena.schema.json` is written next to the file on every start, generated from `AthenaConfig.model_json_schema()`, so VS Code and other editors autocomplete keys and flag bad values.

### Writing: atomic, keeping the hand edits

- `save(section)` takes a process-wide lock and re-reads the file from disk. If the disk copy changed and is valid, the save keeps its other sections, so a hand edit to `server` survives a UI save of `ai` (with a log line that hand edits apply on restart). If the disk copy is invalid, the save fails with a clear error instead of overwriting the admin's half-done edit.
- Each save writes `athena.json.tmp`, fsyncs it, keeps the previous file as `athena.json.bak`, then calls `os.replace`. On Windows `os.replace` fails while another program holds the file open, so it retries a few times before failing.
- The output is pretty-printed (2 spaces) with keys in model order, so diffs and hand edits stay readable.

### Server section and precedence

`ServerSettings` holds `host`, `port`, `feedback_repo` and `durable_execution_database_url`. The precedence is CLI flag > `ATHENA_*` env var > file > default, implemented as a pydantic-settings source in `config.py`. `data_dir` can't be in the file, because the file is inside it. `web_dir` and `log_to_file` are internals and stay env-only.

### CLI

- `athena config path`: where the file is.
- `athena config show`: the effective settings, with the source of each server field (flag, env, file, default).
- `athena config check`: validates the file with the same messages as startup. Exit code 0 or 1.
- `athena config reset <section>`: puts one section back to its defaults, keeping a `.bak`.
- These replace the current `config get/set`, which only print an `export` line.
- `athena https off` keeps working, now as a file edit (it no longer opens the database).
- `athena doctor` reports `config check`'s result.

### Removed

The `system`, `ai`, `https` and `webdav` keys of the `system_settings` table. The table stays for the file-locations "seeded" marker, which isn't a setting anyone edits.

### Web, assistant, API

- No API changes, so the generated client is unchanged.
- Part 3 adds one line to Settings → System: "These settings are saved in `<path>`; edit it there if Athena won't start", with a link to the recovery docs. That needs `system_settings.public()` (or a small field on the system endpoint) to return the path, admins only.

### Dependencies

None (stdlib `json`, pydantic).

## Parts

1. **Settings file** (`feat(settings): store settings in athena.json`): `athena/settings_file.py`, `AthenaConfig`, the strict startup read with line/column errors, atomic and merging saves, the schema file, moving `system`/`ai`/`https`/`webdav` onto it (`load()`/`save()` take the config store instead of a DB session), `athena https off` on the file, tests, and the one-off conversion of the development database (not committed).
2. **Server section and CLI** (`feat(cli): athena config path/show/check/reset`): `ServerSettings` with flag > env > file > default, the `config` commands, the doctor check, docs (a `docs/design/decisions.md` row, `backend.md`, a "recovering from bad settings" section in the user docs, `docs/agents/commands.md`).
3. **UI hint** (`feat(web): show where settings are saved`): the Settings → System line, verified with `athena-ui-verify`.

## Acceptance checks

- Unit tests: defaults when the file is missing (and the file gets written); a partial file; an unknown key, a bad value and a JSON syntax error each refuse startup with the expected `file:line:col` message; a save keeps another section's hand edit; a save refuses when the disk copy is invalid; `.bak` holds the previous version; `os.replace` retries (simulated `PermissionError`); secrets are still encrypted on disk and never returned by the API; env beats file for `port`.
- Existing settings, HTTPS, tunnel, WebDAV and assistant tests pass unchanged apart from fixtures.
- CI on Windows (atomic replace, paths).
- By hand: break `https.port` in the file, see `athena serve` refuse with the line number, fix it, see it start. Set `server.port` in the file and see the server listen there.
- Part 3: `athena-ui-verify` on Settings → System (phone width, dark mode).

## Open questions

All decided on 2026-11-21: JSON (not TOML); refuse to start on an invalid file; hand edits apply on restart; the file goes in the data dir; no legacy import (convert the dev database once).
