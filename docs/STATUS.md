# Athena status

_Shared handoff log for every coding agent. Update it at the end of each session (see AGENTS.md → Handoff)._

**Current milestone:** M7, the AI assistant (§4.5). Parts A, B and C are done; part D stage 1 and stage 2 done (#65–#73 merged). Stage 3: web research (#75), second-model reviews (#76), Docker sandbox (#77), hosted integrations (#78) and durable execution foundation (#80) done; browser blocked by a dependency conflict (see below).

## Done

Finished work is in `docs/HISTORY.md` (read it only when you need a feature's background). When you finish something, add a short bullet there with the PR number and take it out of In progress below.

## In progress

- PR #98 (49-app catalog plus the storefront UI: banner, covers, screenshot galleries) is open with auto-merge; CI and the browser pass are the last gates.
- M7 D stage 2 complete: PRs 1–5 (#65–#73) all merged (#73 = `step_persistence` + `conversation_search` + `media`). Follow-up ideas: show a delegate's own tool calls nested under its row; a Settings → AI page to see and clear notes and to list or upload skills; warn in the UI when Ollama runs a model with a context too small for Athena's prompt and tools (see AGENT-NOTES → Assistant); on a phone, a waiting question card sits mostly below the plan bar and prompt until you scroll.
- MCP server support for the assistant added: `McpStdio` and `McpHttp` server configs in `ai_settings.mcp_servers` (Settings → AI), built as fresh `MCPToolset`s per turn and wired into the chat agent, investigator (delegation) and `run_workflow` helpers. Audit logs MCP server changes.
- Not yet verified for real: the Windows terminal (ConPTY plus PowerShell) beyond CI's pty tests, and the container shell through Docker in WSL.
- Not yet verified for real: the other Linux system managers' install/uninstall (dnf, pacman, zypper, apk; apt was checked in a Lima VM, see #26 in HISTORY) and every Windows manager (hand-written fixtures; CI runs choco/winget reads on Windows).
- Cloud add-storage wizard (PR #97, branch `feat/cloud-add-storage-wizard`, auto-merge on): "Add remote" on `/cloud` is now a two-step wizard — step 1 picks a storage provider from an icon catalog (like the app store), step 2 fills in the connection name and settings; rclone's follow-up questions are answered one at a time. No API change. Verified: web lint/typecheck/build, prettier, check-docs. Blocked on CI: the `server (macos-latest)` job is stuck QUEUED (GitHub runner infra, not a code problem; change is web-only). `athena-ui-verify` browser pass and a real rclone remote not yet done.

## Next

M7 part D stage 3 (design §4.5 Parts): extras with outside services.
- Web research: done — Exa (`web_search`/`get_page`), gated by `web_research_enabled` + `EXA_API_KEY` (#75 merged).
- Second-model reviews: done — `ApprovalReviewer` consults a second model per action awaiting approval, gated by `review_model`/`review_tool_calls` (#76 merged; auto-approve needs deferred-flow changes, a follow-up).
- Docker sandbox: done — `DockerSandbox` (`python:3.13-slim` container) offered when `docker_sandbox_enabled` is on and the `containers` capability is ready (#77 merged).
- Browser: repo side wired (`browser_use_enabled` setting + `browse_web` capability behind a lazy import guard, Settings → AI card, audit), all server/web tests and checks pass; **blocked** — `pydantic-ai-harness[browser-use]==0.68.0` pins `browser-use` → `google-genai==1.65.0`, conflicting with `pydantic-ai-slim[google]>=2.68.0` (`google-genai>=2.30.0`). Needs a harness release whose `browser-use` extra allows `google-genai>=2.30.0`, then unpin `pydantic-ai-harness` in `apps/server/pyproject.toml`. The toggle does nothing until then.
- Hosted integrations (D.5): done — curated MCP servers with a per-server encrypted token, Settings → AI card, actions through the same approval cards (#78 merged).
- Durable execution (D.6): done — turns are wired to run inside pgtask tasks against Postgres when `durable_execution_enabled` is on and `ATHENA_DURABLE_EXECUTION_DATABASE_URL` is set; each model request/tool call is checkpointed as a pgtask step, so an interrupted run resumes from its last completed step instead of repeating paid work. Transparent outside a pgtask task, so hosts without pgtask + Postgres run turns inline unchanged. Real Postgres and a crash/resume flow not yet verified.
- Coding stack (D.7): foundation done (#81 merged). File-system write/edit capabilities done — `FileSystem` bounded to `<data-dir>/assistant/code-workspace` under `coding_stack_enabled`, with `Permissions` in read-only mode so `write_file`/`edit_file`/`create_directory` go through the Approve/Deny card and reads run free (#84 merged). Shell commands added to the coding stack behind the same `ShellGuard` allowlist + approval + audit as the assistant shell, only when the shell allowlist is non-empty (#86 merged). `Coder` from pydantic-ai-harness is intentionally not used — its bundled shell is unrestricted and bypasses `ShellGuard`; the stack composes `LocalWorkspace` + `RepoContext` + `FileSystem` + `Shell` + `Permissions` + `ShellGuard` itself. Code Mode (`CodeMode`) added behind `code_mode_enabled` — read-only tools tagged `code_mode=True` batch behind a single `run_code` tool in a Monty sandbox; approval-gated tools stay as regular deferred calls needing the admin's Approve/Deny card. `ipython_code_mode`, `smart_search`, `macroscope`, `capability_creation`, `pydantic_ai_docs` deferred to later stages.

Later (cloud): mounts (FUSE; `rclone nfsmount` on macOS), scheduled or saved syncs, encrypting the rclone config with the OS keyring (§7), uploads to a remote without staging the whole file on the server first, Range requests for seeking in remote videos, and stopping an orphaned `rclone rcd` if Athena is killed (`SIGKILL` leaves it running).

Later (shares): a size limit for upload links, per-file audit of WebDAV changes, locks that survive a restart, WebDAV for more than one account.

Later (files): folder uploads (drag a folder), resumable uploads across page reloads, search, and SMB/NFS shares.

Later: switches for package installs and the assistant's shell in system settings (§7), next to the terminal's. Proxying the terminal WebSocket in `next dev` hasn't been checked; use the release build to work on it.

Later: a CI check that `themes.css` matches the registry (needs network; run `pnpm gen:theme` after shadcn upgrades for now), and switching shadcn styles at runtime (§5.4).

Later: auto-refreshing catalogs on a schedule, stripping missing host devices from imported apps, and Docker Hub login for pulls (rate limits).

Later: per-container stats, verifying temperatures on a real Linux host, importing existing compose projects not created by Athena, and Windows path translation for WSL bind mounts.

## Open questions

- None. (The first AI provider question was settled in M7: no default; Ollama is offered when detected.)
- QA review (#94, PR #94): full repo check done — four bugs fixed (assistant shell dual `run_command` registration, raw SQL DELETE in `delete_app`, upload disk-space check missing partial bytes, orphaned `docker logs -f` processes) and an e2e test suite added under `scripts/e2e/` (apps, files, shares, packages, assistant, terminal, settings, cloud). Verified: 506 server tests passed, ruff/format clean, check-docs clean, pre-push checks all green. Nothing left open.

## Just done

- Frontend design toolkit: installed the Anthropic `frontend-design` skill in `.agents/skills/` and locked it in `skills-lock.json`; added a frontend design and quality section to AGENTS.md (intentional art direction, shadcn-first primitives, theme tokens only, one active decorative element max, reduced motion, visible keyboard focus, responsive breakpoints 1440/768/390). MCP servers (shadcn, next-devtools, playwright, context7) were already configured in `.mcp.json`. PR #100 opened with auto-merge on; docs check passes (336 names in 13 files exist).

## Blockers

- None. The first release (release-please PR #3, `RELEASE_PLEASE_TOKEN` is set) is on hold: the maintainer merges it once the plan under **Next** is complete. Agents: don't merge it or turn on its auto-merge.
- Pipeline on main: E2E install + smoke failed on all platforms because M7 part C added an optional AI step to `/setup` after account creation and the smoke test never dismissed it. Fixed by PR #90 (#90 merged; click "Skip for now" after account creation). CI on main is green.
