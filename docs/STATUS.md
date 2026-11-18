# Athena status

_Shared handoff log for every coding agent. Update it at the end of each session (see AGENTS.md → Handoff)._

**Current milestone:** M8, automation (cron + trigger-based jobs, MCP server, webhooks). M7 (the AI assistant, §4.5) is complete.

## Done

Finished work is in `docs/HISTORY.md` (read it only when you need a feature's background). When you finish something, add a short bullet there with the PR number and take it out of In progress below.

## In progress

- M7 D stage 2 follow-up ideas: show a delegate's own tool calls nested under its row; a Settings → AI page to see and clear notes and to list or upload skills; warn in the UI when Ollama runs a model with a context too small for Athena's prompt and tools (see AGENT-NOTES → Assistant); on a phone, a waiting question card sits mostly below the plan bar and prompt until you scroll.
- M8 A (automation foundation): done — durable triggers + job runs, cron scheduler, triggers/job routers, audit.
- M8 B (MCP server): done — streamable-HTTP MCP server at /api/mcp with session or bearer-token auth, tools for apps/capabilities/stats/automation. Verified with MCP handshake + tool-call tests.
- M8 C (webhooks): done — public POST /api/automation/webhook/{token} fires HTTP triggers (n8n path), no session needed. Verified with API tests.
- Next: M8 D Automation UI.
- Not yet verified for real: the Windows terminal (ConPTY plus PowerShell) beyond CI's pty tests, and the container shell through Docker in WSL.
- Not yet verified for real: the other Linux system managers' install/uninstall (dnf, pacman, zypper, apk; apt was checked in a Lima VM, see #26 in HISTORY) and every Windows manager (hand-written fixtures; CI runs choco/winget reads on Windows).
- Not yet verified in a browser: the cloud add-storage wizard (#97) and the cloud remote cards (#92), with a real rclone remote.

Standalone (open PR, not M7): compose variants per catalog app is PR #109 (open, auto-merge squash, CI pending). A store app folder may hold several compose files — compose.yaml is the default variant and each compose.<slug>.yaml sibling is another variant, each with its own install-form env fields. FreshRSS gains compose.postgres.yaml (PostgreSQL); defaults stay SQLite. No server/UI changes beyond the general variant support (select-free). Browser pass not yet done — the web release build fails on a pre-existing theme-provider typecheck error that also fails on untouched main.

## Next

M7 part D stage 3 (design §4.5 Parts): extras with outside services.
- Browser (#89): **blocked**. `pydantic-ai-harness[browser-use]==0.68.0` pins `browser-use` → `google-genai==1.65.0`, which conflicts with `pydantic-ai-slim[google]>=2.68.0` (`google-genai>=2.30.0`). Needs a harness release whose `browser-use` extra allows `google-genai>=2.30.0`; then unpin `pydantic-ai-harness` in `apps/server/pyproject.toml`. The toggle does nothing until then.
- Durable execution (D.6): turns run inside pgtask tasks against Postgres when `durable_execution_enabled` is on and `ATHENA_DURABLE_EXECUTION_DATABASE_URL` is set, checkpointing each model request and tool call; without them turns run inline as before. A real Postgres connection is tested; a crash/kill/resume flow isn't yet.
- Coding stack (D.7): foundation, file write/edit behind approval cards, shell behind `ShellGuard`, and Code Mode are done (see HISTORY). `Coder` from pydantic-ai-harness is intentionally not used: its bundled shell is unrestricted and bypasses `ShellGuard`. Deferred to later stages: `ipython_code_mode`, `smart_search`, `macroscope`, `capability_creation`, `pydantic_ai_docs`.

Later (cloud): mounts (FUSE; `rclone nfsmount` on macOS), scheduled or saved syncs, encrypting the rclone config with the OS keyring (§7), uploads to a remote without staging the whole file on the server first, Range requests for seeking in remote videos, and stopping an orphaned `rclone rcd` if Athena is killed (`SIGKILL` leaves it running).

Later (shares): a size limit for upload links, per-file audit of WebDAV changes, locks that survive a restart, WebDAV for more than one account, a web UI for SMB shares (server side is #95, Linux only), and NFS shares.

Later (files): folder uploads (drag a folder), resumable uploads across page reloads, and search.

Later: switches for package installs and the assistant's shell in system settings (§7), next to the terminal's. Proxying the terminal WebSocket in `next dev` hasn't been checked; use the release build to work on it.

Later: a CI check that `themes.css` matches the registry (needs network; run `pnpm gen:theme` after shadcn upgrades for now), and switching shadcn styles at runtime (§5.4).

Later: auto-refreshing catalogs on a schedule, stripping missing host devices from imported apps, and Docker Hub login for pulls (rate limits).

Later: per-container stats, verifying temperatures on a real Linux host, importing existing compose projects not created by Athena, and Windows path translation for WSL bind mounts.

## Open questions

- None.

## Blockers

- None. The first release (release-please PR #3, `RELEASE_PLEASE_TOKEN` is set) is on hold: the maintainer merges it once the plan under **Next** is complete. Agents: don't merge it or turn on its auto-merge.
