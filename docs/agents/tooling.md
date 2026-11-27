# Agent tooling

_How the coding agents (Claude Code, OpenCode, Hermes Agent, oh-my-pi) are set up for this repo. Read this when you change agent tooling (MCP servers, skills, generated agent config, guards) or set up a machine. Day-to-day work doesn't need it._

## One source of truth

Everything agent-related has one source in the repo. Each agent gets it the way that agent does natively: it reads the file itself, or `scripts/agents-sync.mjs` writes that agent's own config from it (CI runs `--check`, so generated files can't drift and leftover ones are reported).

| What | Source | How each agent gets it |
|---|---|---|
| Instructions | `AGENTS.md` (router) + `apps/*/AGENTS.md` | Claude Code through `CLAUDE.md` files that import them; the others read `AGENTS.md` |
| Project state at start | `docs/STATUS.md` | Claude Code `SessionStart` hook (`scripts/session-start.mjs`, also runs the setup check); OpenCode `instructions`; oh-my-pi `.omp/AGENTS.md` imports it; Hermes follows `AGENTS.md` → Every session |
| Area gotchas | `docs/agents/gotchas/<area>.md` | `AREA_RULES` → Claude Code `.claude/rules/<area>.md` (`paths:`) and oh-my-pi `.omp/rules/<area>.md` (`globs:`, in its rulebook) point at them; others follow the router |
| Skills | `.agents/skills/` (third-party ones pinned in `skills-lock.json`) | Claude Code through the `.claude/skills` symlink; OpenCode and oh-my-pi read it; Hermes once trusted, and in worktrees through `skills.external_dirs` |
| MCP servers | `.mcp.json` | Claude Code and oh-my-pi read it; generated `opencode.json`; Hermes through `agents-sync.mjs --hermes` |
| Subagents (`ui-verify`, `reviewer`; when to use them: `docs/agents/subagents.md`) | `OPENCODE_SUBAGENT_ONLY`, `SUBAGENTS` in `scripts/agents-sync.mjs` | `.claude/agents/` (skill preloaded with `skills:`), `.omp/agents/` (`autoload-skills:`; omp uses its bundled `reviewer`), `agents` in `opencode.json` |
| Commands (`/next`, `/check-prs`, `/review-diff`, `/handoff`, `/ship`, `/security-audit`) | The `athena-*` skills; `COMMANDS` in `scripts/agents-sync.mjs` | `.claude/commands/` (`/review-diff` forks into `reviewer`; oh-my-pi reads them too), `commands` in `opencode.json`, Hermes `quick_commands` aliases |
| Guards: secret reads, release files, base checkout, pushes | `SECRET_GLOBS`, `SECRET_DIRS`, `PROTECTED_FILES`, `DENIED_COMMANDS` and `verdict()` in `scripts/agent-guard.mjs` | Claude Code deny rules + `PreToolUse` hook; OpenCode `read`/`edit`/`shell` deny rules; oh-my-pi `bash.patterns` + `.omp/extensions/athena.ts` (calls `verdict()`); Hermes `approvals.deny` + `pre_tool_call` hook |
| Worktrees | Each agent's default (AGENTS.md → Git workflow) | Claude Code `.claude/worktrees/`, Hermes `.worktrees/` (both git-ignored), OpenCode its data dir, oh-my-pi `~/.omp/wt` (`worktree.onStart: create`) |
| Secret scanning | `.gitleaks.toml` | `scripts/pre-commit.sh` (staged changes) and CI's repo checks (the tree) |
| Machine settings | `scripts/agents-setup.mjs` + templates in `.agents/user/` | Applied to the home folder by `node scripts/agents-setup.mjs` (see [New machine](#new-machine)) |

## How each agent loads instructions

Checked against each tool's docs and the installed versions (Claude Code 2.1, OpenCode 2.3, Hermes 0.23 from its source, omp 19.1) on 2026-11-24. This is why `AGENTS.md` is a router and the app folders have both files.

| Agent | Reads | Subfolders |
|---|---|---|
| Claude Code | `CLAUDE.md` only, once a root one exists (so the root and each app `CLAUDE.md` import `@AGENTS.md`); `.claude/rules/` with `paths:` when a matching file is read or edited | A subfolder `CLAUDE.md` loads the first time a file there is read or edited <!-- docs-check: ignore --> |
| OpenCode (V2 config: plural `agents`, `commands`, `permissions` list) | `AGENTS.md` (`CLAUDE.md` only where a folder has none), then `instructions` | Loaded when a file below is read or listed |
| Hermes Agent | One kind only, first found: `.hermes.md`, `AGENTS.md`, `CLAUDE.md`, `.cursorrules`. `AGENTS.md` files merge from the git root to the cwd. Never add a `.hermes.md`: it would replace `AGENTS.md` | Added to the tool result the first time a path there is touched (32k cap) | <!-- docs-check: ignore -->
| oh-my-pi (`omp`) | `.omp/AGENTS.md` over `AGENTS.md` at the same level (hence the import), `@` imports, `.omp/rules/` as a rulebook (read on demand) | Deeper `AGENTS.md` files are listed as pointers to read before editing there |

## Guards (`scripts/agent-guard.mjs`)

The rules every agent gets, from one file: no reading secret files (keys, `.env`, `.dev-data/`), no editing `CHANGELOG.md`/`version.txt` (release-please), no editing in the base checkout (it stays on `main`; set `ATHENA_ALLOW_BASE_EDIT=1` to do it on purpose), and no push to `main` or force push. Each agent enforces them natively where it can (deny rules, `bash.patterns`, `approvals.deny`); file tools where an agent has no per-path setting go through the script: Claude Code's `PreToolUse` hook and Hermes's `pre_tool_call` hook run it (stdin JSON, answer in that agent's format), and omp's extension imports `verdict()`. It lets the call through on any error, so a broken guard never blocks a session (both hooks fail open; `--hermes` only adds Hermes's once the script is on `main`). `node scripts/agent-guard.mjs --self-test` runs as part of `agents-sync.mjs --check` (CI).

Not covered: shell commands that write files (`sed -i`, redirects) and pushes spelled differently (`git -C . push`). The pre-commit hook and GitHub's branch protection are the backstop. OpenCode has no guard hook: its V2 plugin API for blocking a tool call isn't documented yet, so it gets the deny rules only.

## MCP servers (`.mcp.json`)

- `shadcn`: browse, search and install registry items.
- `next-devtools`: Next.js docs and runtime diagnostics while `pnpm dev` runs.
- `playwright`: a headless browser with an in-memory profile, for UI verification (navigate, accessibility snapshots, screenshots in `.playwright-mcp/`, clicks, console, network, resize). It runs with `--snapshot-mode none` to save tokens: actions don't return the page, so call `browser_snapshot` when you need it. It uses the system Chrome; on a machine without Chrome, add `--browser firefox` or install Chrome.
- `context7`: current docs and examples for any library (FastAPI, SQLModel, Alembic, wsgidav, xterm.js, Base UI, pydantic-ai, rclone…). It works without an API key (rate-limited); set `CONTEXT7_API_KEY` for higher limits.
- No GitHub server: every skill uses `gh`, which needs no token in the environment and costs no tool definitions (oh-my-pi also has a built-in `github` tool, `github.enabled`).

## Skills (`.agents/skills/`)

Third-party ones are pinned in `skills-lock.json`: `shadcn`, `building-pydantic-ai-agents`, `pydantic-ai-harness`, `pydantic`. The project's own skills are routed from `AGENTS.md` → Read when. All skills are committed, so a clone has them. Every agent can also run a skill directly (`/athena-next`).

## Changing tooling

- _Add an MCP server:_ edit `.mcp.json`, then run `node scripts/agents-sync.mjs` to regenerate every agent's copy (and `--hermes` to update Hermes). Never edit generated files or parts by hand: the `mcp`, `permissions`, `agents`, `commands`, `instructions`, `share` and `watcher` parts of `opencode.json`, the `$schema`, deny rules and `PreToolUse` guard hook in `.claude/settings.json`, and every file in `.claude/agents/`, `.claude/commands/`, `.claude/rules/` and `.omp/`. Which tools each agent gets is set in `scripts/agents-sync.mjs` (`UNUSED_TOOLS`, `OPENCODE_SUBAGENT_ONLY`).
- _Change a guard:_ edit the lists or `verdict()` in `scripts/agent-guard.mjs` (add a `--self-test` case, run by `agents-sync.mjs --check`), then run `node scripts/agents-sync.mjs` (and `--hermes`).
- _Add a third-party skill:_ `npx skills add <owner/repo> --skill <name> -a claude-code -y`. It lands in `.agents/skills/` through the symlink and is recorded in `skills-lock.json`.
- _Add a project skill:_ create `.agents/skills/<name>/SKILL.md` with `name` and `description` frontmatter (the description is what agents see before loading the skill: say what it does and when to use it), and add it to the list in `AGENTS.md`. `scripts/check-docs.mjs` checks every name the skill mentions.
  - Hermes's scanner also hides **our own** skills when they contain `curl … | python3` (rated critical "supply chain"), even when Python only parses JSON. In skills, use `jq` or save to a file first. `sudo`, `uv run` and systemd mentions are only medium and don't hide a skill. To check a skill before committing: `PYTHONPATH=~/.hermes/hermes-agent ~/.hermes/tools/python-3.14*/bin/python3 -c "from pathlib import Path; from tools.skills_guard import scan_skill; print(scan_skill(Path('.agents/skills/<name>'), source='project').verdict)"` should print `safe`.
- _Add a subagent or a shared command:_ a subagent goes in `SUBAGENTS` (with the skill that holds its procedure), a command in `COMMANDS` as an alias for a skill; run `node scripts/agents-sync.mjs`. Don't name a command like a built-in (`/review` is Claude Code's).
- _Add a gotchas area that loads by itself:_ add the file under `docs/agents/gotchas/`, then its globs to `AREA_RULES` in `scripts/agents-sync.mjs`, and run the script.
- _Change a machine-level setting_ (a hook, plugin or user config every agent install needs): add a step to `scripts/agents-setup.mjs` (with a check, a fix that merges rather than overwrites, and a manual fallback), keeping its data in `.agents/user/` without secrets. Hermes has no project config, so its settings are merged by `agents-sync.mjs --hermes`.
- _Check what an agent really loaded:_ Claude Code `/context`, `/hooks`, `/agents`; OpenCode `opencode debug config` and `opencode debug agents`; omp `omp config list --scope project` and `/extensions`; Hermes `hermes config get <key>`, `hermes mcp list`, `hermes skills list`. Test a Hermes change without touching your config: `HERMES_HOME=<copy of ~/.hermes> node scripts/agents-sync.mjs --hermes`.

## New machine

1. Install the agents you use and sign in to each (and `gh auth login`). Put API keys in your environment or the agent's own login; none are in the repo.
2. Clone the repo and run `node scripts/agents-setup.mjs` from it. It lists what's missing for the agents found on `PATH` and, after you confirm, fixes it:
   - git hooks (`core.hooksPath`) and gitleaks for the pre-commit secret scan;
   - RTK (installed with brew or cargo) and its hook in Claude Code, OpenCode, Hermes and oh-my-pi;
   - TokenEconomizer (cloned to `~/.local/share/TokenEconomizer` or `$TOKENECONOMIZER_DIR`, plugin installed in Claude Code, linked into OpenCode and Hermes, `TE_PYTHON` set to a Python 3.10+);
   - Hermes: trusts the repo's skills, registers the MCP servers, and merges in the guard hook, `approvals.deny`, `skills.external_dirs` and the `quick_commands` aliases (`agents-sync.mjs --hermes`);
   - with `--with-models`, the maintainer's provider and model choices from `.agents/user/` (OpenCode and Hermes).
     `--check` only reports, `--dry-run` prints the commands, `--yes` skips the question, `--only <groups>` limits it. Re-running is safe: it merges into existing configs.
3. Restart each agent (Hermes: also `/reload-mcp`, and approve the guard hook the first time it asks).

Claude Code runs `agents-setup.mjs --check --quiet` at every session start (through `scripts/session-start.mjs`) and says what's missing; other agents are told to by `AGENTS.md`. An agent must ask before running the fixes, since they install tools and edit the home folder.

Per agent, what the script doesn't do:

- **Claude Code** on Windows: enable symlinks (`git config core.symlinks true` with Developer Mode on) so `.claude/skills` works.
- **OpenCode:** a cheaper model for the `ui-verify` subagent, in your own `~/.config/opencode/opencode.json`: `{"agents": {"ui-verify": {"model": "<provider>/<model>"}}}`. Its worktrees are detached: name the branch with `git switch -c <type>/<topic>`.
- **Hermes Agent:** its skill scanner rates `pydantic-ai-harness` "dangerous" (a false positive from docs mentioning `~/.ssh` and `os.environ`) and hides it; read `.agents/skills/pydantic-ai-harness/SKILL.md` directly when working on the assistant. Skills in worktrees come from the base checkout (`skills.external_dirs`), so a skill changed on a branch is seen as on `main`. `quick_commands` work in the CLI.
- **oh-my-pi:** nothing beyond RTK's extension. Generated for it: `.omp/config.yml` (`worktree.onStart: create` starts each session in a new linked worktree; `bash.gitGuard` refuses stash/reset/checkout that discard work in the base checkout; `bash.patterns` from `DENIED_COMMANDS`; `secrets.enabled` redacts secrets before they reach the model), `.omp/agents/` (it ignores `.claude/agents`), `.omp/rules/`, `.omp/AGENTS.md` and `.omp/extensions/athena.ts`. omp drops the Playwright MCP server on purpose in favour of its own headless browser (`athena-ui-verify` says how to use it). Not covered: the setup check at start-up and TokenEconomizer (no omp plugin upstream). Point `ui-verify` at a cheap model with omp's `smol` role (`/model` → Roles).

## Running agents headless

For scripted runs, such as the orchestration in `docs/specs/agent-orchestration.md`: one agent starting another as a child process in a given worktree. Checked by hand on 2026-11-25 (omp 19.1.1, OpenCode 2.3.2, model `kilo/kilo-auto/free`), with throwaway commits in a throwaway worktree.

| | oh-my-pi (worker) | OpenCode (reviewer) |
|---|---|---|
| Command | `omp -p --no-session --mode json --model <provider>/<id> --max-cost 0.01 --cwd <worktree> "<prompt>"` | `opencode run --agent reviewer --model <provider>/<id> --format json --archived --title <task> "<prompt>"`, started with `cd <worktree>` |
| Output | JSON lines on stdout: `session` (with `cwd`), `message_start`/`message_end`, `tool_execution_start`/`_end`, `turn_end`, `agent_end` (`isTerminal`) | JSON lines: `step_start`, `tool_use` (`part.tool`, `part.state`), `text`, `step_finish` (`part.cost`), `error` | <!-- docs-check: ignore -->
| Model used | Every assistant `message_end`: `.message.provider`, `.message.model`, `.message.upstreamProvider`, `.message.usage.cost.total` | Not in the stream. `opencode session export <sessionID>` (the id is in every event): `.messages[].model.providerID` / `.id`, `.info.agent` | <!-- docs-check: ignore -->
| Exit codes | 0 done; 1 model not found (`Model "…" not found` on stderr); 2 bad flag; 3 `--max-cost` reached | 0 done; 1 on an error event (`provider.no-route` for an unknown model) |
| Worktree | `--cwd` is honoured. `worktree.onStart: create` (`.omp/config.yml`) doesn't fire under `-p`, even from the base checkout: no second worktree | Runs in the current folder. Don't pass `-w`: it makes another worktree |
| Guards | `.omp/extensions/athena.ts` is loaded under `-p`: a write to the base checkout was refused | Only the deny rules in `opencode.json` (no guard hook) |
| Cleanup | `--no-session` saves nothing | `--archived` keeps it out of lists; `opencode session delete <id>` removes it |

Rules for scripted runs:

- **Pass exact model ids and check the model afterwards.** omp's `--model` fuzzy-matches, so a typo can pick a different (possibly paid) model; compare the reported provider/model with the approved list after every run. `--max-cost` won't take `0`; use a small positive cap (`0.01`) as a backstop on free models.
- **The reviewer isn't read-only.** OpenCode's `edit` deny doesn't cover `shell` or Code Mode's `execute`: told to try, the reviewer appended to a file with `echo >>` and reported it as allowed. Give a scripted reviewer its own detached worktree at the candidate commit and check afterwards that `git status --porcelain` is empty and `HEAD` didn't move; otherwise discard the review. The same holds for Claude Code's `reviewer` (it has Bash).
- A run of a few tool calls took 10–60 s on `kilo-auto/free`; nothing hung waiting for a permission prompt.

## Token budget

In the repo:

- **What every session pays for is kept small:** `AGENTS.md`, STATUS and the app rule files are size-capped by `scripts/check-docs.mjs` (`SIZE_LIMITS`) (finished work goes to `docs/HISTORY.md`); `scripts/check.sh` is quiet without a terminal; Playwright runs with `--snapshot-mode none` (snapshot only when you need to read the page); `.ignore` keeps lockfiles, CHANGELOG and the generated theme files out of ripgrep searches; Claude Code caps Bash and MCP output at 20k (`.claude/settings.json` → `env`) and OpenCode caps tool output at 20 KB (`opencode.json` → `tool_output`, the rest is saved to disk). Pipe long commands through `tail` or `grep` yourself too. This file is separate from AGENTS.md because only tooling changes need it.
- **Subagents start with their skill loaded** (Claude Code `skills:`, omp `autoload-skills:`), so they don't spend a turn reading it.
- **Dependencies ship their own agent files.** pydantic-ai has `CLAUDE.md`/`AGENTS.md` files in `.venv/…/pydantic_ai/` (about 40 KB, written for pydantic-ai's own contributors), and Next and recharts ship `AGENTS.md` in `node_modules`. Claude Code loads a subfolder's `CLAUDE.md` as soon as it reads a file there, which happens when you read pydantic-ai's source. `.claude/settings.json` → `claudeMdExcludes` skips them. <!-- docs-check: ignore -->
- **MCP tool definitions cost tokens on every request in OpenCode and Hermes** (Claude Code loads them on demand). Measured: Playwright 25 tools ≈ 21k characters, next-devtools ≈ 5.7k, context7 ≈ 5.2k, shadcn ≈ 4.3k. So `scripts/agents-sync.mjs` gives Playwright only to OpenCode's `ui-verify` subagent (a `playwright_*` deny rule globally, allow in the agent; agent rules come after global ones and the last match wins), and writes Hermes `tools.exclude` filters for unused tools. OpenCode 2.x routes each MCP server's tools through Code Mode by default (per server, `codemode`). Hermes' `lazy: true` only delays connecting; the tools are still registered, so it saves memory, not tokens.
- Not used: caveman (terse replies; measured at a few percent of a session's tokens, and the "Short replies" rule in `AGENTS.md` gets most of it).

Per person, so not committed:

- **Cheaper subagents in Claude Code.** `ui-verify` and `reviewer` use `model: sonnet`, and `.claude/settings.json` sets `CLAUDE_CODE_SUBAGENT_MODEL=sonnet` for the rest (e.g. Explore). Use `/model opusplan` in the main session for Opus planning and Sonnet execution.
- **A cheaper model for browser checks.** Claude Code's generated `ui-verify` subagent uses `model: sonnet`; OpenCode's needs a per-provider id (see New machine → OpenCode).
- **Token-saving tools (set up by `scripts/agents-setup.mjs`):**
  - [RTK](https://github.com/rtk-ai/rtk) (Apache-2.0): a hook that shortens the output of shell commands like `git`, `gh`, `pytest` and `pnpm` before the agent reads it. It only covers shell commands (not built-in Read or Grep), and it runs your commands through a third-party binary. `scripts/check.sh` is already quiet without a terminal, so the gain here is mostly on `git`, `gh` and ad-hoc test runs. It also rewrites `git diff`, so to save a real patch to a file use `/usr/bin/git diff` (or `rtk proxy git diff`).
  - [TokenEconomizer](https://github.com/microsoft/TokenEconomizer) (Apache-2.0): learns repo facts, prunes unused tools, and nudges an agent stuck in a failure loop. The first two overlap with `athena-recipes`, the command cheat sheet and the MCP scoping above. What it learns stays in `~/.tokeneconomizer`, so anything another agent needs must still go in the repo.
  - Both are installed and hooked into each agent by `scripts/agents-setup.mjs` (see [New machine](#new-machine)). `rtk gain` shows RTK's savings; `~/.tokeneconomizer/bin/te doctor` checks TokenEconomizer. RTK runs with `--hook-only` (no `RTK.md`, an instructions file every session would pay for). TokenEconomizer's tool pruning writes `.claude/settings.local.json`, which is git-ignored. <!-- docs-check: ignore -->
