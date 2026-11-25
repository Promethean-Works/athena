---
name: athena-check-prs
description: Checks Athena's open pull requests - CI, CodeQL, auto-merge, merge conflicts - fixes failures on the PR branch and reports what merged and what didn't. One pass, never waiting on running checks. Use when the maintainer says "check", "check now", "check the PRs" or "keep observing the PRs".
---

# Check the PRs

1. List them: `gh pr list --state open --json number,title,headRefName,autoMergeRequest,mergeStateStatus`. Skip release-please PRs (the maintainer merges those).
2. For each PR:
   - `gh pr checks <n>`; for a failure, `gh run view <run-id> --log-failed | tail -80`. The table of known failures and fixes is in the `athena-ship` skill (step 6) and `docs/agents/gotchas/git-ci.md`.
   - Fix it in that PR's worktree (`git worktree list`; create one from the PR branch if needed: `git worktree add ../worktrees/athena-<topic> <branch>`). Never fix on `main`.
   - Behind `main` or conflicting: `git merge origin/main` (no rebase; force pushes are blocked). Generated files (`packages/api-client`) are regenerated, not hand-merged.
   - Auto-merge off on a PR to `main`: turn it on (`gh pr merge <n> --squash --auto --delete-branch`).
   - Also look at CodeQL: `gh api "repos/Promethean-Works/athena/code-scanning/alerts?state=open&ref=refs/pull/<n>/merge"`. Fix alerts in code; dismissing is the maintainer's call.
3. One pass only: read each PR's state as it is now, fix what failed, and report. Never wait for running checks (`gh pr checks --watch`, sleep or polling loops), even when asked to "keep observing": report them as pending, and the maintainer checks again later.
4. Report per PR: merged / waiting (on what) / failing (why, what you pushed). Never say a PR merged without seeing `MERGED` in `gh pr view <n> --json state`. After a merge, remove its worktree and move its STATUS item to HISTORY (`athena-handoff`).
