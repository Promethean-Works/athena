# Agent tooling

_How the coding agents (Claude Code, OpenCode, Hermes Agent) are set up for this repo. Read this when you change agent tooling (MCP servers, skills, generated agent config) or set up an agent on a new machine. Day-to-day work doesn't need it._

## One source of truth

Everything agent-related has one source of truth in the repo. Each agent reads it either directly or through a link or generated file.

| What | Source of truth | Claude Code | OpenCode | Hermes Agent |
|---|---|---|---|---|
| Instructions | `AGENTS.md` | `CLAUDE.md` imports it | reads `AGENTS.md` | reads `AGENTS.md` |
| Skills | `.agents/skills/` | `.claude/skills` → symlink | reads `.agents/skills` | reads `.agents/skills` after `hermes skills trust` |
| MCP servers | `.mcp.json` | reads it | `opencode.json` (generated) | `~/.hermes/config.yaml` (snippet generated) |
| Browser-check subagent | `scripts/agents-sync.mjs` | `.claude/agents/ui-verify.md` (generated) | `ui-verify` in `opencode.json` (generated) | none |
| Project state | `docs/STATUS.md` (finished work: `docs/HISTORY.md`) | ← | ← | ← |
| Lessons, gotchas, commands | `docs/AGENT-NOTES.md` | ← | ← | ← |

## MCP servers (`.mcp.json`)

- `shadcn`: browse, search and install registry items.
- `next-devtools`: Next.js docs and runtime diagnostics while `pnpm dev` runs.
- `playwright`: a headless browser with an in-memory profile, for UI verification (navigate, accessibility snapshots, screenshots in `.playwright-mcp/`, clicks, console, network, resize). It runs with `--snapshot-mode none` to save tokens: actions don't return the page, so call `browser_snapshot` when you need it. It uses the system Chrome; on a machine without Chrome, add `--browser firefox` or install Chrome.
- `context7`: current docs and examples for any library (FastAPI, SQLModel, Alembic, wsgidav, xterm.js, Base UI, pydantic-ai, rclone…). It works without an API key (rate-limited); set `CONTEXT7_API_KEY` for higher limits.

## Skills (`.agents/skills/`)

Third-party ones are pinned in `skills-lock.json`: `shadcn`, `building-pydantic-ai-agents`, `pydantic-ai-harness`, `pydantic`. The project's own skills are listed in `AGENTS.md` → Agent tooling.

## Changing tooling

- *Add an MCP server:* edit `.mcp.json`, then run `node scripts/agents-sync.mjs` to regenerate `opencode.json`, `.claude/agents/ui-verify.md` and the Hermes snippet. Never edit the generated parts by hand: the `mcp` block of `opencode.json`, its `playwright_*` permission rules and `ui-verify` agent, and the Claude Code subagent file. Which tools each agent gets is set in `scripts/agents-sync.mjs` (`UNUSED_TOOLS`, `OPENCODE_SUBAGENT_ONLY`). CI runs `--check`.
- *Add a third-party skill:* `npx skills add <owner/repo> --skill <name> -a claude-code -y`. It lands in `.agents/skills/` through the symlink and is recorded in `skills-lock.json`.
- *Add a project skill:* create `.agents/skills/<name>/SKILL.md` with `name` and `description` frontmatter (the description is what agents see before loading the skill: say what it does and when to use it), and add it to the list in `AGENTS.md`. `scripts/check-docs.mjs` checks every name the skill mentions.
  - Hermes's scanner also hides **our own** skills when they contain `curl … | python3` (rated critical "supply chain"), even when Python only parses JSON. In skills, use `jq` or save to a file first. `sudo`, `uv run` and systemd mentions are only medium and don't hide a skill. To check a skill before committing: `PYTHONPATH=~/.hermes/hermes-agent ~/.hermes/tools/python-3.14*/bin/python3 -c "from pathlib import Path; from tools.skills_guard import scan_skill; print(scan_skill(Path('.agents/skills/<name>'), source='project').verdict)"` should print `safe`.
- *Restore skills on a new machine:* `npx skills experimental_install`.

## One-time setup per agent

- **Every agent and person:** `git config core.hooksPath .githooks` (required for agents). It turns on both hooks: pre-commit refuses commits on `main` or in the base checkout, pre-push runs the checks the push touches.
- **Claude Code:** nothing else to do. On Windows, enable symlinks in git (`git config core.symlinks true` with Developer Mode on) so `.claude/skills` works.
- **OpenCode:** nothing to do. `opencode.json` is committed. To save tokens, the main agent doesn't get the Playwright tools: browser checks go to the `ui-verify` subagent, which follows the `athena-ui-verify` skill.
- **Hermes Agent:** run `node scripts/agents-sync.mjs --hermes`. It trusts this repo's skills (`hermes skills trust`) and adds any missing MCP servers to `~/.hermes/config.yaml` through `hermes mcp add`. For servers already there, it re-applies their `args` and tool filters (unused tools are left out to save tokens) through `hermes config set`, a no-op when unchanged, so flag changes in `.mcp.json` reach Hermes; it leaves everything else alone. Then restart Hermes or run `/reload-mcp`. `--hermes-print` only prints the YAML block.
  - Known gap: Hermes's skill scanner rates `pydantic-ai-harness` as "dangerous" and hides it. That's a false positive from its docs mentioning `~/.ssh`, `os.environ` and command denylists. Hermes agents should read `.agents/skills/pydantic-ai-harness/SKILL.md` directly when working on the assistant.

## Token budget

In the repo:

- **What every session pays for is kept small:** STATUS is capped at 8 KB by `scripts/check-docs.mjs` (finished work goes to `docs/HISTORY.md`); `scripts/check.sh` is quiet without a terminal; Playwright runs with `--snapshot-mode none` (snapshot only when you need to read the page); `.ignore` keeps lockfiles, CHANGELOG and the generated theme files out of ripgrep searches; Claude Code caps Bash and MCP output at 20k (`.claude/settings.json` → `env`) and OpenCode caps tool output at 20 KB (`opencode.json` → `tool_output`, the rest is saved to disk). Pipe long commands through `tail` or `grep` yourself too. This file is separate from AGENTS.md because only tooling changes need it.
- **Dependencies ship their own agent files.** pydantic-ai has `CLAUDE.md`/`AGENTS.md` files in `.venv/…/pydantic_ai/` (about 40 KB, written for pydantic-ai's own contributors), and Next and recharts ship `AGENTS.md` in `node_modules`. Claude Code loads a subfolder's `CLAUDE.md` as soon as it reads a file there, which happens when you read pydantic-ai's source. `.claude/settings.json` → `claudeMdExcludes` skips them. <!-- docs-check: ignore -->
- **MCP tool definitions cost tokens on every request in OpenCode and Hermes** (Claude Code loads them on demand). Measured: Playwright 25 tools ≈ 21k characters, next-devtools ≈ 5.7k, context7 ≈ 5.2k, shadcn ≈ 4.3k. So `scripts/agents-sync.mjs` gives Playwright only to OpenCode's `ui-verify` subagent (a `playwright_*` deny rule globally, allow in the agent; agent rules come after global ones and the last match wins), and writes Hermes `tools.exclude` filters for unused tools. OpenCode 2.x already routes MCP tools through Code Mode by default (`codemode: true`). Hermes' `lazy: true` only delays connecting; the tools are still registered, so it saves memory, not tokens.

Per person, so not committed:

- **A cheaper model for browser checks.** UI verification is many small, repetitive steps. Claude Code's generated `ui-verify` subagent (`.claude/agents/ui-verify.md`) uses `model: sonnet`, and its output stays out of the main context. OpenCode needs a `provider/model` id, which depends on your provider, so set it in your own `~/.config/opencode/opencode.json` (OpenCode merges it with the project file): `{"agents": {"ui-verify": {"model": "<provider>/<model>"}}}`.
- **Optional tools, tried but not required:**
  - [RTK](https://github.com/rtk-ai/rtk) (Apache-2.0): a hook that shortens the output of shell commands like `git`, `gh`, `pytest` and `pnpm` before the agent reads it. Works with Claude Code and OpenCode. It only covers shell commands (not built-in Read or Grep), and it runs your commands through a third-party binary. `scripts/check.sh` is already quiet without a terminal, so the gain here is mostly on `git`, `gh` and ad-hoc test runs.
  - [TokenEconomizer](https://github.com/microsoft/TokenEconomizer) (Apache-2.0): learns repo facts, prunes unused tools, and nudges an agent stuck in a failure loop. The first two overlap with `athena-recipes`, the command cheat sheet and the MCP scoping above. What it learns stays in `~/.tokeneconomizer`, so anything another agent needs must still go in the repo.
  - Installing them (done on the maintainer's Mac, 2026-11-15):
    - RTK: `brew install rtk`, then `rtk init -g --opencode --hook-only --no-patch` and `rtk init --agent hermes --hook-only --no-patch`. `--hook-only` skips `RTK.md`, an instructions file every session would pay for; the hook rewrites commands without it. `--no-patch` only prints the Claude Code hook (`"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "rtk hook claude"}]}]` in `~/.claude/settings.json`), so add it by hand. `rtk gain` shows the savings. <!-- docs-check: ignore -->
    - TokenEconomizer: follow its README per agent (Claude Code plugin, OpenCode `~/.config/opencode/plugins/` symlink, Hermes `~/.hermes/plugins/` symlink). It needs Python 3.10+: macOS's `python3` is 3.9, so set `TE_PYTHON` (in `~/.claude/settings.json` → `env` for Claude Code, in your shell profile for OpenCode). It also needs a `claude` CLI on `PATH` for its own model calls; with only the VS Code extension, point a wrapper at the extension's `resources/native-binary/claude`. Tool pruning writes `.claude/settings.local.json`, which is git-ignored. `~/.tokeneconomizer/bin/te doctor` checks the setup. <!-- docs-check: ignore -->
  - Not used: caveman (terse replies; measured at a few percent of a session's tokens, and the "Short replies" rule in `AGENTS.md` gets most of it).
