# Athena status

_Shared handoff log for every coding agent. Update it at the end of each session (see AGENTS.md → Handoff)._

**Current milestone:** M7, the AI assistant (§4.5). Parts A, B and C are done; part D (the rest of pydantic-ai-harness): stage 1 and stage 2 done (#65–#73 merged). Stage 3 next.

## Done

Finished work is in `docs/HISTORY.md` (read it only when you need a feature's background). When you finish something, add a short bullet there with the PR number and take it out of In progress below.

## In progress

- M7 D stage 2 complete: PRs 1–5 (#65–#73) all merged (#73 = `step_persistence` + `conversation_search` + `media`). Follow-up ideas: show a delegate's own tool calls nested under its row; a Settings → AI page to see and clear notes and to list or upload skills; warn in the UI when Ollama runs a model with a context too small for Athena's prompt and tools (see AGENT-NOTES → Assistant); on a phone, a waiting question card sits mostly below the plan bar and prompt until you scroll.
- MCP server support for the assistant added: `McpStdio` and `McpHttp` server configs in `ai_settings.mcp_servers` (Settings → AI), built as fresh `MCPToolset`s per turn and wired into the chat agent, investigator (delegation) and `run_workflow` helpers. Audit logs MCP server changes.
- Not yet verified for real: the Windows terminal (ConPTY plus PowerShell) beyond CI's pty tests, and the container shell through Docker in WSL.
- Not yet verified for real: the other Linux system managers' install/uninstall (dnf, pacman, zypper, apk; apt was checked in a Lima VM, see #26 in HISTORY) and every Windows manager (hand-written fixtures; CI runs choco/winget reads on Windows).

## Next

M7 part D stage 3 (design §4.5 Parts): extras with outside services — web research (`exa`, `youdotcom`, `keenable`, `researcher`; API keys), a browser (`playwright` / `browser_use`), and second-model reviews (`approval_reviewer`, `tool_call_judge`, `trajectory_judge`). Then sandboxes and other workspaces, hosted integrations, durable execution and operations, and the coding stack.

Later (cloud): mounts (FUSE; `rclone nfsmount` on macOS), scheduled or saved syncs, encrypting the rclone config with the OS keyring (§7), uploads to a remote without staging the whole file on the server first, Range requests for seeking in remote videos, and stopping an orphaned `rclone rcd` if Athena is killed (`SIGKILL` leaves it running).

Later (shares): a size limit for upload links, per-file audit of WebDAV changes, locks that survive a restart, WebDAV for more than one account.

Later (files): folder uploads (drag a folder), resumable uploads across page reloads, search, and SMB/NFS shares.

Later: switches for package installs and the assistant's shell in system settings (§7), next to the terminal's. Proxying the terminal WebSocket in `next dev` hasn't been checked; use the release build to work on it.

Later: a CI check that `themes.css` matches the registry (needs network; run `pnpm gen:theme` after shadcn upgrades for now), and switching shadcn styles at runtime (§5.4).

Later: auto-refreshing catalogs on a schedule, stripping missing host devices from imported apps, and Docker Hub login for pulls (rate limits).

Later: per-container stats, verifying temperatures on a real Linux host, importing existing compose projects not created by Athena, and Windows path translation for WSL bind mounts.

## Open questions

- None. (The first AI provider question was settled in M7: no default; Ollama is offered when detected.)

## Blockers

- None. The first release (release-please PR #3, `RELEASE_PLEASE_TOKEN` is set) is on hold: the maintainer merges it once the plan under **Next** is complete. Agents: don't merge it or turn on its auto-merge.
