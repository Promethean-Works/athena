#!/usr/bin/env bash
# Remove worktrees whose PR is merged, with their local and remote branches.
# Usage:
#   scripts/clean-worktrees.sh          # dry run: list what would be removed
#   scripts/clean-worktrees.sh --yes    # remove them
#   scripts/clean-worktrees.sh --yes --force   # also remove worktrees with uncommitted changes
#
# "Merged" means GitHub has a merged PR from that branch (main is squash-merged, so
# git's own --merged check can't tell). A worktree is kept when its branch has commits
# the merged PR didn't include, when it has uncommitted changes (unless --force), when
# it is detached, and when it is the one this script runs in. Worktrees whose folder is
# gone are pruned. Needs `gh` signed in.
set -euo pipefail

apply=0
force=0
for arg in "$@"; do
  case "$arg" in
    --yes | -y) apply=1 ;;
    --force) force=1 ;;
    -h | --help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "error: unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

command -v gh >/dev/null || { echo "error: gh is not installed" >&2; exit 1; }

# The base checkout's folder, even when run from a linked worktree.
base="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
here="$(git rev-parse --show-toplevel)"
cd "$base"

echo "==> fetching origin"
git fetch --prune --quiet origin

if [ "$apply" = 1 ]; then
  git worktree prune --verbose
else
  git worktree prune --dry-run --verbose
fi

# One line per merged PR: "<branch> <head sha> <number>".
merged="$(mktemp)"
trap 'rm -f "$merged"' EXIT
gh pr list --state merged --limit 1000 --json headRefName,headRefOid,number \
  --jq '.[] | "\(.headRefName) \(.headRefOid) \(.number)"' >"$merged"

# Prints the merged PR number whose head contains everything on <branch>, or nothing.
merged_pr() {
  local branch="$1" tip name oid number
  tip="$(git rev-parse --verify --quiet "refs/heads/$branch")" || return 0
  while read -r name oid number; do
    [ "$name" = "$branch" ] || continue
    if [ "$tip" = "$oid" ]; then echo "$number"; return 0; fi
    # Local branch behind the PR head (e.g. pushed from elsewhere) is fine too.
    if git cat-file -e "$oid^{commit}" 2>/dev/null &&
      git merge-base --is-ancestor "$tip" "$oid"; then
      echo "$number"
      return 0
    fi
  done <"$merged"
}

removed=0
kept=0
path=""
branch=""
# `git worktree list --porcelain`: blocks of "worktree <path>", "HEAD <sha>",
# "branch refs/heads/<name>" or "detached", separated by a blank line.
while IFS= read -r line || [ -n "$path" ]; do
  case "$line" in
    "worktree "*) path="${line#worktree }"; branch=""; continue ;;
    "branch refs/heads/"*) branch="${line#branch refs/heads/}"; continue ;;
    "") ;;
    *) continue ;;
  esac
  [ -n "$path" ] || continue
  p="$path" b="$branch"
  path="" branch=""

  [ "$p" = "$base" ] && continue
  [ -d "$p" ] || continue # prunable: handled by `git worktree prune` above
  if [ -z "$b" ]; then
    echo "keep  $p (detached HEAD)"; kept=$((kept + 1)); continue
  fi
  pr="$(merged_pr "$b")"
  if [ -z "$pr" ]; then
    echo "keep  $p [$b] (no merged PR, or commits after the merge)"; kept=$((kept + 1)); continue
  fi
  if [ "$p" = "$here" ]; then
    echo "keep  $p [$b] (merged in #$pr, but this script runs in it)"; kept=$((kept + 1)); continue
  fi
  dirty="$(git -C "$p" status --porcelain)"
  if [ -n "$dirty" ] && [ "$force" = 0 ]; then
    echo "keep  $p [$b] (merged in #$pr, but has uncommitted changes; --force removes it)"
    kept=$((kept + 1)); continue
  fi

  remote=""
  git ls-remote --exit-code --heads origin "$b" >/dev/null 2>&1 && remote=" + origin/$b"
  echo "clean $p [$b$remote] (merged in #$pr)"
  removed=$((removed + 1))
  [ "$apply" = 1 ] || continue

  if [ -n "$dirty" ]; then
    git worktree remove --force "$p"
  else
    git worktree remove "$p"
  fi
  git branch -D "$b" >/dev/null # -D: squash merges aren't ancestors of main
  [ -z "$remote" ] || git push --quiet origin --delete "$b"
done < <(git worktree list --porcelain)

echo
if [ "$apply" = 1 ]; then
  echo "==> removed $removed worktree(s), kept $kept"
else
  echo "==> would remove $removed worktree(s), keep $kept. Run with --yes to remove them."
fi
