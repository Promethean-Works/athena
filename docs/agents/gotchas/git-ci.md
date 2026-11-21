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
- Every file that holds the version needs an `extra-files` entry in `release-please-config.json`, or the release PR fails CI. `apps/server/uv.lock` uses `$.package[?(@.name.value=='athena-server')].version`: release-please's TOML parser wraps strings, so `@.name` alone matches nothing. `athena openapi` pins `info.version` to `0.0.0` so `packages/api-client` doesn't change on a bump (the JSON updater would also rewrite its `\u2026` escapes).
- Releases are drafts until the `release assets` job uploads the wheel and publishes. `force-tag-creation` pushes the tag up front, because GitHub only tags a draft on publish and release-please finds the last release by its tag. If the job fails, fix and re-run it; the draft is still there.
- `gitleaks dir .` (in `scripts/check.sh` and the pre-push hook) ignores `.gitignore`, so it scanned pytest's `__pycache__` (the compiled secret-guard tests hold fake tokens) and `.next/cache`, and failed every push after a local test run. `.gitleaks.toml` allowlists those build-output folders; add any new build-output folder there too.
- **Tests that run `git` must drop the `GIT_*` variables** (`monkeypatch.delenv`). The pre-commit and pre-push hooks run pytest with `GIT_DIR`/`GIT_INDEX_FILE` set, so a test's `git init` in `tmp_path` acts on the real repository instead: it once set `core.bare = true` in the shared `.git/config`, which breaks the base checkout and every worktree ("must be run in a work tree"). Fix: `git config --file .git/config core.bare false`. <!-- docs-check: ignore -->
- `tests/test_terminal.py::test_pty_output_and_exit_code` sometimes fails on macOS CI with empty output (seen on #196, passed on a rerun). Rerun the failed job (`gh run rerun <id> --failed`, only after the whole run finishes) before debugging.
