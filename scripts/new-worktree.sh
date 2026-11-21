#!/usr/bin/env bash
# Start a new agent task on its own worktree + feature branch from origin/main,
# leaving the base checkout on main (see AGENTS.md -> Git workflow). Usage:
#   scripts/new-worktree.sh <type>/<topic>
#
# Creates ../worktrees/athena-<topic> (next to the base checkout) on branch <type>/<topic>.
# Works the same when run from inside another worktree.
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: $0 <type>/<topic>" >&2
  echo "example: $0 feat/store-app-view-hooks" >&2
  exit 1
fi

branch="$1"
case "$branch" in
  */*) ;;
  *)
    echo "error: branch must be type/topic (e.g. feat/foo, fix/bar)" >&2
    exit 1
    ;;
esac
topic="${branch#*/}"
topic="${topic//\//-}"

# The base checkout's folder, even when run from a linked worktree.
base="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
cd "$base" || exit 1

worktree_dir="$(cd .. && pwd)/worktrees/athena-$topic"
if [ -e "$worktree_dir" ]; then
  echo "error: worktree dir already exists: $worktree_dir" >&2
  exit 1
fi

echo "==> creating worktree at $worktree_dir on $branch from origin/main"
git fetch origin
mkdir -p "$(dirname "$worktree_dir")"
git worktree add "$worktree_dir" -b "$branch" origin/main

echo
echo "==> work in $worktree_dir. OpenCode: opencode session_move --directory \"$worktree_dir\""
echo
echo "==> after the PR merges, clean up:"
echo "    git worktree remove $worktree_dir"
