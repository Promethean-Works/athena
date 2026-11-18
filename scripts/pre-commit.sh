#!/usr/bin/env bash
# Git pre-commit hook: forbids committing directly to main/master.
# Commits must go through a feature branch + PR (see AGENTS.md git workflow).
set -uo pipefail

if [ "${ATHENA_ALLOW_MAIN_COMMIT:-0}" = 1 ]; then
  echo "pre-commit: ATHENA_ALLOW_MAIN_COMMIT=1, allowing commit to main"
  exit 0
fi

cd "$(git rev-parse --show-toplevel)" || exit 1

branch=$(git symbolic-ref --short HEAD 2>/dev/null || true)

# Allow commits while mid-rebase/mid-cherry-pick (HEAD is detached there); only
# block when we're actually on main/master.
case "$branch" in
  main|master)
    echo "pre-commit: ERROR: committing directly to '$branch' is not allowed."
    echo "Create a feature branch instead: git switch -c feat/<description>"
    echo "Skip once (emergency only): ATHENA_ALLOW_MAIN_COMMIT=1 git commit ..."
    exit 1
    ;;
  *)
    exit 0
    ;;
esac
