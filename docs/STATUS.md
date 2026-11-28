# Athena status

_Shared handoff log for every coding agent. Update it at the end of each session (see AGENTS.md → Handoff)._

**Current milestone:** M8, automation (cron and webhook triggers, MCP server, Automation UI): parts A–D shipped in #114. M7 (the AI assistant, §4.5) is done except part D stage 3 (see **Next**).

Finished work is in `docs/HISTORY.md` (read it only when needed). When you finish something, add a bullet there with the PR number and remove it below.

## In progress

- User folders (`docs/specs/user-folders.md`): PR open. Next: back up `users/` (in no snapshot; a restore leaves them in `athena.before-restore-*`), then pentest pass 2.
- Package manager UI (`docs/specs/package-manager-ui.md`): merged (#327, #328). Not verified: real MacPorts/Homebrew/Scoop/Chocolatey installs; hand-written MacPorts/winget/scoop/choco fixtures.
- Multi-user (`docs/specs/multi-user.md`): PR open. Follow-ups: per-user folders, user assistant.
- Onboarding wizard: built; see HISTORY for what is unverified.
- i18n (`docs/specs/i18n.md`): in one PR. Next: native review (all but pt-BR are machine-made), check populated pages, stable API error codes, the hard-coded-text lint rule.
- Network shares (#312 UI) + share-from-explorer (#317, `docs/specs/share-from-explorer.md`) built. Not verified: real sudo/UAC, real `rclone mount` + FUSE, real mounts. Sub-folder sharing built; browser-checked on a faked host.
- Self-update (`docs/specs/self-update.md`): all 4 parts done (part 4: backup first + interrupted banner). Not verified: Fedora, hand failure cases, real UI update (E2E smoke), a real backup-then-update. Follow-up: CLI backup step and `--no-backup` (needs a CLI path into the backup code).
- Backup (`docs/specs/backup.md`): part 1 (#215) needs `athena-host-test`. Part 2: 2a-2c (#216, #244, #247) and 2d done; `schedule` runs in part 4. Part 4 (#256) done. 2d not run against real runtime/volumes.
- HTTPS (`docs/specs/https.md`): all 4 parts done (#192, #196, #199, #203). Not verified: real Let's Encrypt/Cloudflare, trusting CA on real devices. Renewal/error live in memory only (restart forgets). Follow-up: own-certificate upload.
- Settings file (`docs/specs/settings-file.md`): part 1 in review; next, part 2.
- Agent orchestration (`docs/specs/agent-orchestration.md`): parts 1–2 done. Next: a happy-path trial from `main` (`/orchestrate`, `start --issue-file`), then part 3 (PR, CI watch).
- Windows E2E flake: `GET /api/containers` sometimes 500s under the service (`WinError 6`, see gotchas/windows.md).
- M7 D stage 2 follow-ups: nest delegate tool calls; warn on small Ollama context; phone waiting-question card below the plan bar.
- Dashboard: touch dragging on phone; app "update available" badge (`AppOut` lacks the field).
- Webhook app restart took 10 min, `GET /api/automation/jobs` hung (slow Colima).
- Agent tooling: after merge, run `node scripts/agents-setup.mjs` and `hermes mcp remove github`; approve the Hermes hook once.
- Fix the ESLint config: `pnpm lint` skips `apps/web` `.tsx` (gotchas/web.md).
- Not verified: Windows terminal (ConPTY + PowerShell) beyond CI's pty tests; container shell in WSL.
- Not yet verified for real: other Linux system managers' install/uninstall (dnf, pacman, zypper, apk; apt checked in Lima VM, see #26) and every Windows manager (hand-written fixtures; CI runs choco/winget reads on Windows).
- Not verified in browser: compose variant picker (#109), cloud wizard (#97), remote cards (#92) with a real remote.
- Catalog smoke test (#169–#176): store apps installed on macOS arm64 (Colima); `smoke: skip` marks heavy ones. Next: `Catalog smoke` workflow (amd64/arm64).
- Tunnel follow-ups (#150): ngrok service files hold a `${NGROK_AUTHTOKEN}` placeholder; only a Cloudflare quick tunnel was tested.
- models.dev providers left out (SDK needed): watsonx, GitLab, SAP AI Core, gateways. Vertex untried.

## Next

**0.1.0 dry run (in progress):** installers now fetch pre-release wheels (`fix/installer-prerelease-wheel-name`). Still to do, by the maintainer: `prerelease: true` in `release-please-config.json` plus a `Release-As: 0.1.0-rc.1` footer (remove the flag before the real 0.1.0), merge the release PR, then `gh workflow run e2e.yml -f release_version=0.1.0-rc.1`.

**Release 0.1.0:** `docs/plans/release-0.1.0.md` lists every Must/Should item and the release checklist; decisions are recorded at its end (backup in, no 2FA, rc first). Work the Must items before new features.

M7 part D stage 3 (design §4.5 Parts): extras with outside services.
- Browser (#89): **blocked**. `pydantic-ai-harness[browser-use]==0.68.0` pins `browser-use` → `google-genai==1.65.0`, which conflicts with `pydantic-ai-slim[google]>=2.68.0` (`google-genai>=2.30.0`). Needs a harness release whose `browser-use` extra allows `google-genai>=2.30.0`; then unpin `pydantic-ai-harness` in `apps/server/pyproject.toml`. The toggle does nothing until then.
- Durable execution (D.6): turns run inside pgtask tasks against Postgres when `durable_execution_enabled` is on and `ATHENA_DURABLE_EXECUTION_DATABASE_URL` is set, checkpointing each model request and tool call; without them turns run inline as before. A real Postgres connection is tested; a crash/kill/resume flow isn't yet.
- Coding stack (D.7): foundation, file write/edit behind approval cards, shell behind `ShellGuard`, and Code Mode are done (see HISTORY). `Coder` from pydantic-ai-harness is intentionally not used: its bundled shell is unrestricted and bypasses `ShellGuard`. Deferred to later stages: `ipython_code_mode`, `smart_search`, `macroscope`, `capability_creation`, `pydantic_ai_docs`.

Raspberry Pi fixes and features from the competitor review: `docs/plans/improvements.md`.

Later ideas (no milestone yet) are in `docs/design/milestones.md` → Backlog.

## Open questions

- None.

## Blockers

- None. The first release (release-please PR #3, `RELEASE_PLEASE_TOKEN` is set) is on hold: the maintainer merges it once every Must item in `docs/plans/release-0.1.0.md` is ticked. Agents: don't merge it or turn on its auto-merge.
