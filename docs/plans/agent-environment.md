# Plan: a reproducible AI development environment

_Started 2026-11-19. Three PRs; tick them off here and in `docs/STATUS.md` as they merge._

Goal: every agent (Claude Code, OpenCode, Hermes Agent, Codex, Antigravity/Gemini, Copilot) gets the same instructions, skills, MCP servers, commands and safety settings from the repo, loads only what a task needs, and a reinstalled machine gets everything back with one command.

Scope decisions (maintainer, 2026-11-19): capture only Athena-relevant machine settings (not unrelated Hermes plugins; model and provider choices as opt-in templates, never keys); support Codex, Gemini and Copilot too; split the docs fully.

## PR 1 — `docs`: load agent docs on demand (done, #152)

- [x] `AGENTS.md` becomes a short router with a "Read when" table; the maintainer's working style moves into it.
- [x] `docs/AGENT-NOTES.md` → `docs/agents/commands.md` + `docs/agents/gotchas/<area>.md`; `docs/AGENT-TOOLING.md` → `docs/agents/tooling.md`.
- [x] `docs/mvp-design.md` → `docs/design/README.md` (index) + one file per section; references rewritten.
- [x] STATUS backlog → `docs/design/milestones.md` → Backlog.
- [x] `scripts/check-docs.mjs`: checks every `AGENTS.md`/`CLAUDE.md`/`GEMINI.md` and `docs/agents/`; size limits for files read every session.
- [x] `apps/server/CLAUDE.md` and `apps/web/CLAUDE.md` import their `AGENTS.md`: Claude Code reads only CLAUDE.md files once a root one exists, so it never loaded the app rules before. The other agents read nested `AGENTS.md` lazily or follow the router (see `docs/agents/tooling.md` → How each agent loads instructions).

## PR 2 — `build`: one-command machine setup (done, #154)

- `agents/user/`: templates for machine-level settings (no secrets; `{env:VAR}` references): the RTK hook and TokenEconomizer for each agent, OpenCode plugin links, Hermes trust/MCP/plugins, opt-in model/provider templates.
- `scripts/agents-setup.mjs` (`--check`, `--dry-run`): git hooks, skills restore, RTK and TokenEconomizer install (or the command to run), merging into user configs without overwriting, required env vars. A Claude Code `SessionStart` hook runs `--check`; other agents are told to by `AGENTS.md`. Installs and home-folder changes are confirmed with the maintainer first.
- `scripts/agents-sync.mjs` also generates Codex (`.codex/config.toml`), Antigravity, which replaced Gemini CLI in June 2026 (reads `AGENTS.md` and `.agents/skills/`; MCP in `.agents/mcp_config.json`) and Copilot (`.github/copilot-instructions.md`) config.
- `docs/agents/tooling.md` → "New machine".
- Area gotchas that load by themselves when a matching file is touched: Claude Code `.claude/rules/<area>.md` with `paths:`, Copilot `.github/instructions/<area>.instructions.md` with `applyTo`, both generated from one map in `scripts/agents-sync.mjs`.

## PR 3 — `feat`: shared workflows (done)

As built: skills `athena-next`, `athena-check-prs`, `athena-handoff`, `athena-review` with commands `/next`, `/check-prs`, `/handoff`, `/review-diff` (not `/review`: Claude Code's built-in), `/ship`; a `reviewer` subagent; no custom explorer (Claude Code and OpenCode have built-in ones); `scripts/session-start.mjs` prints STATUS and the setup check.


- Commands `/next`, `/check-prs`, `/ship`, `/handoff`, `/review`, defined once and generated per agent.
- Subagents `reviewer` (read-only, checks a diff against the rules) and `explorer` (cheap model), generated like `ui-verify`.
- `SessionStart` hook printing STATUS → In progress; gitleaks secret scan in pre-commit and CI; deny reading `.env*`, credentials and the data dir.
- Spec-first: `docs/specs/_template.md` and a recipe in `athena-recipes`; big features get a spec approved before code.

## Last — developer guide

- `docs/DEVELOPMENT.md`, linked from `README.md` and `CONTRIBUTING.md`: setting up a machine from scratch (clone, `agents-setup.mjs`, keys), what each agent gets, RTK and TokenEconomizer, the daily loop (worktrees, shared commands, checks, spec-first, handoff), and troubleshooting. Asked for by the maintainer on 2026-11-19.

