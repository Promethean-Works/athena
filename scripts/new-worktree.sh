#!/usr/bin/env bash
# Start a new agent task on its own worktree + feature branch, leaving the base
# repo on main. Usage:
#   scripts/new-worktree.sh feat/<short-description>
#
# Prints the `opencode session_move` command to run so the session (and VS Code
# pointed at the base repo) stays on main while the agent works in the worktree.
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: $0 <type>/<short-description>" >&2
  echo "example: $0 feat/store-app-view-hooks" >&2
  exit 1
fi

branch="$1"
case "$branch" in
  */*) ;;
  *)
    echo "error: branch must be type/description (e.g. feat/foo, fix/bar)" >&2
    exit 1
    ;;
esac

cd "$(git rev-parse --show-toplevel)" || exit 1

echo "==> switching base to main and pulling"
git switch main
git pull --ff-only

echo "==> creating branch $branch from main"
git switch -c "$branch"

worktree_dir="../worktrees/$branch"
if [ -e "$worktree_dir" ]; then
  echo "error: worktree dir already exists: $worktree_dir" >&2
  exit 1
fi

echo "==> creating worktree at $worktree_dir"
git worktree add "$worktree_dir" "$branch"

echo
echo "==> move this session into the worktree so VS Code (on the base repo) stays on main:"
echo "    opencode session_move --directory \"$worktree_dir\""
echo
echo "==> when done, commit on $branch, push, open a PR, then clean up:"
echo "    git worktree remove $worktree_dir"
echo "    git branch -d $branch"
