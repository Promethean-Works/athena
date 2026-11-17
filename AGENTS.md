# Athena

Self-hosted home server control panel (CasaOS-style) for **Linux, macOS and Windows**.

This file is the single source of instructions for every coding agent working here (Claude Code, OpenCode, Hermes Agent and others). `CLAUDE.md` only imports this file. Don't put agent-specific rules anywhere else.

## Start here (every session, every agent)

1. Read `docs/STATUS.md`: the current milestone, what's in progress, and what's next. Finished work is in `docs/HISTORY.md`; read it only when you need a feature's background.
2. Read the rules file of the app you'll touch: `apps/server/AGENTS.md` or `apps/web/AGENTS.md`.
3. Read `docs/AGENT-NOTES.md` down to **Gotchas** (how the maintainer works, the command cheat sheet, patterns to copy). Under Gotchas, read only the sections for the area you touch (Windows CI, CodeQL, Server, Web, Assistant, …), plus "Git, GitHub and CI" before you push.
4. Read the parts of `docs/mvp-design.md` that the task touches. It holds the design and the decisions log (§11).
5. Before ending a session, update `docs/STATUS.md` (see [Handoff](#handoff)). The next agent may be a different tool with no memory of yours.

## Git workflow (mandatory)

The repo is public at `github.com/tiagozaccaro/athena`. `main` is protected: no direct pushes, no force pushes.

1. Start every task on a new branch from an up-to-date `main`: `git switch main && git pull && git switch -c <type>/<short-description>`. Types: `feat`, `fix`, `perf`, `docs`, `refactor`, `test`, `build`, `ci`, `chore`, `revert`.
2. Create a new git worktree for that branch and do all work there, never in the base checkout: `git worktree add <worktree-dir> <branch>`. Keep the base repository always on `main`; each agent works in its own worktree like on its own machine, so one agent's uncommitted work never clobbers another's. When the branch is merged or deleted, remove the worktree: `git worktree remove <worktree-dir>`.
3. Commit on the branch. Never commit to or push `main`.
3. Open a PR to `main` with a Conventional Commit title (`feat(store): add install form`). CI checks the title, because it becomes the squash commit and the changelog entry.
4. Turn on auto-merge right after opening the PR, without asking: `gh pr merge <n> --squash --auto --delete-branch`. This is the maintainer's standing instruction for every PR. CI (`ci-ok`) and `pr-title` must pass. PRs are squash-merged and the branch is deleted. Exceptions: release-please PRs (the maintainer merges those) and PRs whose base isn't `main` (turn it on once they're retargeted to `main`).
5. Don't edit `CHANGELOG.md` or `version.txt` by hand. release-please manages them.

Full details are in `CONTRIBUTING.md`.

## Layout

Each app has its own rules file. **Read it before working there**: some agents load it automatically, others won't.

- `apps/server`: Python 3.13 (uv), FastAPI, package and CLI `athena`. Rules, module map and test conventions are in **`apps/server/AGENTS.md`**.
- `apps/web`: Next.js 16 static export, shadcn/ui on Base UI (preset `b0`), served by the Python server in production. Rules, layout and UI conventions are in **`apps/web/AGENTS.md`**.
- `packages/ui`: shadcn components (`pnpm dlx shadcn@latest add <name> -c apps/web`). Athena-made components go in `packages/ui/src/components/athena/`.
- `packages/api-client`: generated from the server's OpenAPI schema with `pnpm gen:api`. Never hand-write request types; CI fails if the client is out of date.
- `catalog/`: built-in app store (compose + `x-athena` metadata, see `catalog/README.md`).
- `scripts/`: `install.sh` and `install.ps1` (the one-line installers, attached to every GitHub release; keep them in sync with the server's `athena service` CLI), `check.sh` (CI's checks locally), `check-docs.mjs`, `build-wheel.sh`, `agents-sync.mjs`, `gen-theme-css.mjs`, and `scripts/e2e/` (the browser smoke test).
- `.github/`: CI (`ci.yml`), E2E (`e2e.yml`), PR title check, release-please (`release.yml`), Dependabot, templates.

## Rules

- **Cross-platform first.** Anything that touches the host goes through a provider and a capability in the manifest. The UI and the AI assistant only show what the host supports. Follow the `athena-platform-feature` skill.
- **Don't guess APIs.** Read the existing feature that does something similar, then the library's docs (Context7, the `shadcn` skill or MCP, Next's bundled docs). Training data is often older than the versions used here (Next 16, Base UI, xterm.js 6, Python 3.13).
- **Open-source dependencies only.** Record licenses in `docs/mvp-design.md` §9.
- **UI rules** (shadcn first, the app shell, theme tokens only, and design quality with the `frontend-design` skill) are in `apps/web/AGENTS.md`.
- **Short replies.** In chat, lead with the answer. Skip preamble, restating the question and step-by-step recaps of what you did. Code, commands, and reports of what was and wasn't verified stay complete.
- Run pnpm commands from the repo root; Python commands with `uv run` inside `apps/server`.

## Agent tooling

- **Project skills** (`.agents/skills/<name>/SKILL.md`; read it directly if your agent doesn't load skills): `athena-recipes` (common changes and the "before you say done" checklist; **start here if you're unsure how something is done**), `athena-platform-feature`, `athena-ui-verify`, `athena-ship`, `athena-host-test`, `athena-catalog-app`. Third-party: `shadcn`, `frontend-design`, `building-pydantic-ai-agents`, `pydantic-ai-harness`, `pydantic`.
- **MCP servers** (`.mcp.json`): `shadcn`, `next-devtools`, `playwright` (actions don't return the page; call `browser_snapshot` when you need it), `context7`.
- To change any of it (MCP servers, skills, generated agent config) or set up an agent on a new machine, read `docs/AGENT-TOOLING.md` first.

## Definition of done

Before pushing, run `scripts/check.sh` (the same checks as CI; `--quick` skips the web build). Windows-only failures still show up only in CI.

Turn on the pre-push hook once per clone so this happens even when you forget: `git config core.hooksPath .githooks`. It runs only the parts the push touches: about 2 s for docs, under a minute with server changes. Skip it once with `git push --no-verify`.

**Docs are checked too.** `node scripts/check-docs.mjs` (in CI and in `scripts/check.sh`) fails when AGENTS.md, `docs/AGENT-NOTES.md`, `docs/AGENT-TOOLING.md`, `catalog/README.md` or a project skill names a file, function, component or constant that doesn't exist. When you rename something, fix the docs in the same PR. To mention something on purpose that doesn't exist (an old name, an external API), end the line with `<!-- docs-check: ignore -->`.

### UI work

Any change to `apps/web`, or to an API the UI uses, is verified in a real browser with the `athena-ui-verify` skill (release build on port 8421, fresh data dir, happy path plus a failure, console and network checks, phone width and dark mode when layout changed, cleanup) before it's reported as done.

## Handoff

At the end of every session, update `docs/STATUS.md`:
- Move finished items out of STATUS: add one short bullet to the end of `docs/HISTORY.md` (what, the PR, what was verified and what wasn't).
- Under **In progress**, say exactly where you stopped: files touched, what works, what's broken, and the next concrete step.
- Add new **Open questions** or **Blockers**.
- Add anything non-obvious you learned to `docs/AGENT-NOTES.md` (see [Where things go](#where-things-go)).
- Keep it short: every agent reads STATUS at the start of every session, so each line costs tokens many times over. `scripts/check-docs.mjs` fails if it grows past 8 KB. Detail belongs in the design doc, HISTORY, commits and code.

## Where things go

| What | Where |
|---|---|
| Rules for every agent and task | `AGENTS.md` (this file). Every session loads it, so keep it short and link to detail |
| Rules for one app | `apps/server/AGENTS.md`, `apps/web/AGENTS.md` |
| A repeatable procedure | A project skill in `.agents/skills/<name>/SKILL.md` (how: `docs/AGENT-TOOLING.md` → Changing tooling) |
| Design and decisions | `docs/mvp-design.md`: update the section and add a row to §11 Decisions log |
| Lessons, gotchas, troubleshooting, commands | `docs/AGENT-NOTES.md`, in its area's section, one bullet per fact with the _why_ (a CI failure with a surprising cause, a tool quirk, a scanner false positive, a pattern worth copying) |
| Agent tooling (MCP servers, generated config, token budget) | `docs/AGENT-TOOLING.md` |
| Current work / finished work | `docs/STATUS.md` / `docs/HISTORY.md` (see Handoff) |
| Store app format | `catalog/README.md` |
| Workflow for human contributors | `CONTRIBUTING.md` |

Never only in chat or in agent-private memory (Claude memory, Hermes MEMORY.md, OpenCode sessions): the next agent can't see either.
