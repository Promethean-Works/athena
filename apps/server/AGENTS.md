# Athena server (`apps/server`)

Rules for working on the Python server. The repo-wide rules, Git workflow and handoff are in the root `AGENTS.md`; read that first. Gotchas: `docs/agents/gotchas/server.md` (read before changing server code), `docs/agents/gotchas/windows.md` and `docs/agents/gotchas/codeql.md` (before pushing); the assistant and rclone have their own files there. For step-by-step changes (endpoint, migration, job, setting), use the `athena-recipes` skill. For anything that touches the host OS, use `athena-platform-feature`.

## Stack and commands

Python 3.13 (uv), FastAPI, SQLModel and Alembic on SQLite. Package `athena`, CLI `athena` (`serve`, `openapi`, `service install|uninstall|status`, `start`, `stop`, `doctor`, `config show|get|set`, `admin reset-password`, `https status|off`). Run everything with `uv run` from this folder:

| Task | Command |
|---|---|
| Tests | `uv run pytest -q` (`-k name` to narrow) |
| Lint and format | `uv run ruff check` and `uv run ruff format --check` (CI runs both) |
| Real-engine tests | `ATHENA_DOCKER_TESTS=1 uv run pytest -q` (`-k "real_app or real_container or compose_config"` for only those). They touch your container engine, so they're opt-in (on in Linux CI) |
| Run the server | `uv run athena serve --port 8421 --data-dir "$DATA"` (8420 may be the developer's own Athena) |
| After any API change | `pnpm gen:api` from the repo root; CI fails if `packages/api-client` is stale |
| Everything CI checks | `scripts/check.sh server` from the repo root |

## Module map (`src/athena/`)

| Module | What it holds |
|---|---|
| `main.py` | `create_app()`: wiring, `app.state`, every `include_router` |
| `cli.py`, `config.py` | The CLI and settings (data dir via platformdirs, `ATHENA_*` env) |
| `api/` | One thin router per area. Logic lives in the area packages below |
| `auth/` | Sessions, argon2id passwords, CSRF (`deps.py`: `require_user`, `Authed`, `DbSession`) |
| `db/` | `models.py` (SQLModel), `engine.py`, `db/migrations/versions/` (Alembic) |
| `platform/` | Host detection: `probe.py` (never raises), `detect.py`, `capabilities.py`, `store.py` |
| `containers/` | `runtime.py` (`runtime_from(capability)` gives the CLI prefix and client), `service.py` (operations, `check_ref`) |
| `apps/` | `store.py` (on-disk layout, compose checks, `store.compose(...)`), `docker_run.py` (converter) |
| `catalog/` | `model.py` (`x-athena` format), `loader.py` (load and resolve install values), `registry.py` (built-in plus downloaded catalogs), `remote.py` (fetch and extract archives), `casaos.py` (CasaOS import) |
| `packages/` | `base.py`, then one class per manager in `linux.py`, `apps.py` (brew, flatpak, snap), `windows.py`; `MANAGERS` in `__init__.py` |
| `files/` | `paths.py` (containment), `locations.py`, `ops.py`, `shares.py` (public links), `smb.py` (SMB shares), `webdav.py` |
| `cloud/` | `rclone.py` (the `rclone rcd` sidecar and its client), `remotes.py` (backends, remotes, config questions, remote paths), `transfers.py` (copy, move and sync jobs with progress and cancel) |
| `assistant/` | The AI assistant: `kinds.py` (provider forms), `providers.py` (pydantic-ai models per provider, live model lists), `settings.py` (Settings → AI), `tools.py` (read-only tools and `toolset_for`, gated by capabilities), `actions.py` (tools that change things: `requires_approval=True`, card summaries), `shell.py` (the shell allowlist check, and the PowerShell runner for Windows without WSL), `workspace.py` (the harness `Shell` with `Permissions`, `WSLWorkspace`, `ShellGuard`), `robustness.py` (always-on harness capabilities: argument repair, loop nudges, output spills, reminders, cache-bust logging), `safety.py` (tool results as untrusted input: the prompt injection defender, secret redaction, `RedactionGuard`), `knowledge.py` (memory across chats, skills from the data dir, and the scanner that audits flagged notes and skills), `plans.py` (the plan per chat: harness `Planning` with `write_plan` only, on a `SqlitePlanStore`), `delegation.py` (`delegate_task` with the read-only `investigator`, background delegations whose results the stream and chat UI put on the call's row, `run_workflow` scripts of investigators for large contexts, and the optional `advisor` tool), `review.py` ("Double-check answers": `RefineOutput` that marks the draft), `questions.py` (`ask_user_question` cards: `AskUser` with no answerer, and turning the admin's answers into tool results), `compaction.py` (history compaction and the `TranscriptRecorder` that keeps the full transcript), `context.py` (each model's context window, looked up per turn), `chat.py` (turns streamed as SSE, approvals resumed with `DeferredToolResults`, history as pydantic-ai `Conversation` JSON), `models_dev.py` (provider kinds from models.dev, cached 24 h in `models_dev_cache`), `persistence.py` (step persistence, conversation search), stage 3 extras behind Settings → AI switches (`web_research.py`, `browser_use.py`, `approval_review.py`, `docker_sandbox.py`, `durable_execution.py`, `coding_stack.py`, `code_mode.py`), `integrations.py` and `mcp.py` (hosted MCP servers as assistant toolsets) |
| `terminal/` | `pty.py` (one async pty for POSIX and ConPTY), `shells.py` (host or container shell) |
| `service/` | `athena service install` per OS (`platforms.py`, `plan.py`) |
| `automation/` | `service.py`: durable triggers (cron, webhook), their job runs and the scheduler loop |
| `mcp/` | Athena's own MCP server at `/api/mcp`: `server.py` (tools), `auth.py` (session cookie or `ATHENA_MCP_TOKEN` bearer) |
| `https/` | HTTPS for Athena itself: `settings.py` (the `https` section of athena.json), `local_ca.py` (local CA and server certificate), `manager.py` (`HttpsManager`: a second uvicorn server on the HTTPS port, run from the lifespan), `redirect.py` (HTTP → HTTPS, never for loopback, proxies or `/api/health`) |
| `tunnel/` | Remote access: `base.py` (`TunnelProvider`), `cloudflare.py`, `tailscale.py`, `ngrok.py`; `get_provider` in `__init__.py` |
| `jobs.py`, `audit.py`, `monitor.py`, `system_settings.py`, `settings_file.py` | Jobs over SSE, the audit log, host stats, host-wide settings, `<data-dir>/athena.json` |
| `crypto.py` | `SecretBox`: Fernet encryption of stored secrets with `<data-dir>/secret.key` |
| `logging_setup.py` | Logs to stderr and `<data-dir>/logs/athena.log` |

## Conventions

- **Routes:** everything is under `/api`, and each route has an explicit camelCase `operation_id`. New routers must require a session: `include_router(..., dependencies=[require_user])`, which also CSRF-checks writes. The only public routes are health, `/api/auth/*`, a share link's `/api/public/shares/{token}`, `POST /api/automation/webhook/{token}` (the trigger's token is the credential) and `/api/mcp` (session cookie or `ATHENA_MCP_TOKEN` bearer, checked by `MCPAuthMiddleware`). WebDAV at `/dav/` has its own sign-in, and the terminal WebSocket checks its session and CSRF itself (see the top of `api/terminal.py`).
- **Database:** every model change needs a new migration in `db/migrations/versions/`. `tests/test_db.py` fails if the models and migrations differ. Migrations run on every start.
- **Long operations** run as jobs: `request.app.state.jobs.start(title, body)`, with `run_or_fail(job, argv, what, env=...)` inside, returning 202; the UI opens `<JobDialog job>`. One job per resource at a time (see `app.state.package_jobs`).
- **Audit** privileged actions with `athena.audit.record(db, username, "<area>.<action>", target)`.
- **Commands:** use argument lists, never `shell=True`. Validate user-supplied names before they reach a CLI (`check_ref`, `PACKAGE_NAME`), and reject a leading `-`. Run with `LC_ALL=C.UTF-8` when parsing output.
- **Apps:** compose commands go through `store.compose(...)` with `env=store.env(name)`, so `${ATHENA_APP_DATA}` resolves. That applies to stop, restart and remove, not just deploy. Installs go through `deploy_new_app()` in `api/apps.py`.
- **Catalog:** apps live in `catalog/apps/<id>/compose.yaml` at the repo root (see `catalog/README.md` and the `athena-catalog-app` skill). `tests/test_catalog.py` checks every one. Remote fetches are stubbed in tests (`remote.download`).
- **Packages:** parsers are pure functions over recorded output. A new parser needs a fixture in `tests/fixtures/packages/` and a line in that folder's README saying how it was captured, recorded in a throwaway container where possible. Real-tool runs have found bugs that hand-written fixtures missed.
- **Shares and WebDAV:** `api/shares.py` has the admin `router` plus the public `public_router`. `files/webdav.py` holds the wsgidav provider, sign-in and the `/dav` middleware. Location folders can never be deleted, moved or replaced over WebDAV (wsgidav would empty them).
- **Cloud (rclone):** talk to rclone only through `app.state.rclone` (`Rclone.call`), never by running the `rclone` CLI. Check remote paths with `remotes.check_path` and build fs strings with `remotes.fs_of`. rclone itself lets `name:..` leave an alias's folder. Jobs that run rclone transfers use `transfers.run(job, rclone, steps)` and start with `cancellable=True`.
- **Assistant:** tools are thin wrappers over Athena's own services, registered in `toolset_for(manifest)` only when their capability is ready. Anything that changes the host goes in `actions.py` (it's registered with `requires_approval=True` there), calls the route helper the UI uses, gets a sentence in `summarize()`, and waits for its job with `_follow`. Provider HTTP goes through `httpx2` with `app.state.ai_transport` (tests set an `httpx2.MockTransport`). Never return a stored secret from the API; empty secrets on edit keep the stored value.
- **Settings:** per-user settings go in `users.appearance` (`api/settings.py`). Host-wide ones are sections of `<data-dir>/athena.json` (`settings_file.py`; routes take `SettingsStore`), editable by hand; only admins change them.
- **Host access** always goes through a capability; never branch on `sys.platform` in a router. See the `athena-platform-feature` skill.

## Tests

- **Apps for tests:** `conftest.make_app(tmp_path)` builds an app on a fake macOS host. Pass `store=` with a `FakeProbe` from `tests/fake_probe.py` to simulate another OS. `signed_in(client)` creates the admin and sets the CSRF header.
- **Tests that start jobs** must hold the `TestClient` open as a context manager for the whole test (see `client_for` in `tests/test_packages_api.py`), or the job's event loop closes.
- **Real-tool tests** use `pytest.mark.skipif` when the tool or engine is missing, so each CI OS runs its own (apt on Ubuntu, brew on macOS, winget and choco on Windows).
- **Cloud tests** (`tests/test_cloud.py`) run a real `rclone rcd` (CI installs rclone on all three OSes) with `alias` remotes over temporary folders, plus a `FakeRclone` for things rclone can't easily produce, like a transfer that's still running when it's cancelled.
- **Write code that passes on Windows:**
  - Open text with `encoding="utf-8"`, and write fixtures with `write_bytes`.
  - Compare `Path` objects, not strings with `/`.
  - Paths written into Linux or macOS files stay forward-slash.

  More in `docs/agents/gotchas/windows.md`.
