#!/usr/bin/env bash
# Runs the same checks as CI (.github/workflows/ci.yml) on this machine, so you know
# before pushing whether `ci-ok` will pass. Run from anywhere inside the repo.
#
#   scripts/check.sh            everything (repo, web, server)
#   scripts/check.sh --quick    skip the web build (the slowest step)
#   scripts/check.sh web        only the web checks (also: server, repo)
#   --quiet / --verbose         print only ok/FAIL per step plus the end of a failing step's
#                               output, or everything. Default: quiet when stdout isn't a
#                               terminal (agents), so passing steps cost no tokens.
#
# What CI runs that this can't: the other two operating systems. Windows-only failures
# (paths, CRLF, PowerShell lint without pwsh) still show up only in CI. See
# docs/agents/gotchas/windows.md.
set -uo pipefail

cd "$(git rev-parse --show-toplevel)" || exit 1

QUICK=0
QUIET=0
[ -t 1 ] || QUIET=1
PARTS=()
for arg in "$@"; do
  case "$arg" in
    --quick) QUICK=1 ;;
    --quiet) QUIET=1 ;;
    --verbose) QUIET=0 ;;
    web | server | repo) PARTS+=("$arg") ;;
    -h | --help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg (see --help)" >&2; exit 2 ;;
  esac
done
[ ${#PARTS[@]} -eq 0 ] && PARTS=(repo web server)

FAILED=()
SKIPPED=()

# Colors only on a terminal: escape codes are noise (and tokens) in an agent's log.
if [ -t 1 ]; then B=$'\033[1m' G=$'\033[32m' R=$'\033[31m' Y=$'\033[33m' N=$'\033[0m'; else B='' G='' R='' Y='' N=''; fi
LOGS=""
if [ "$QUIET" = 1 ]; then
  tmp="${TMPDIR:-/tmp}"
  LOGS=$(mktemp -d "${tmp%/}/athena-check.XXXXXX")
  echo "quiet mode: full output of each step in $LOGS (use --verbose to stream it)"
fi

step() { # step <name> <command...>
  local name="$1" log
  shift
  if [ "$QUIET" = 1 ]; then
    log="$LOGS/$(printf '%s' "$name" | tr -c 'A-Za-z0-9' '_').log"
    if "$@" >"$log" 2>&1; then
      printf '%sok%s  %s\n' "$G" "$N" "$name"
    else
      printf '%sFAIL%s %s (last 40 lines; full log: %s)\n' "$R" "$N" "$name" "$log"
      tail -n 40 "$log" | sed 's/^/  | /'
      FAILED+=("$name")
    fi
    return
  fi
  printf '\n%s== %s%s\n' "$B" "$name" "$N"
  if "$@"; then
    printf '%sok%s  %s\n' "$G" "$N" "$name"
  else
    printf '%sFAIL%s %s\n' "$R" "$N" "$name"
    FAILED+=("$name")
  fi
}

skip() { # skip <name> <reason>
  printf '%sskip%s %s (%s)\n' "$Y" "$N" "$1" "$2"
  SKIPPED+=("$1")
}

api_client_up_to_date() {
  local before after
  before=$(git diff -- packages/api-client | git hash-object --stdin)
  pnpm gen:api >/dev/null || return 1
  after=$(git diff -- packages/api-client | git hash-object --stdin)
  if [ "$before" != "$after" ]; then
    echo "packages/api-client was out of date. It has been regenerated; commit the result."
    return 1
  fi
}

has() { command -v "$1" >/dev/null 2>&1; }

for part in "${PARTS[@]}"; do
  case "$part" in
    repo)
      step "agent config in sync (.mcp.json -> opencode.json)" node scripts/agents-sync.mjs --check
      step "docs point at real files and names" node scripts/check-docs.mjs
      step ".claude/skills points at .agents/skills" test "$(readlink .claude/skills)" = "../.agents/skills"
      if has shellcheck; then step "shellcheck" shellcheck scripts/*.sh; else skip "shellcheck" "not installed"; fi
      if has actionlint; then step "actionlint" actionlint; else skip "actionlint" "not installed"; fi
      if has pwsh; then
        # shellcheck disable=SC2016 # PowerShell code: $i must reach pwsh unexpanded.
        step "PSScriptAnalyzer" pwsh -NoProfile -Command \
          'if (-not (Get-Module -ListAvailable PSScriptAnalyzer)) { Install-Module PSScriptAnalyzer -Force -Scope CurrentUser }; $i = Invoke-ScriptAnalyzer -Path scripts/install.ps1 -Severity Warning,Error; $i | Format-Table -AutoSize; if ($i) { exit 1 }'
      else
        skip "PSScriptAnalyzer" "pwsh not installed; CI's Windows job is the first check"
      fi
      step "install.sh dry run" bash -c 'bash scripts/install.sh --dry-run --version 0.0.0 >/dev/null && bash scripts/install.sh --dry-run --uninstall --purge >/dev/null'
      ;;
    web)
      [ -d node_modules ] || step "pnpm install" pnpm install --frozen-lockfile
      step "API client up to date (pnpm gen:api)" api_client_up_to_date
      step "web lint" pnpm lint
      step "web typecheck" pnpm typecheck
      if [ "$QUICK" = 1 ]; then skip "web build" "--quick"; else step "web build (static export)" pnpm build; fi
      ;;
    server)
      step "ruff check" bash -c 'cd apps/server && uv run ruff check'
      step "ruff format --check" bash -c 'cd apps/server && uv run ruff format --check'
      step "pytest" bash -c 'cd apps/server && uv run pytest -q'
      step "service install dry run" bash -c 'cd apps/server && uv run athena service install --dry-run >/dev/null'
      ;;
  esac
done

echo
if [ ${#SKIPPED[@]} -gt 0 ]; then echo "Skipped: ${SKIPPED[*]}"; fi
if [ ${#FAILED[@]} -gt 0 ]; then
  printf '%sFailed (%d): %s%s\n' "$R" "${#FAILED[@]}" "$(IFS=,; echo "${FAILED[*]}")" "$N"
  exit 1
fi
[ -n "$LOGS" ] && rm -rf "$LOGS"
printf '%sAll checks passed.%s Windows and macOS-only issues still need CI.\n' "$G" "$N"
