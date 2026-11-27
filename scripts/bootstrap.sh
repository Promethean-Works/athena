#!/usr/bin/env bash
# One command from a fresh clone to a working dev machine (macOS and Linux).
#   scripts/bootstrap.sh              install tools, dependencies, git hooks; then offer agent setup
#   scripts/bootstrap.sh --no-agents  skip the coding-agent setup
#   scripts/bootstrap.sh --check      only report what is missing (changes nothing)
# Tools come from the Brewfile (Homebrew). Without Homebrew it lists what to install by hand.
# Windows: see docs/DEVELOPMENT.md (winget list). Safe to re-run.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

CHECK=0
AGENTS=1
for a in "$@"; do
  case "$a" in
    --check) CHECK=1 ;;
    --no-agents) AGENTS=0 ;;
    -h | --help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown argument: $a" >&2; exit 2 ;;
  esac
done

has() { command -v "$1" >/dev/null 2>&1; }
missing=()
for t in git node pnpm uv gh; do has "$t" || missing+=("$t"); done
optional=()
for t in gitleaks shellcheck actionlint trivy docker; do has "$t" || optional+=("$t"); done

if [ "$CHECK" = 1 ]; then
  echo "required missing: ${missing[*]:-none}"
  echo "optional missing: ${optional[*]:-none}"
  git config core.hooksPath >/dev/null || echo "git hooks: not enabled"
  [ -d node_modules ] || echo "web dependencies: not installed (pnpm install)"
  [ -d apps/server/.venv ] || echo "server environment: not created (uv sync)"
  [ ${#missing[@]} -eq 0 ]
  exit $?
fi

if [ ${#missing[@]} -gt 0 ] || [ ${#optional[@]} -gt 0 ]; then
  if has brew; then
    echo "==> brew bundle (Brewfile)"
    brew bundle --file=Brewfile || echo "warning: some Brewfile items failed; continuing" >&2
    hash -r
  else
    echo "Homebrew not found. Install it (https://brew.sh) and re-run, or install by hand:" >&2
    echo "  required: ${missing[*]:-none}   optional: ${optional[*]:-none}" >&2
    echo "  (Linux: your package manager; uv: https://docs.astral.sh/uv/; pnpm: corepack enable)" >&2
  fi
fi

for t in git node pnpm uv gh; do
  has "$t" || { echo "still missing: $t" >&2; exit 1; }
done

echo "==> web dependencies"
pnpm install --frozen-lockfile || exit 1
echo "==> server environment (Python 3.13)"
(cd apps/server && uv sync) || exit 1
echo "==> git hooks"
git config core.hooksPath .githooks

gh auth status >/dev/null 2>&1 || echo "note: run 'gh auth login' (PRs, CI, auto-merge)"

if [ "$AGENTS" = 1 ]; then
  echo "==> coding agents (asks before changing anything)"
  node scripts/agents-setup.mjs
fi

echo
echo "Done. Verify with: scripts/check.sh --quick"
