# Dependencies and APIs

_How to check a library API before using it. Read it when you call an API you haven't seen in this repo, when a symbol you expect isn't found, or when existing code disagrees with what you remember._

Most of the stack here is newer than most models' training data, so an API "remembered" from training is often wrong. Evidence, strongest first: the installed code and its types, the tests and checks that run against it, the official docs for the installed version, then memory. Never let memory or a docs example override the installed code.

## Order of lookup

1. **Find the installed version.** The lockfiles are the truth, not the ranges in the manifests: `pnpm-lock.yaml` (or `pnpm why <pkg>` from the repo root), `apps/server/uv.lock` (or `cd apps/server && uv pip show <pkg>`).
2. **Read what's installed and how the repo already uses it.** `rg` for existing call sites first and copy their shape. Then the package's own types and source: `node_modules/<pkg>/` (its .d.ts files), the project venv (`cd apps/server && uv run python -c 'import <pkg>; print(<pkg>.__file__)'` prints where). A symbol that isn't there doesn't exist in this version, whatever the docs say.
3. **Then the docs for that version:** Context7 (MCP `context7`: resolve the library, then ask about the API and version), the official docs, or a bundled copy (Next ships its docs in `apps/web/node_modules/next/dist/docs/`; shadcn has its skill and MCP).
4. **Reconcile.** If the docs and the installed code disagree, the installed code wins; say so in your report.

Skip the lookup for APIs you've just seen used the same way in this repo, and for the standard library. Don't fetch the same docs twice in one task. If neither docs nor source settle it, stop and say what's missing; never invent a function, option or argument to fill the gap.

## Libraries that trip agents up

| Library | Installed (Nov 2026) | Where to check | Known traps |
|---|---|---|---|
| Next.js | 16.4 | `apps/web/node_modules/next/dist/docs/` | Static export only: no server actions, API routes or dynamic routes (`apps/web/AGENTS.md`) |
| React | 19.3 | Context7, react.dev | |
| Base UI (`@base-ui/react`) | 1.9 | Context7, the `shadcn` skill | shadcn here sits on Base UI, not Radix: props like `asChild` differ (`render`) |
| Tailwind CSS | 4 | Context7 | v4 config lives in CSS, not `tailwind.config.js` | <!-- docs-check: ignore -->
| xterm.js (`@xterm/xterm`) | 6 | Context7, the package's .d.ts files | Scoped `@xterm/*` package names; addons are separate packages |
| FastAPI | 0.165 | Context7 | |
| SQLModel / Alembic | 0.0.50 / 1.20 | Context7; existing migrations in `apps/server/src/athena/db/migrations/` | Every model change needs a migration (post-release rule) |
| pydantic | 2.14 | the `pydantic` skill | v2: `.dict()` and `class Config` are deprecated; use `model_dump()` and `model_config` |
| pydantic-ai (`pydantic-ai-slim`) | 2.71 | the `building-pydantic-ai-agents` skill, `docs/agents/gotchas/assistant.md` | 2.x API differs a lot from 0.x/1.x examples on the web |
| pydantic-ai-harness | 0.71 (pinned) | the `pydantic-ai-harness` skill | Pinned on purpose (see STATUS → browser) |

The versions are a snapshot to show how new things are; the lockfiles stay authoritative. Update a row when you upgrade a library, and add one when a library caused a real wrong-API bug.

## Changing dependencies

- Don't add, upgrade or remove a dependency as a side effect of a feature. If a feature needs one, say why the current stack can't do it, use an open-source license, and record it in `docs/design/licenses.md`.
- Upgrades are their own PR (`build(deps): …`), with the changelog or migration guide read and the full `scripts/check.sh` run.
