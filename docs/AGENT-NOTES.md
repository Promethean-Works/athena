# Agent notes

_Shared knowledge for every coding agent on Athena (Claude Code, OpenCode, Hermes Agent, others)._

This file holds the lessons from earlier sessions: how the maintainer works, the commands that matter, the patterns to copy, and the traps that have already cost someone time. It complements the other docs:

- `AGENTS.md`: the rules.
- `docs/STATUS.md`: where the work is now.
- `docs/mvp-design.md`: the design and the decisions.

Read this file once per session, after STATUS, down to **Gotchas**. Under Gotchas, read only the sections for the area you're touching (plus "Git, GitHub and CI" before you push); they're split by area so you don't have to read all of them.

**Keep it alive.** When you learn something non-obvious that the next agent would otherwise rediscover, add it in the right section. Examples: a CI failure with a surprising cause, a tool quirk, a false positive, a pattern that worked. Use one bullet per fact and say _why_. Delete bullets that stop being true. Design decisions still go in `docs/mvp-design.md` §11, not here.

## Working with the maintainer

- They move through the milestones in `docs/mvp-design.md` §10 in order, with short prompts like "next", "continue", "start M5", "check" or "yes". "Next" means: read STATUS, propose the next concrete step with a recommendation, and wait for a yes before starting a new milestone or part.
- Big milestones are split into parts (M5 A/B, M6 A/B/C), with one branch and one PR per part.
- When asked to "discuss questions first", list the open questions with a recommendation for each before writing code.
- Every PR gets auto-merge as soon as it's opened, without asking (standing instruction since 2026-11-14): `gh pr merge <n> --squash --auto --delete-branch`. The exceptions are in AGENTS.md → Git workflow. Auto-merge only waits for the required checks (`ci-ok`, `pr-title`), so also check that CodeQL is green before you call a PR done.
- "Check" / "check now" / "could you keep observing the PRs?" means: read the PR checks (`gh pr checks <n>`, `gh run view <id> --log-failed`), fix failures on the PR branch, and report what merged and what didn't. Never claim something merged without checking.
- Fix CodeQL alerts in code rather than dismissing them. Dismissing changes the repo's security state, so it's the maintainer's call (see [CodeQL](#codeql)).
- Report honestly: what was verified, what wasn't and why, and the bugs found along the way. Final reports list "Fixed along the way" and "Not tested yet".
- They can't see your private memory. Anything another agent needs goes in the repo.

## Command cheat sheet

Run pnpm from the repo root and Python with `uv run` inside `apps/server`.

| Task | Command |
|---|---|
| **Everything CI runs** | `scripts/check.sh` (`--quick` skips the web build; `web`, `server` or `repo` runs one part). Without a terminal it's quiet: one `ok`/`FAIL` line per step and the last 40 lines of a failure, with the full log's path. `--verbose` streams everything |
| Pre-push hook (once per clone) | `git config core.hooksPath .githooks`; skip once with `git push --no-verify` |
| Docs name real things | `node scripts/check-docs.mjs` (`--list` prints everything it verified) |
| All web checks | `pnpm lint && pnpm typecheck && pnpm build` |
| Server lint | `cd apps/server && uv run ruff check . && uv run ruff format --check .` |
| Server tests | `cd apps/server && uv run pytest -q` (add `-k name` to narrow) |
| Real-engine tests | `ATHENA_DOCKER_TESTS=1 uv run pytest -q -k docker` (touches your engine; opt-in) |
| Regenerate API client | `pnpm gen:api` (after any API change; CI fails on drift) |
| Regenerate theme CSS | `pnpm gen:theme` (after shadcn upgrades; needs network) |
| Agent config sync | `node scripts/agents-sync.mjs` (after editing `.mcp.json`); `--check` is what CI runs |
| Release server for UI checks | `pnpm build` then `cd apps/server && ATHENA_WEB_DIR=../web/out uv run athena serve --port 8421 --data-dir "$DATA"` |
| Dev mode | `pnpm dev` (Next on :3000, proxies `/api` to :8420) plus `uv run athena serve` |
| VS Code | `.vscode/launch.json` (debug the server, pytest, Next with Chrome, or both as "Full stack") and `.vscode/tasks.json` (dev, build, release serve, tests, checks, codegen). Data goes to the git-ignored `.dev-data/` |
| Build the wheel | `scripts/build-wheel.sh` (also used by `release.yml` and the E2E workflow) |
| Installer dry run | `scripts/install.sh --dry-run`; `athena service install --dry-run` |
| PR status | `gh pr checks <n>`, `gh run view <run-id> --log-failed`, `gh api repos/tiagozaccaro/athena/code-scanning/alerts?state=open` |

CI jobs (`.github/workflows/ci.yml`):

- `repo checks`: agent config sync, the `.claude/skills` symlink, actionlint, shellcheck.
- `install script` on 3 OSes: dry runs plus PSScriptAnalyzer.
- `web`: API client drift, lint, typecheck, build.
- `server` on 3 OSes: ruff, pytest, service dry run.
- `ci-ok`: the single required check.

Other workflows: `pr-title`, CodeQL (separate; it can block merges), and `E2E` (`e2e.yml`). E2E is slow and not part of `ci-ok`. It runs on pushes to main, on installer or service changes, and on demand.

## Patterns to copy

When adding something, start from the closest existing feature instead of inventing a new shape.

- **Host feature end to end:** follow the `athena-platform-feature` skill. Packages (`athena/packages/`, `api/packages.py`, `components/packages/`) is the cleanest full example: a capability per manager, pure parsers, jobs, audit, UI gated by `capability: "packages.*"`.
- **Long operation:** `request.app.state.jobs.start(title, body)`, with `run_or_fail(job, argv, title, env=...)` from `athena/jobs.py` inside. Return the job id with 202. The UI opens `<JobDialog job>`. Allow one job per resource at a time (see `app.state.package_jobs`).
- **Audit:** `athena.audit.record(db, username, "<area>.<action>", target)`, e.g. `package.install` with `apt:jq`.
- **Command execution:** use argument lists, never a shell. Set `LC_ALL=C.UTF-8` for parseable output. Validate user-supplied names with a regex that rejects a leading `-`, so a value can't become a flag: `PACKAGE_NAME` in `packages/base.py`, `check_ref` in `containers/service.py`.
- **Parsers:** pure functions over recorded output in `tests/fixtures/<area>/`, each recorded in a throwaway container where possible, with a README line saying how. Real-tool read-only tests use `pytest.mark.skipif` when the tool is missing, so Ubuntu CI runs apt, macOS runs brew and Windows runs winget/choco. Those real runs found bugs the hand-written fixtures missed.
- **API tests:** use `conftest.make_app()` and `signed_in(client)`. Tests that start jobs must enter the `TestClient` as a context manager (see `client_for` in `test_packages_api.py` and `test_terminal.py`). Otherwise jobs die with "event loop is closed".
- **Settings:** per-user settings go in `users.appearance` (`api/settings.py`). Host-wide switches go in the `system_settings` JSON row (`athena/system_settings.py`), and only admins can change them.
- **Missing capability in the UI:** render shadcn `Empty` with the capability's `detail` and its setup/start action, never a broken page. Containers pages wrap in `<RequireContainers>`.

## Gotchas

### Git, GitHub and CI

- Force pushes are blocked, so don't rebase a pushed branch. To bring in `main`, merge it into the branch; the squash merge hides the merge commit.
- When a PR stacked on another PR's branch has its base merged, GitHub retargets it to `main`. Merging `main` in then shows conflicts that are only squash artifacts. Resolve them toward `main`'s content.
- Don't turn on auto-merge for a PR whose base is another feature branch. That branch isn't protected, so it merges immediately into the wrong base.
- Two open PRs that both edit `docs/STATUS.md` or `AGENTS.md` will conflict. The second one needs its branch updated and the docs merged by hand; auto-merge won't do it.
- Never commit conflict markers into a generated file. For `packages/api-client/openapi.json` (or the generated types), resolve a conflict by rerunning `pnpm gen:api`, not by editing. Once, markers were committed and `web` failed.
- A macOS runner can sit queued for a long time and then be _cancelled_, which fails `ci-ok` with no code problem. Re-run the failed jobs.
- Dependabot can't fix a transitive pnpm dependency. Add an override in `pnpm-workspace.yaml` with a comment saying why (see the existing `baseline-browser-mapping`, `brace-expansion` and `minimatch` overrides), and remove it once upstream ships a fix.
- `pr-title` accepts Dependabot's capitalized "Bump …" subject; only the Conventional Commit type is enforced.
- release-please PRs need the `RELEASE_PLEASE_TOKEN` secret to run CI (see STATUS → Blockers). Don't merge a release PR yourself.
- The first release is 0.1.0 because of explicit config. release-please defaults to 1.0.0 without it.

### Windows portability (CI catches these; your Mac won't)

- Paths written into Linux/macOS files (systemd units, launchd plists, Colima socket paths) must use forward slashes even when generated or tested on Windows. Use `PurePosixPath` or string paths, not `Path`.
- Tests that compare paths must not hard-code `/`. Compare `Path` objects.
- Open text files with `encoding="utf-8"`. Windows defaults to cp1252, which gave a `UnicodeDecodeError` in catalog tests.
- Write test fixtures as bytes (`write_bytes`). Text mode on Windows turns `\n` into `\r\n` and breaks content checks.
- Windows silently strips trailing dots and spaces from names, so `...` resolves to the parent folder. Path containment must check that the final name is unchanged, not only that the parent is inside the root (see `athena/files/paths.py` and design §4.3). This was a real "delete the whole location" bug.
- winget IDs can contain spaces (`ARP\Machine\X64\Mozilla Firefox`), and its truncation ellipsis arrives as `�`.
- Recorded fixtures are stored byte-exact (`apps/server/tests/fixtures/** -text` in `.gitattributes`), so CRLF and spinner `\r` survive.
- In `install.ps1`, a failed native command (e.g. `wsl.exe` with no distro) leaves `$LASTEXITCODE` set, and CI reads the script as failed. Reset it after expected failures.
- PSScriptAnalyzer's unused-parameter rule only looks at the script's top level, so it flags parameters used inside functions (`-Wheel`). Suppress that rule for that parameter with a reason.
- On Windows, `schtasks /End` only kills the venv's `pythonw.exe` launcher. The real interpreter keeps the port and locks the install folder. The installers also stop `pythonw.exe -m athena serve` processes and wait for them.
- PowerShell isn't installed on the maintainer's Mac. The CI run is the first real check of `.ps1` changes.

### CodeQL

CodeQL runs on every PR and its alerts can block a merge.

- Any identifier containing "password" is treated as a secret. A constant named `MIN_PASSWORD_LENGTH` was flagged as "clear-text logging of password"; it's now `MIN_PW_LENGTH`. <!-- docs-check: ignore -->
- A fast hash (SHA-256) over anything derived from a password is flagged as weak password hashing, even as an in-memory cache key. Don't hash passwords for keys or caches; compare against what argon2 already produced.
- `hmac.compare_digest` on `str` raises on non-ASCII. Compare bytes.
- Regexes over URLs get flagged (ReDoS / incomplete sanitization). Prefer `urllib.parse` plus plain string checks.
- In the web app, sending server text to something named `write` looks like `document.write` (client XSS). The terminal wrapper's method is called `output` for that reason. Strip control characters from server-provided strings shown in the terminal, and accept only integers for exit codes.
- Path-injection alerts on file APIs are usually real. See the Windows trailing-dot bug above.

### Server (Python)

- `athena openapi` must not create the real data dir. It builds the app against a temp dir, and a test enforces this.
- SQLite runs in WAL mode. A test that reads `athena.db` directly misses rows still in `athena.db-wal`, so query through SQLAlchemy.
- `ruff --fix` can delete an import it thinks is unused when the name is shadowed. Use an aliased import.
- Mutable class attributes trip RUF012. Use tuples or `ClassVar`.
- The capability status type is `Status` (`athena/platform/`), not `CapabilityStatus`. <!-- docs-check: ignore -->
- Open SSE streams never end on their own. uvicorn's `timeout_graceful_shutdown` (5 s, `SHUTDOWN_GRACE_SECONDS` in `cli.py`) is what lets the service stop with a dashboard open. Keep it.
- Every compose command needs `env=store.env(name)`, not only deploy. Stop, restart and remove once failed for apps using `${ATHENA_APP_DATA}`.
- Compose YAML is YAML 1.2: `yes` is a string, not `true`. The CasaOS importer parses it the same way (one of 182 apps broke on this).
- Terminal: don't use `pty.fork()` or ptyprocess in the multi-threaded server; they can deadlock (Python 3.12+ warns). Use the stdlib pty with `Popen(start_new_session=True)` and the `TIOCSCTTY` shim in `athena/terminal/pty.py`.
- `require_user` can't protect WebSockets. The terminal checks the cookie itself and takes the CSRF token in the first message (see the top of `api/terminal.py`).
- wsgidav: a DELETE on a collection whose `delete()` refuses falls back to deleting every member one by one. That emptied a whole location. Refuse such requests in `handle_delete` / `handle_copy` / `handle_move` before wsgidav gets there, and test it.
- Tests that need a CLI to be _absent_ must really hide it from PATH. A test passed on every machine with `docker` and only failed on macOS CI, which has none. Run such tests with the tool removed from PATH.
- The release wheel must include the catalog (`athena/catalog_builtin`) and the web export. Once it shipped without the catalog, and the store was empty. `build-wheel.sh` now fails if either is missing.

### rclone (cloud storage)

- rclone accepts `name:..` and leaves an alias remote's folder (`operations/list` on `loc:..` listed its parent). The API's own `remotes.check_path` is the only guard; never pass a user path into an fs string without it.
- Every rc call is a job in rclone, so job ids climb on every request (`core/version` too). Use the `jobid` an `_async` call returns; don't guess it.
- `_config: {"BwLimit": …}` has no effect: the bandwidth limit is global (`core/bwlimit`). To make a transfer slow enough to test progress or cancel, run the test WebDAV server with `rclone serve webdav <dir> --addr 127.0.0.1:<port> --user u --pass p --bwlimit 3M` and add it as a `webdav` remote. It's a real remote with no cloud account needed.
- Progress can reach 100% while the job still runs: rclone counts bytes once it has read them, and a slow remote may still be taking them. The job dialog then says "finishing…". A cancel at that point can still leave the whole file on the remote.
- `rclone serve webdav` caches folder listings for about 5 minutes, so files written straight to its folder don't show up in listings or sync previews until then. Create test files through the API.
- In the non-interactive config flow, a refused answer (a bad OAuth token) comes back with the same `State`, an `Error` and no `Option`: ask the same question again. Athena returns it as `ConfigStep.error` with `question: null`.
- rclone marks more than passwords as `Sensitive` (WebDAV `user`, S3 keys, OAuth client secrets). Treat both flags as secrets; the edit form shows them as "Unchanged".
- `config/create` writes the section immediately, before its follow-up questions are answered, so a remote abandoned halfway stays in the config unless it's deleted (the dialog's Cancel does that).
- Ubuntu's apt rclone is old (1.60 on the CI runner) and behaves differently. `operations/check` returns no file lists there, so a preview built on it said "nothing will be deleted" when sync would delete files: the preview lists both folders instead. 1.60 also doesn't mark WebDAV `user` as sensitive and words errors differently ("didn't find section in config file"). CI installs it on purpose; write tests that pass on both.
- Newer rclone (1.76) asks about Google's retiring shared client id before the OAuth step; older ones don't. Tests loop over questions until `config_token` instead of hard-coding the order.

### Web (Next.js 16, shadcn on Base UI)

- Base UI, not Radix: component APIs differ (`render` prop instead of `asChild`, different `Select` and `ToggleGroup` APIs). Check the `shadcn` skill or `shadcn docs <component>` before using one.
- The shadcn CLI may drop files in `apps/web` that belong in `packages/ui`. It put `use-mobile` in `apps/web/hooks` while the sidebar imported it from `packages/ui`, which broke typecheck. Check where added files land.
- `trailingSlash: true` (needed so FastAPI's `StaticFiles` serves `<route>/index.html`) made `next dev` 308-redirect every `/api` call before proxying it. The dev config sets `skipTrailingSlashRedirect: true`; keep it when touching `next.config.ts`.
- `next-env.d.ts` is gitignored, and CI typechecks before building. Don't rely on it existing.
- next/font: each loader call must be its own module-level `const` with literal options. Spreads or calls inside an object literal fail the build (`apps/web/lib/fonts.ts`).
- Appearance is applied before paint by `APPEARANCE_SCRIPT` in `<head>`, and re-applied in `useLayoutEffect` after the dev Strict Mode remount. next-themes changes `setTheme`'s identity on mode change; an effect depending on it re-ran the initial load and undid the user's change. Use refs and a load-once effect.
- Theme generation (`scripts/gen-theme-css.mjs`): themes depend on the base color, `chartColor` must be omitted for neutral, `rose` changes the dark sidebar (so keys are tracked per mode), and the registry refuses `gray`, so it's skipped.
- A Sheet's width and max width come from `data-[side=right]:w-3/4` and `data-[side=right]:sm:max-w-sm`, which beat a plain `w-full` or `sm:max-w-xl`. Override them with the same prefix (`data-[side=right]:w-full data-[side=right]:sm:max-w-xl`, as `AssistantSheet` does). A trigger whose label is hidden at phone width (`hidden sm:inline`) needs an `aria-label`.
- Toasts must sit above sheets and dialogs. Both were `z-50`, which hid every error toast behind side panels. The toast viewport is raised in `packages/ui/src/components/toast.tsx`; don't lower it.
- Generated types sometimes lack a shape you need (e.g. `HostStats`). Derive it (`Omit<StatsSnapshot, "history">`) rather than hand-writing request types.
- Byte formatting: values just under a unit boundary must switch unit (no "1024 B/s").
- After any action that changes a list (apps, files), reload the list. A stale tile after a failed action was a real bug.
- Links rendered from untrusted text (terminal output) must allow only `http(s)` and open in a new tab. A `javascript:` link was clickable once.
- Next 16 proxying of the terminal WebSocket in `next dev` is unchecked. Use the release build for terminal work.

- `InputGroup` has `has-disabled:opacity-50`: one disabled button inside (a Send button with no text) fades the whole prompt box. Use `aria-disabled` plus a guard in the submit handler.
- `shadcn add code-block` also drops shiki helpers (`lib/highlighter.tsx`, `hooks/use-highlighted-code.ts`) into `apps/web` and adds `shiki`. `CodeBlock` doesn't need them; they were deleted. shadcn's Typeset is a CSS file from its online builder, not a registry item. <!-- docs-check: ignore -->
- The chat UI reads the assistant's SSE with `fetch` and a stream reader (POST with the CSRF header), not `EventSource`, which can only GET. `TextDecoderStream` fails typecheck with this TS lib setup; use `TextDecoder` with `stream: true`. <!-- docs-check: ignore -->

### Assistant (pydantic-ai)

- pydantic-ai here is 2.x (`pydantic-ai-slim`): store chats with `ConversationTypeAdapter` (a `Conversation` carries usage for `UsageLimits` across turns), stop runs with a `CancellationToken` (`RunCancelled.all_messages()` keeps the partial reply), and pass the model per run. Read the installed source under `.venv/…/pydantic_ai/` before trusting older docs. <!-- docs-check: ignore -->
- `UsageLimits` passed with a `conversation=` are checked against the **whole chat's** usage (`Conversation.usage` is cumulative), not the run's. A fixed `request_limit=25` once stopped every chat for good after 25 requests in total. Per-turn limits must add what the chat already used: see `turn_limits` in `assistant/chat.py`. The spend limit is meant per chat, so it stays fixed.
- `FunctionModel` needs `stream_function=` for `run_stream_events()` (a plain function errors with "must receive a stream_function") and `function=` for a plain `agent.run()`, like the title agent's; give a test model both when it serves both. Tool calls are yielded as `{0: DeltaToolCall(...)}`.
- A route that starts an `asyncio` task must be `async def`: sync routes run in a thread with no running loop.
- OpenRouter model ids must include the upstream (`openai/gpt-x`); `build_model` raises `UserError` otherwise, which the API returns as a 409.
- Newer Ollama returns `capabilities` in `/api/tags`; older ones need `/api/show` per model. Both are handled. `ATHENA_OLLAMA_TESTS=1` runs a real Ollama test.
- Approvals: give the agent `output_type=[str, DeferredToolRequests]` and register actions with `Tool(fn, requires_approval=True)`. The paused run's `Conversation.deferred_tool_requests` survives `ConversationTypeAdapter` round trips, so answer from the stored copy with `build_results(approvals=...)`. A resumed run re-emits `FunctionToolCallEvent` for the approved calls (the UI updates the existing part by id instead of adding one). A new prompt is refused while calls are unanswered unless `deferred_tool_results` comes with it, which is how a new message denies them. A denial comes back as a `ToolReturnPart` with `outcome="denied"`.
- Assistant actions call route functions directly (`apps.app_action(name, action, request, runtime, user, db)`). FastAPI's `Path`/`Query` checks don't run on a direct call, so the tool's own parameters carry the same patterns (`Annotated[str, Field(pattern=...)]`; pydantic-ai validates them and asks the model to retry). Route helpers that use the chat's db session run on the event loop, not `asyncio.to_thread` (SQLite sessions are per thread).
- Small local models (qwen2.5 7B) guess ids, e.g. a file location id, instead of calling the list tool first. The approval card resolves ids to names ("… in App data"), which is how the admin catches it; the instructions also tell the model never to guess.
- Costs in tests: `FunctionModel(..., model_name="gpt-4o")` gets real prices from pydantic-ai's bundled price list, offline. In the browser, a tiny stdlib fake OpenAI-compatible server that streams a reply with `usage` and reports model `gpt-4o` is priced too (add it as an "OpenAI-compatible" provider); serve another model name to see the "prices unknown" state. The title agent's request has no `tools`, which is how a fake can tell it apart.
- pydantic-ai-harness pins `pydantic-ai-slim==` the same version: upgrade both in one PR (a Dependabot bump of only one fails to resolve). Its `LocalWorkspaceBackend` raises `NotImplementedError` on Windows, hence `WSLWorkspace` in `assistant/workspace.py`. The harness `Shell` checks `allowed_commands` (first word only) inside the tool, after `Permissions` has already asked, so `ShellGuard.after_tool_validate` runs our stricter check first and raises `ToolFailed` (a failed call; `ModelRetry` is capped and running out ends the turn). Its `run_command` result is `[stdout]…`, with `[exit code: N]` only when N isn't 0. <!-- docs-check: ignore -->
- Process groups in `sh`: dash (`/bin/sh` on Debian and Ubuntu, so inside most WSL distros) and zsh refuse `set -m` without a terminal, and the job stays in the script's group, so killing "its group" would kill the script's. `WSLWorkspaceBackend` uses `setsid` and falls back to `set -m` only after checking with `ps` that the job leads its own group. Test the WSL script without Windows by setting `launcher=("docker", "exec", "<container>")` against Debian and Alpine containers (pull from `public.ecr.aws/docker/library/…` to avoid Docker Hub limits); Debian slim has no `ps`, so check leftovers through `/proc`.
- Browser check of the shell: qwen2.5 via the local Ollama follows "use run_command to run exactly: …" reliably. Allow only harmless programs (`uname`, `df`) while testing, because an approved command really runs on your machine.
- `packages.brew` is really `ready` on the maintainer's Mac, so an approved package action in a browser check really runs `brew`. Only approve file actions inside a scratch location, or stub `brew` on `PATH`.

### Browser verification (`athena-ui-verify`)

- Base UI checkboxes and switches render a hidden `<input>`. A click on it "works" but sends the wrong value, and only `browser_network_requests` showed that. Click the visible control and re-snapshot.
- Take a fresh snapshot after a dialog closes or the layout shifts. Stale refs click the wrong thing, and clicking while a page is still loading misses.
- A rebuilt web export is served without restarting the server. Server or catalog changes need a restart.
- Fake anything that would change the host: a stub `brew`/`colima` first on the server's `PATH` (reads can pass through to the real tool), or `HOME` pointed at an empty folder so a runtime looks stopped. For files, point `HOME` at a scratch folder so the default Home location isn't the real one.
- Anonymous Docker Hub pulls are rate-limited (429). Image-checking loops used up the quota for hours. Prefer ghcr.io or codeberg.org images in tests, and don't loop `docker manifest inspect`.
- Keep the developer's personal data out of fixtures and screenshots. For example, a fixture once used a real installed-cask list and was replaced with neutral entries.
- Playwright MCP can crash at launch on macOS (`SIGTRAP`, `bootstrap_check_in … MachPortRendezvousServer: unknown error code (124)`), even outside the sandbox. It was transient: the same call worked a few minutes later. Retry before giving up, and drive the API with a script meanwhile.
- `browser_file_upload` only accepts files under the repo (`.playwright-mcp/` is git-ignored). Copy test files there instead of using the scratchpad, and delete them afterwards.
- A text input with a `<datalist>` shows up as a `combobox` in snapshots, not a textbox: type into it, don't wait for a listbox.
- What the sandbox can't do: `mount_webdav` (Finder mounts), `.claude/settings.json` edits, and turning on Claude's PR monitor. Say so and leave them to the maintainer; don't work around the guard.

### Installers and E2E

- Hosted runners can't run Colima's VM (macOS) or WSL2 (Windows), so containers are only checked end to end on Linux in CI.
- For a full Linux check locally on a Mac, use a Lima VM (`limactl start template://ubuntu`, or `template://fedora` for dnf). Docker containers don't run systemd, so they can't test the service.
- Installers take `--wheel <path>` / `-Wheel <path>` so E2E tests the commit, not the last release.
- Recording pacman fixtures under amd64 emulation on Apple Silicon needs `--disable-sandbox` (for recording only).

### Agent environment

- The maintainer's shell is zsh. `echo =====` fails there (`=word` expands to a command path), and unquoted `$VAR` lists don't word-split. Quote or use arrays.
- Claude Code's safety check refuses `rm` with unguarded variables or globs (`rm -rf $S/*`). Use literal paths.
- Hermes quarantines `pydantic-ai-harness` as "dangerous" (a false positive). Read its `SKILL.md` directly.
- Hermes's scanner also hides **our own** skills when they contain `curl … | python3` (rated critical "supply chain"), even when Python only parses JSON. In skills, use `jq` or save to a file first. `sudo`, `uv run` and systemd mentions are only medium and don't hide a skill. To check a skill before committing: `PYTHONPATH=~/.hermes/hermes-agent ~/.hermes/tools/python-3.14*/bin/python3 -c "from pathlib import Path; from tools.skills_guard import scan_skill; print(scan_skill(Path('.agents/skills/<name>'), source='project').verdict)"` should print `safe`.
- Another agent session may be working in the main checkout at the same time (uncommitted changes on its feature branch). For unrelated work, use `git worktree add ../athena-<topic> -b <branch> origin/main` instead of switching branches under it.
- The machine can be offline (no DNS, even outside the sandbox). `uv run --offline --with <pkg>==<version>` uses uv's cache when the package was installed before.
- `pkill` and `ps` may fail in the sandbox ("Cannot get process list"). Find a server by its port with `lsof -nP -t -iTCP:<port> -sTCP:LISTEN` and `kill` that pid.
- **Token budget.** Things every session pays for are kept small on purpose: STATUS is capped at 8 KB by `scripts/check-docs.mjs` (finished work goes to `docs/HISTORY.md`); `scripts/check.sh` is quiet without a terminal; Playwright runs with `--snapshot-mode none` (snapshot only when you need to read the page); `.ignore` keeps lockfiles, CHANGELOG and the generated theme files out of ripgrep searches; Claude Code caps Bash and MCP output at 20k (`.claude/settings.json` → `env`) and OpenCode caps tool output at 20 KB (`opencode.json` → `tool_output`, the rest is saved to disk). Pipe long commands through `tail` or `grep` yourself too.
- **MCP tool definitions cost tokens on every request in OpenCode and Hermes** (Claude Code loads them on demand). Measured: Playwright 25 tools ≈ 21k characters, next-devtools ≈ 5.7k, context7 ≈ 5.2k, shadcn ≈ 4.3k. So `scripts/agents-sync.mjs` gives Playwright only to OpenCode's `ui-verify` subagent (a `playwright_*` deny rule globally, allow in the agent; agent rules come after global ones and the last match wins), and writes Hermes `tools.exclude` filters for unused tools. OpenCode 2.x already routes MCP tools through Code Mode by default (`codemode: true`). Hermes' `lazy: true` only delays connecting; the tools are still registered, so it saves memory, not tokens.
- `node scripts/agents-sync.mjs --hermes` also re-applies `args` and `tools` to servers Hermes already has (via `hermes config set`, a no-op when unchanged), so flag changes in `.mcp.json` reach Hermes. Restart Hermes or run `/reload-mcp` afterwards.
- Port 8420 may be the maintainer's own Athena. Use 8421 or another spare port.
- Act only on containers, apps and images named `athena-demo-*` / `athena-test-*`. The maintainer's own containers run on the same engine. Leave pulled images unless you know you pulled them, and say which ones are left.
