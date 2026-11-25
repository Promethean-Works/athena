# Athena status

_Shared handoff log for every coding agent. Update it at the end of each session (see AGENTS.md → Handoff)._

**Current milestone:** M8, automation (cron and webhook triggers, MCP server, Automation UI): parts A–D shipped in #114. M7 (the AI assistant, §4.5) is done except part D stage 3 (see **Next**).

Finished work is in `docs/HISTORY.md` (read it only when needed). When you finish something, add a bullet there with the PR number and remove it below.

## In progress

- Self-update (`docs/specs/self-update.md`): all 4 parts done (part 4: backup first + interrupted banner). Not verified: Fedora, hand failure cases, real UI update (E2E smoke), a real backup-then-update. Follow-up: CLI backup step and `--no-backup` (needs a CLI path into the backup code).
- Backup (`docs/specs/backup.md`): part 1 (#215) needs `athena-host-test`. Part 2: 2a-2c (#216, #244, #247) and 2d done; `schedule` runs in part 4. Part 4 (#256) done. 2d not run against real runtime/volumes.
- HTTPS (`docs/specs/https.md`): all 4 parts done (#192, #196, #199, #203). Not verified: real Let's Encrypt/Cloudflare, trusting CA on real devices. Renewal/error live in memory only (restart forgets). Follow-up: own-certificate upload.
- Settings file (`docs/specs/settings-file.md`): part 1 in review; next, part 2.
- Agent orchestration (`docs/specs/agent-orchestration.md`): parts 1–2 done. Next: a happy-path trial from `main` (`/orchestrate`, `start --issue-file`), then part 3 (PR, CI watch).
- Windows E2E flake: `GET /api/containers` sometimes 500s under the service (`WinError 6`, see gotchas/windows.md).
- M7 D stage 2 follow-up ideas: show delegate tool calls nested; Settings → AI page; warn on small Ollama context; phone waiting question card below plan bar.
- Dashboard follow-ups: touch dragging on phone; app "update available" badge (`AppOut` has no such field).
- Webhook app restart took 10 min, `GET /api/automation/jobs` hung (Colima slow; rerun 10 s): does a run block the DB?
- Agent tooling: after merge, run `node scripts/agents-setup.mjs` (Hermes guard hook, denies, aliases) and `hermes mcp remove github`; approve Hermes hook once.
- Fix the ESLint config: `pnpm lint` skips `apps/web` `.tsx` (gotchas/web.md).
- Not yet verified for real: Windows terminal (ConPTY + PowerShell) beyond CI's pty tests, container shell through Docker in WSL.
- Not yet verified for real: other Linux system managers' install/uninstall (dnf, pacman, zypper, apk; apt checked in Lima VM, see #26) and every Windows manager (hand-written fixtures; CI runs choco/winget reads on Windows).
- Not yet verified in browser: `/files/smb` (#104), compose variant picker (#109), cloud wizard (#97) and remote cards (#92) with real rclone remote.
- Catalog smoke test (#169, #172, fixes #173–#176): every store app installed for real on macOS arm64 (Colima); 135/199 passed at first, rest fixed or marked `smoke: skip` (GPU, accounts, 12–16 GB RAM: ragflow, indextts). Next: run `Catalog smoke` workflow for `--all` on amd64/arm64. Logins/real use not verified.
- Tunnel follow-ups (#150): ngrok service files hold `${NGROK_AUTHTOKEN}` placeholder; Cloudflare quick tunnel tested (macOS); not yet: named tunnels, ngrok, Tailscale, Windows; service files need `/etc/cloudflared/config.yml`.
- models.dev providers left out (pydantic-ai needs their SDK): watsonx, GitLab, SAP AI Core, gateways. Google Vertex in (`google-vertex`, service-account key; not tried against real Vertex).
- **Raspberry Pi phase-1 memory fix**: lazy-load assistant stack (PR #265). Assistant imports (pydantic-ai, ~200 MB) moved to on-demand; startup RSS ~191 MB vs ~293 MB with full stack. All 376 tests pass.

## Next

**Release 0.1.0:** `docs/plans/release-0.1.0.md` lists every Must/Should item and the release checklist; decisions are recorded at its end (backup in, no 2FA, rc first). Work the Must items before new features.

M7 part D stage 3 (design §4.5 Parts): extras with outside services.
- Browser (#89): **blocked**. `pydantic-ai-harness[browser-use]==0.68.0` pins `browser-use` → `google-genai==1.65.0`, which conflicts with `pydantic-ai-slim[google]>=2.68.0` (`google-genai>=2.30.0`). Needs a harness release whose `browser-use` extra allows `google-genai>=2.30.0`; then unpin `pydantic-ai-harness` in `apps/server/pyproject.toml`. The toggle does nothing until then.
- Durable execution (D.6): turns run inside pgtask tasks against Postgres when `durable_execution_enabled` is on and `ATHENA_DURABLE_EXECUTION_DATABASE_URL` is set, checkpointing each model request and tool call; without them turns run inline as before. A real Postgres connection is tested; a crash/kill/resume flow isn't yet.
- Coding stack (D.7): foundation, file write/edit behind approval cards, shell behind `ShellGuard`, and Code Mode are done (see HISTORY). `Coder` from pydantic-ai-harness is intentionally not used: its bundled shell is unrestricted and bypasses `ShellGuard`. Deferred to later stages: `ipython_code_mode`, `smart_search`, `macroscope`, `capability_creation`, `pydantic_ai_docs`.

Raspberry Pi fixes and features from the competitor review: `docs/plans/improvements.md` (phase 1 fixes broken things: cloudflared download, store apps by host arch, broken catalog images, 32-bit install check, arm64 CI).

Later ideas (no milestone yet) are in `docs/design/milestones.md` → Backlog.

## Open questions

- None.

## Blockers

- None. The first release (release-please PR #3, `RELEASE_PLEASE_TOKEN` is set) is on hold: the maintainer merges it once every Must item in `docs/plans/release-0.1.0.md` is ticked. Agents: don't merge it or turn on its auto-merge.
