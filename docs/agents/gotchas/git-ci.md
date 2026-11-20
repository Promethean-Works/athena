# Gotchas: Git, GitHub and CI

CI jobs (`.github/workflows/ci.yml`):

- `repo checks`: agent config sync, the docs check (`check-docs.mjs`), the `.claude/skills` symlink, actionlint, shellcheck.
- `install script` on 3 OSes: dry runs plus PSScriptAnalyzer.
- `web`: API client drift, lint, typecheck, build.
- `server` on 3 OSes: ruff, pytest, service dry run.
- `ci-ok`: the single required check.

Other workflows: `pr-title`, CodeQL (separate; it can block merges), and `E2E` (`e2e.yml`). E2E is slow and not part of `ci-ok`. It runs on pushes to main, on installer or service changes, and on demand.

- Force pushes are blocked, so don't rebase a pushed branch. To bring in `main`, merge it into the branch; the squash merge hides the merge commit.
- When a PR stacked on another PR's branch has its base merged, GitHub retargets it to `main`. Merging `main` in then shows conflicts that are only squash artifacts. Resolve them toward `main`'s content.
- Don't turn on auto-merge for a PR whose base is another feature branch. That branch isn't protected, so it merges immediately into the wrong base.
- Two open PRs that both edit `docs/STATUS.md` or `AGENTS.md` will conflict. The second one needs its branch updated and the docs merged by hand; auto-merge won't do it.
- Never commit conflict markers into a generated file. For `packages/api-client/openapi.json` (or the generated types), resolve a conflict by rerunning `pnpm gen:api`, not by editing. Once, markers were committed and `web` failed.
- A macOS runner can sit queued for a long time and then be _cancelled_, which fails `ci-ok` with no code problem. Re-run the failed jobs.
- Dependabot can't fix a transitive pnpm dependency. Add an override in `pnpm-workspace.yaml` with a comment saying why (see the existing `baseline-browser-mapping`, `brace-expansion` and `minimatch` overrides), and remove it once upstream ships a fix.
- `pr-title` accepts Dependabot's capitalized "Bump …" subject; only the Conventional Commit type is enforced.
- release-please PRs need the `RELEASE_PLEASE_TOKEN` secret to run CI (see STATUS → Blockers). Don't merge a release PR yourself.
- The first release is 0.1.0 because of explicit config. release-please defaults to 1.0.0 without it.
- `gitleaks dir .` (in `scripts/check.sh` and the pre-push hook) ignores `.gitignore`, so it scanned pytest's `__pycache__` (the compiled secret-guard tests hold fake tokens) and `.next/cache`, and failed every push after a local test run. `.gitleaks.toml` allowlists those build-output folders; add any new build-output folder there too.
