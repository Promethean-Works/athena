# Developing Athena

How to set up a machine to work on Athena, with or without AI coding agents, and how day-to-day work runs. For the rules agents follow, see `AGENTS.md`; for contribution rules (branches, PR titles, reviews), `CONTRIBUTING.md`.

## 1. Set up a machine

### What you need

| Tool | Why |
|---|---|
| git, Node.js (LTS) with pnpm, Python 3.13 with [uv](https://docs.astral.sh/uv/) | Building and running Athena |
| [GitHub CLI](https://cli.github.com/) (`gh auth login`) | PRs, CI and auto-merge |
| Docker or another container engine (optional) | Apps and container features; tests that need it are skipped without it |
| One or more coding agents (optional) | Claude Code, OpenCode, Hermes Agent, Codex, Antigravity, GitHub Copilot or oh-my-pi (`omp`) |

### Steps

```bash
git clone https://github.com/tiagozaccaro/athena.git
cd athena
pnpm install
(cd apps/server && uv sync)
node scripts/agents-setup.mjs
```

`agents-setup.mjs` lists what's missing on this machine and, after you confirm, sets it up. It only touches agents it finds on your `PATH`, and it merges into your existing configs rather than overwriting them:

- the git hooks (`core.hooksPath`): pre-commit scans for secrets and refuses commits on `main`; pre-push runs the checks your push touches;
- [gitleaks](https://github.com/gitleaks/gitleaks), for that secret scan;
- [RTK](https://github.com/rtk-ai/rtk), which shortens the output of shell commands before an agent reads it, hooked into Claude Code, OpenCode and Hermes;
- [TokenEconomizer](https://github.com/microsoft/TokenEconomizer), which learns facts about the repo, drops tools you never use and nudges an agent stuck in a loop (cloned to `~/.local/share/TokenEconomizer`, or `$TOKENECONOMIZER_DIR`);
- Hermes: trusting the repo's skills and registering its MCP servers.

Useful flags: `--check` reports without changing anything, `--dry-run` prints the commands it would run, `--yes` skips the question, `--only claude,hermes` limits it to some groups, and `--with-models` also applies the maintainer's model choices from `.agents/user/`.

Then:

1. **Sign in to each agent** with its own login or an API key in your environment (for example `KILOCODE_API_KEY` for the Kilo provider in `.agents/user/opencode.models.json`). No keys are stored in the repo.
2. **Restart your agents** so they load the new hooks and plugins. In Hermes, also run `/reload-mcp`.
3. **Check:** `node scripts/agents-setup.mjs --check` should print only `ok` lines.

Re-run `agents-setup.mjs` after reinstalling an agent or moving to a new machine: it puts back everything that lives outside the repo.

### What each agent gets from the repo

Everything else is in the repo and needs no setup:

| | Instructions | Skills | MCP servers | Commands and subagents |
|---|---|---|---|---|
| **Claude Code** | `CLAUDE.md` files import `AGENTS.md`; area rules in `.claude/rules/` | `.claude/skills` (a link to `.agents/skills`) | `.mcp.json` | `.claude/commands/`, `.claude/agents/` |
| **OpenCode** | `AGENTS.md` | `.agents/skills` | `opencode.json` | `opencode.json` |
| **Hermes Agent** | `AGENTS.md` | `.agents/skills` (once trusted) | Set up by `agents-setup.mjs` | Skills as `/athena-…` |
| **Codex** | `AGENTS.md` | `.agents/skills` | `.codex/config.toml` (trust the project when asked) | `.codex/agents/`, skills |
| **Antigravity** | `AGENTS.md` | `.agents/skills` | `.agents/mcp_config.json` | Skills |
| **GitHub Copilot** | `AGENTS.md`, `.github/instructions/` | `.agents/skills` | `.mcp.json` | Skills |
| **oh-my-pi** | `AGENTS.md`, `.github/instructions/` as rules | `.agents/skills` | `.mcp.json` | `.claude/commands/`, `.omp/agents/` |

The MCP servers are `shadcn` (component registry), `next-devtools` (Next.js docs and diagnostics), `playwright` (a headless browser for UI checks) and `context7` (current library docs; set `CONTEXT7_API_KEY` for higher rate limits).

Many of these files are generated from one source by `node scripts/agents-sync.mjs`, and CI fails when they drift. Don't edit generated files by hand; `docs/agents/tooling.md` explains which files are generated and how to change them.

### Platform notes

- **Windows:** turn on Developer Mode and `git config core.symlinks true` before cloning, so `.claude/skills` is a real link. Where a link can't be made, `agents-setup.mjs` copies the file instead; re-run it after updating TokenEconomizer.
- **macOS:** the system `python3` is 3.9, too old for TokenEconomizer; `agents-setup.mjs` finds or installs (through uv) a 3.10+ and points `TE_PYTHON` at it.
- **Codex and Antigravity:** RTK and TokenEconomizer aren't wired up automatically; the script prints the steps.
- **oh-my-pi:** `agents-setup.mjs` installs the RTK extension; TokenEconomizer has no omp integration.

## 2. Run Athena

| Task | Command |
|---|---|
| Dev mode | `pnpm dev` (UI on :3000) plus `cd apps/server && uv run athena serve` (API on :8420) |
| Release build, as users get it | `pnpm build`, then `cd apps/server && ATHENA_WEB_DIR=../web/out uv run athena serve --port 8421 --data-dir "$DATA"` |
| Server tests | `cd apps/server && uv run pytest -q` (`-k <name>` for one) |
| Web lint and types | `pnpm lint && pnpm typecheck` |
| Everything CI checks | `scripts/check.sh` (`--quick` skips the web build) |
| After changing an API route | `pnpm gen:api` (CI fails if the client is stale) |

Port 8420 is the default for an installed Athena, so use another one (8421) when you already run Athena on the same machine. VS Code launch and task configurations are in `.vscode/`. More commands are in `docs/agents/commands.md`.

## 3. Day-to-day work

### One task, one worktree

The checkout you cloned stays on a clean `main`. Every task, however small, gets its own git worktree and branch, so several people or agents can work at once without touching each other's files:

```bash
scripts/new-worktree.sh feat/folder-upload      # creates ../worktrees/athena-folder-upload from origin/main
cd ../worktrees/athena-folder-upload
# … work, commit …
git push -u origin HEAD
gh pr create --title "feat(files): add folder upload"
gh pr merge <n> --squash --auto --delete-branch
# after it merges:
git worktree remove ../worktrees/athena-folder-upload
```

PR titles are Conventional Commits; they become the squash commit and the changelog line. `main` is protected, and auto-merge merges the PR once CI is green.

### Working with an agent

Agents read `AGENTS.md` first. It's a short router: it tells them which few files to read for the task at hand, so a session doesn't start by loading every document. The shared commands below work in every agent: as slash commands in Claude Code and OpenCode, and as skills (`/athena-next` in Hermes, `$athena-next` in Codex) elsewhere.

| Say or type | What happens |
|---|---|
| `/next` ("next") | The agent reads `docs/STATUS.md`, proposes one next step with a recommendation, and waits for your yes |
| `/check-prs` ("check") | It checks open PRs, CI and CodeQL, fixes failures on their branches, and reports what merged |
| `/review-diff` | A read-only reviewer checks the current diff against the project rules |
| `/ship` | Checks, commit, PR with auto-merge, CI watching |
| `/handoff` ("wrap up") | It updates `docs/STATUS.md`, `docs/HISTORY.md` and the gotchas so the next agent, possibly a different tool, can continue |

**Big features start with a spec.** For a new milestone part, a new area, or anything bigger than one PR, the agent writes `docs/specs/<feature>.md` from the template, covering goal, non-goals, platforms, design, parts, acceptance checks and open questions. You approve it before any code is written (`docs/specs/README.md`).

**UI changes are checked in a real browser** (the `athena-ui-verify` skill) before they're called done.

### Where things are written down

| What | Where |
|---|---|
| What's being worked on, what's next | `docs/STATUS.md` (finished work: `docs/HISTORY.md`) |
| The design, one file per area, and the decisions log | `docs/design/` |
| Rules for agents | `AGENTS.md`, `apps/server/AGENTS.md`, `apps/web/AGENTS.md` |
| Lessons and traps, by area | `docs/agents/gotchas/` |
| Step-by-step procedures | `.agents/skills/` |
| Agent tooling: what's generated, how to change it | `docs/agents/tooling.md` |

Nothing an agent needs later should live only in a chat or in an agent's private memory: other agents can't see either.

## 4. When something goes wrong

| Problem | Fix |
|---|---|
| A commit is refused: "committing in the base checkout" or "on main" | Work in a worktree (see above). To move changes: `git stash`, create the worktree, `git -C ../worktrees/athena-<topic> stash pop` |
| A commit is refused: gitleaks found a secret | Take it out (use an environment variable or the data dir). For a false positive, add an allowlist entry to `.gitleaks.toml` with a reason |
| CI fails on "generated agent config is in sync" | Run `node scripts/agents-sync.mjs` and commit the result |
| CI fails on "docs point at real files" | A doc names something you renamed or removed; fix the doc. To mention something absent on purpose, end the line with an HTML comment `docs-check: ignore` |
| CI fails only on Windows | Usually paths, encoding or line endings; see `docs/agents/gotchas/windows.md` |
| An agent doesn't see the skills or MCP servers | Run `node scripts/agents-setup.mjs --check` and restart the agent. Hermes: `/reload-mcp`; Codex: trust the project |
| Hermes hides a skill | Its scanner rated it unsafe; see `docs/agents/tooling.md` → Changing tooling |
| RTK or TokenEconomizer misbehaves | `rtk gain` shows what RTK does; `~/.tokeneconomizer/bin/te doctor` checks TokenEconomizer. Remove a hook from the agent's user config to turn it off |
| Claude Code says setup is missing at start-up | Run `node scripts/agents-setup.mjs` and restart |
