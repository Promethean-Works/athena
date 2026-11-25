---
name: athena-ship
description: Takes an Athena change from "code written" to an open PR with auto-merge - branch, local checks, commit, PR, the CI triage table for later checks, and the STATUS handoff. Never waits for CI. Use whenever you are about to commit, push, open or update a pull request, when asked to "check" a PR or CI, when a check failed, or when finishing a task or session.
---

# Ship an Athena change

Follow these steps in order. Each step says what "done" looks like and when it applies: run what the diff needs, not everything. Every PR still needs the title check and auto-merge.

## 1. Be on the right branch

```bash
git status -sb          # where am I, is anything uncommitted?
```

- **Always work in your own worktree, never in the base checkout** (it stays on `main`; `scripts/agent-guard.mjs` refuses edits there and the pre-commit hook rejects commits). Start the session in one your agent's native way (AGENTS.md → Git workflow) and name the branch `<type>/<topic>`. If you're in the base checkout, or in a worktree for a different task, create one with `scripts/new-worktree.sh <type>/<topic>` and work in the folder it prints. Remove it after the merge: `git worktree remove <path>`.
- If you already edited files in the base checkout by mistake: `git stash`, create the worktree, then `git -C ../worktrees/athena-<topic> stash pop`.
- Types: `feat`, `fix`, `perf`, `docs`, `refactor`, `test`, `build`, `ci`, `chore`, `revert`.

## 2. Run the local checks

```bash
scripts/check.sh repo       # docs, skills, agent config, scripts only
scripts/check.sh --quick    # code: repo, web (lint, types, API client drift), server (ruff, pytest), no web build
scripts/check.sh            # everything CI runs, web build included: before pushing web changes
```

Run the parts the diff touches, once. The pre-push hook runs them again by itself, so don't run a full check just before pushing a docs change. Done when it prints "All checks passed". If it regenerated `packages/api-client`, commit those files.

If `git config core.hooksPath` doesn't print `.githooks`, run `git config core.hooksPath .githooks` (required for agents): it turns on both the pre-commit guard (no commits on `main` or in the base checkout) and the pre-push checks.

If the docs check fails, you renamed or removed something that an `AGENTS.md`, a file in `docs/agents/` or a skill still names. Fix the doc in the same commit; don't silence it.

Also, depending on what changed:
- **Something users see or do** (a page, component, style, or an API the UI calls): browser verification with the `athena-ui-verify` skill, in the `ui-verify` subagent where your agent has one (`docs/agents/subagents.md`). Required before saying "done". Not for docs, comments, `apps/web/AGENTS.md` or test-only changes.
- **A database model:** a new migration (see the `athena-recipes` skill). `tests/test_db.py` fails without one.
- **A new dependency:** add its license to `docs/design/licenses.md`. Open-source only.
- **A design change:** update its section in `docs/design/` and add a row to `docs/design/decisions.md`.

## 3. Review

When the diff changes code (`apps/`, `packages/`, `scripts/`, `catalog/`, workflows) or is over about 100 lines, have it reviewed before the PR. Skip it for small docs-only diffs (a review costs 30–40k tokens): the `reviewer` subagent (`/review-diff`; oh-my-pi's bundled `reviewer` and Hermes's `delegate_task` need "follow `.agents/skills/athena-review/SKILL.md`, read-only" in the brief). Give it the diff, not your conclusions. Fix what it finds that's real, and say in the PR body what you didn't fix and why.

## 4. Commit

- Use Conventional Commit messages (`feat(files): add folder upload`), and explain _why_ in the body.
- Don't touch `CHANGELOG.md` or `version.txt`.
- Never commit to `main`, and never force-push (it's blocked). To bring in `main`: `git merge origin/main`, not a rebase.
- Merge conflict in `packages/api-client/*`: don't hand-merge it. Take either side, run `pnpm gen:api`, and commit. Search for leftover markers before committing: `git grep -n '^<<<<<<< '`.

## 5. Open the PR and turn on auto-merge

```bash
git push -u origin HEAD
gh pr create --title "<type>(<scope>): <summary>" --body "<what, why, how it was verified, what wasn't>"
gh pr merge <n> --squash --auto --delete-branch      # always, without asking
```

- The title becomes the squash commit and the changelog line, so make it Conventional and specific.
- In the body, state what was verified and how (tests, browser, real host), and what wasn't verified. End it with the attribution line your tool requires, if any.
- Auto-merge exceptions: release-please PRs (the maintainer merges those), and PRs whose base isn't `main`. Turn it on for those only after GitHub retargets them to `main`.

## 6. Don't wait for CI

Once the PR is open with auto-merge on, stop: don't watch or poll its checks (`gh pr checks --watch`, sleep loops, re-running `gh pr checks` until nothing is pending). Waiting costs tokens and auto-merge doesn't need you. Report the PR as open with auto-merge on, and say merged only if `gh pr view` already showed `MERGED`. CI failures and CodeQL alerts are handled when the maintainer says "check" (`athena-check-prs`), one pass at a time, with the commands and table below.

```bash
gh pr checks <n>                                   # summary, read once
gh run view <run-id> --log-failed | tail -80       # the failing step's output
gh api 'repos/Promethean-Works/athena/code-scanning/alerts?state=open&ref=refs/pull/<n>/merge' \
  --jq '.[] | "\(.rule.id) \(.most_recent_instance.location.path):\(.most_recent_instance.location.start_line) \(.rule.description)"'
gh pr view <n> --json state,mergeStateStatus,mergedAt
```

Triage table:

| Symptom | Likely cause | Action |
|---|---|---|
| Only `server (windows-latest)` fails | Paths, encoding, CRLF, trailing dots | See `docs/agents/gotchas/windows.md`; fix and push |
| Only `server (macos-latest)` fails | A CLI missing on the runner (e.g. no `docker`) | Make the test really hide or stub the tool |
| A job was **cancelled**, not failed | macOS runner capacity | `gh run rerun <run-id> --failed` |
| `web` fails at "API client is up to date" | You changed the API without regenerating | `pnpm gen:api`, commit |
| `install script (windows-latest)` lint | PSScriptAnalyzer | You can't run it locally without pwsh; read the log and fix exactly what it names |
| CodeQL fails | A code scanning alert | Fix it in code (`docs/agents/gotchas/codeql.md` lists the known false-positive shapes). Don't dismiss alerts; that's the maintainer's call |
| `pr-title` fails | Title isn't `type(scope): summary` | `gh pr edit <n> --title "..."` |
| Merge state `BEHIND` / `DIRTY` | `main` moved (often STATUS.md) | `git merge origin/main`, resolve, push |

Done when the PR is open with auto-merge on. Auto-merge waits only for the required checks (`ci-ok`, `pr-title`); CodeQL alerts are looked at in the next "check". Never say "merged" without seeing `MERGED`.

## 7. Hand off

Before ending the session, on the branch (or in a follow-up docs PR):
- `docs/STATUS.md`: take finished items out and add one short bullet each to `docs/HISTORY.md` with the PR number: append with the shell (`cat >> docs/HISTORY.md <<'EOF'`), never by opening it (100 KB). Under In progress, say exactly where you stopped and the next concrete step. Keep STATUS under 6 KB (the docs check enforces it; ideas go to `docs/design/milestones.md` → Backlog).
- `docs/agents/gotchas/<area>.md`: add anything non-obvious you learned (a surprising failure, a tool quirk, a pattern).
- Report to the maintainer: the PRs opened (with links, auto-merge on), what merged if you saw it, what was verified and what wasn't, and the bugs fixed along the way.
