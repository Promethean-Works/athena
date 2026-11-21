# Commands and patterns

_Read when you need a command or are starting something new. Rules are in `AGENTS.md`._

## Command cheat sheet

Run pnpm from the repo root and Python with `uv run` inside `apps/server`.

| Task | Command |
|---|---|
| **Everything CI runs** | `scripts/check.sh` (`--quick` skips the web build; `web`, `server` or `repo` runs one part). Without a terminal it's quiet: one `ok`/`FAIL` line per step and the last 40 lines of a failure, with the full log's path. `--verbose` streams everything |
| **CodeQL locally** | `scripts/codeql.sh [create\|analyze\|all] [python\|javascript-typescript\|actions]` builds databases in `.codeql/databases/` (the VS Code CodeQL extension lists them) and writes SARIF to `.codeql/results/`. Settings: `.github/codeql/codeql-config.yml`. GitHub's default setup on PRs ignores that file |
| Docs name real things | `node scripts/check-docs.mjs` (`--list` prints everything it verified) |
| Regenerate API client | `pnpm gen:api` (after any API change; CI fails on drift) |
| Regenerate theme CSS | `pnpm gen:theme` (after shadcn upgrades; needs network) |
| Check or find the settings file | `cd apps/server && uv run athena config check --data-dir "$DATA"` (`path`, `show`, `reset <section>`) |
| Agent config sync | `node scripts/agents-sync.mjs` (after editing `.mcp.json`); `--check` is what CI runs |
| Release server for UI checks | `pnpm build` then `cd apps/server && ATHENA_WEB_DIR=../web/out uv run athena serve --port 8421 --data-dir "$DATA"` |
| Dev mode | `pnpm dev` (Next on :3000, proxies `/api` to :8420) plus `uv run athena serve` |
| Build the wheel | `scripts/build-wheel.sh` (also used by `release.yml` and the E2E workflow) |
| Store apps start for real | `cd apps/server && uv run python -m athena.catalog.smoke --changed` (or `<id>…`, or `--all --jobs 3`); report in `catalog-smoke-report/` |
| Installer dry run | `scripts/install.sh --dry-run`; `athena service install --dry-run` |
| PR status | `gh pr checks <n>`, `gh run view <run-id> --log-failed`, `gh api repos/tiagozaccaro/athena/code-scanning/alerts?state=open` |

Per-app commands (tests, lint, real-engine tests, adding a shadcn component) are in `apps/server/AGENTS.md` and `apps/web/AGENTS.md`.

If your session starts with "environment facts learned from earlier tasks in this checkout" (TokenEconomizer, on the maintainer's machine) and a fact isn't in this table yet, add it here: the facts stay on one machine, the table reaches every agent.

## Patterns to copy

When adding something, start from the closest existing feature instead of inventing a new shape.

- **Host feature end to end:** follow the `athena-platform-feature` skill. Packages (`athena/packages/`, `api/packages.py`, `components/packages/`) is the cleanest full example: a capability per manager, pure parsers, jobs, audit, UI gated by `capability: "packages.*"`.
- **Server patterns** (jobs, audit, running commands, parsers and fixtures, API tests, settings) are in `apps/server/AGENTS.md` → Conventions and Tests; **UI patterns** (data loading, capabilities, feedback, live output) in `apps/web/AGENTS.md` → Conventions.
