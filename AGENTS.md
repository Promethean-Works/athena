# Athena

Self-hosted home server control panel (CasaOS-style) for **Linux, macOS and Windows**. Public repo: `github.com/tiagozaccaro/athena`.

This file is the single source of instructions for every coding agent (Claude Code, OpenCode, Hermes Agent, Codex, Gemini CLI, Copilot). Other agents' files only point here. Every session loads this file, so it stays short: **read the rest only when the task needs it** (see [Read when](#read-when)).

Layout: `apps/server` (Python 3.13, FastAPI, CLI `athena`), `apps/web` (Next.js 16 static export, shadcn on Base UI, served by the server), `packages/ui` (shadcn components; Athena-made ones in `packages/ui/src/components/athena/`), `packages/api-client` (generated), `catalog/` (store apps), `scripts/` (installers, `check.sh`, git hooks, agent sync), `docs/`, `.agents/skills/`.

## Every session

1. Read `docs/STATUS.md` (current milestone, in progress, next, open questions).
2. Pick the rows of [Read when](#read-when) that match the task and read only those files.
3. Before ending, do the [Handoff](#handoff). The next agent may be a different tool with no memory of yours.

## Working with the maintainer

- They move through the milestones in `docs/design/milestones.md` with short prompts. "Next": read STATUS, propose the next concrete step with a recommendation, and wait for a yes before starting a new milestone or part. "Discuss questions first": list the open questions with a recommendation each before writing code. Big milestones are split into parts, one branch and PR per part.
- "Check" / "keep observing the PRs": read the checks (`gh pr checks <n>`, `gh run view <id> --log-failed`), fix failures on the PR branch, report what merged and what didn't. Never claim a merge without checking.
- **Short replies.** Lead with the answer; skip preamble and recaps. Reports of what was and wasn't verified stay complete: final reports list "Fixed along the way" and "Not tested yet".
- They can't see your private memory (Claude memory, Hermes memory, OpenCode sessions). Anything the next agent needs goes in the repo ([Where things go](#where-things-go)).

## Git workflow (mandatory)

`main` is protected: no direct or force pushes. Details in `CONTRIBUTING.md`.

1. **Never edit, branch or commit in the base checkout** (where the repo was cloned). It stays on `main`, clean.
2. Every task, however small, starts in its own worktree before any file is touched: `scripts/new-worktree.sh <type>/<topic>` (or `git fetch origin && git worktree add ../athena-<topic> -b <type>/<topic> origin/main`). Types: `feat`, `fix`, `perf`, `docs`, `refactor`, `test`, `build`, `ci`, `chore`, `revert`. Several agents work at once; worktrees keep them apart. After the merge: `git worktree remove ../athena-<topic>`.
3. Open a PR to `main` with a Conventional Commit title (`feat(store): add install form`); it becomes the squash commit and changelog entry.
4. Turn on auto-merge right away, without asking: `gh pr merge <n> --squash --auto --delete-branch`. Not for release-please PRs (the maintainer merges those) or PRs whose base isn't `main`. Also check CodeQL is green before calling a PR done.
5. Never edit `CHANGELOG.md` or `version.txt`; release-please does.

## Rules

- **Cross-platform first.** Anything that touches the host goes through a provider and a capability in the manifest; the UI and the assistant show only what the host supports (`athena-platform-feature` skill).
- **Don't guess APIs.** Copy the closest existing feature, then check current docs (Context7, the `shadcn` skill or MCP, `node_modules/next/dist/docs/`). Versions here are newer than most training data (Next 16, Base UI, xterm.js 6, Python 3.13, pydantic-ai 2.x).
- **Open-source dependencies only**, each recorded in `docs/design/licenses.md`.
- **Leave the maintainer's things alone.** Port 8420 may be their own Athena (use 8421+). Act only on containers, apps and images named `athena-demo-*` / `athena-test-*`. Fake anything that would change the host in browser checks.
- Run pnpm from the repo root and Python with `uv run` inside `apps/server`. Never hand-write API request types: `pnpm gen:api` regenerates `packages/api-client` after any route change.

## Read when

| When you… | Read |
|---|---|
| Work in `apps/server` | `apps/server/AGENTS.md`; before pushing Python, `docs/agents/gotchas/windows.md` and `docs/agents/gotchas/codeql.md` |
| Work in `apps/web` | `apps/web/AGENTS.md` and `docs/agents/gotchas/web.md` |
| Touch the AI assistant | `docs/agents/gotchas/assistant.md`, `docs/design/assistant.md`, skills `pydantic-ai-harness` / `building-pydantic-ai-agents` |
| Touch cloud storage (rclone) | `docs/agents/gotchas/rclone.md`, `docs/design/cloud.md` |
| Touch the host OS (runtimes, package managers, terminal, shares) | skill `athena-platform-feature`, `docs/design/platform.md` |
| Add an endpoint, migration, page, job or setting | skill `athena-recipes` (start here when unsure how something is done) |
| Add or update a store app | skill `athena-catalog-app`, `catalog/README.md` |
| Finish UI work (any `apps/web` change or API the UI uses) | skill `athena-ui-verify` and `docs/agents/gotchas/browser.md` |
| Change installers, `athena service` or platform detection | skill `athena-host-test`, `docs/agents/gotchas/installers.md` |
| Commit, push, open a PR or fix CI | skill `athena-ship`, `docs/agents/gotchas/git-ci.md` |
| Need a command | `docs/agents/commands.md` |
| Need the design of a feature, or a past decision | `docs/design/README.md` (index), then one section |
| Need a feature's history | `docs/HISTORY.md` (search it; don't read it whole) |
| Hit a shell, sandbox or agent quirk | `docs/agents/gotchas/environment.md` |
| Change agent tooling (MCP, skills, settings) or set up a machine | `docs/agents/tooling.md` |

Skills live in `.agents/skills/<name>/SKILL.md`; if your agent doesn't load skills, read the file. MCP servers (`.mcp.json`): `shadcn`, `next-devtools`, `playwright` (call `browser_snapshot` when you need the page), `context7`.

## Definition of done

- While iterating, run focused checks: `cd apps/server && uv run pytest -q -k <name>`, `uv run ruff check`, `pnpm lint && pnpm typecheck`.
- Before pushing: `scripts/check.sh` (what CI runs; `--quick` skips the web build). Windows-only failures show up only in CI.
- Turn on the git hooks once per clone: `git config core.hooksPath .githooks` (pre-commit refuses `main` and the base checkout; pre-push runs the parts of `scripts/check.sh` the push touches).
- UI changes are verified in a real browser with `athena-ui-verify` before they're reported done.
- `node scripts/check-docs.mjs` fails when an agent doc (every `AGENTS.md`/`CLAUDE.md`, `docs/agents/`, skills, `catalog/README.md`) names a file, function or constant that doesn't exist, or a file read every session grows past its size limit. Fix docs in the same PR as a rename; end a line with `<!-- docs-check: ignore -->` to mention something absent on purpose.

## Handoff

At the end of every session, in your branch or a docs PR:

- `docs/STATUS.md`: move finished items to one short bullet at the end of `docs/HISTORY.md` (what, PR, what was and wasn't verified). Under **In progress**, say where you stopped and the next concrete step. Add **Open questions** and **Blockers**. Keep it short (size-checked).
- Add anything non-obvious you learned to [the right place](#where-things-go).

## Where things go

| What | Where |
|---|---|
| Rules for every task | This file. Keep it short; link to detail |
| Rules for one app | `apps/server/AGENTS.md`, `apps/web/AGENTS.md` |
| A repeatable procedure | A project skill (`.agents/skills/<name>/SKILL.md`, see `docs/agents/tooling.md`) |
| Design and decisions | The section in `docs/design/`, plus a row in `docs/design/decisions.md` |
| Lessons and gotchas (one bullet per fact, with the _why_) | `docs/agents/gotchas/<area>.md` |
| Commands and patterns to copy | `docs/agents/commands.md` |
| Agent tooling | `docs/agents/tooling.md` |
| Current / finished work | `docs/STATUS.md` / `docs/HISTORY.md` |
| Store app format | `catalog/README.md` |
