#!/usr/bin/env bash
# Git pre-commit hook: scans staged changes for secrets (gitleaks, when installed),
# forbids committing directly to main/master, and committing from the base checkout at all. Every task gets its own worktree
# on a feature branch (see AGENTS.md git workflow), so the base checkout stays
# on a clean main and parallel agent sessions never clobber each other.
set -uo pipefail

if [ "${ATHENA_ALLOW_MAIN_COMMIT:-0}" = 1 ]; then
  echo "pre-commit: ATHENA_ALLOW_MAIN_COMMIT=1, skipping branch/worktree checks"
  exit 0
fi

cd "$(git rev-parse --show-toplevel)" || exit 1

# Secrets: block a commit that adds one. CI scans the tree too (repo checks).
if command -v gitleaks >/dev/null 2>&1; then
  if ! gitleaks git --pre-commit --staged --redact --no-banner --log-level warn .; then
    echo "pre-commit: ERROR: gitleaks found a secret in the staged changes (above)."
    echo "Remove it (use an environment variable or the data dir). False positive: add an allowlist to .gitleaks.toml."
    exit 1
  fi
else
  echo "pre-commit: gitleaks not installed, secret scan skipped (node scripts/agents-setup.mjs installs it)"
fi

branch=$(git symbolic-ref --short HEAD 2>/dev/null || true)
git_dir=$(cd "$(git rev-parse --git-dir)" && pwd -P)
common_dir=$(cd "$(git rev-parse --git-common-dir)" && pwd -P)

fix_hint() {
  echo "Move your changes to a worktree instead:"
  echo "  git stash"
  echo "  git fetch origin && git worktree add ../athena-<topic> -b <type>/<topic> origin/main"
  echo "  git -C ../athena-<topic> stash pop"
  echo "Skip once (emergency only): ATHENA_ALLOW_MAIN_COMMIT=1 git commit ..."
}

# Allow commits while mid-rebase/mid-cherry-pick (HEAD is detached there).
case "$branch" in
  main|master)
    echo "pre-commit: ERROR: committing directly to '$branch' is not allowed."
    fix_hint
    exit 1
    ;;
esac

# In a linked worktree, git-dir is .git/worktrees/<name>; in the base checkout
# it equals the common dir.
if [ -n "$branch" ] && [ "$git_dir" = "$common_dir" ]; then
  echo "pre-commit: ERROR: committing in the base checkout is not allowed (branch '$branch')."
  echo "The base checkout stays on main; every task works in its own git worktree."
  fix_hint
  exit 1
fi

exit 0
