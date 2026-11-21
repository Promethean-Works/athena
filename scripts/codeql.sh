#!/usr/bin/env bash
# Run CodeQL locally, the same languages and query suites as GitHub's default setup.
#   scripts/codeql.sh [create|analyze|all] [python|javascript-typescript|actions ...]
# Default: all three languages, create then analyze. Databases go to .codeql/databases/<lang>
# (the VS Code CodeQL extension lists them under "Databases"); SARIF goes to .codeql/results/<lang>.sarif
# (open it with the SARIF Viewer extension or "CodeQL: Open ... SARIF"). The CLI is found on PATH,
# in $CODEQL, or in the VS Code extension's download.
set -euo pipefail
cd "$(dirname "$0")/.."

find_codeql() {
  if [ -n "${CODEQL:-}" ]; then echo "$CODEQL"; return; fi
  if command -v codeql >/dev/null 2>&1; then command -v codeql; return; fi
  local d
  for d in \
    "$HOME/Library/Application Support/Code/User/globalStorage/github.vscode-codeql" \
    "$HOME/Library/Application Support/Code - Insiders/User/globalStorage/github.vscode-codeql" \
    "$HOME/.config/Code/User/globalStorage/github.vscode-codeql" \
    "$HOME/.config/Code - Insiders/User/globalStorage/github.vscode-codeql" \
    "$HOME/.vscode-server/data/User/globalStorage/github.vscode-codeql" \
    "${APPDATA:-/nonexistent}/Code/User/globalStorage/github.vscode-codeql"; do
    for c in "$d"/distribution*/codeql/codeql "$d"/distribution*/codeql/codeql.exe; do
      if [ -x "$c" ]; then echo "$c"; return; fi
    done
  done
  echo "error: CodeQL CLI not found. Install the CodeQL VS Code extension (it downloads the CLI) or set CODEQL=/path/to/codeql." >&2
  exit 1
}

mode="all"
case "${1:-}" in create | analyze | all) mode="$1"; shift ;; esac
langs=("$@")
[ ${#langs[@]} -gt 0 ] || langs=(python javascript-typescript actions)

CODEQL_BIN="$(find_codeql)"
config=".github/codeql/codeql-config.yml"
mkdir -p .codeql/databases .codeql/results

for lang in "${langs[@]}"; do
  db=".codeql/databases/$lang"
  case "$lang" in
    python | javascript-typescript | actions) ;;
    *) echo "error: unknown language $lang" >&2; exit 1 ;;
  esac
  if [ "$mode" != analyze ]; then
    echo "==> [$lang] creating database"
    "$CODEQL_BIN" database create "$db" --language="$lang" --source-root=. \
      --build-mode=none --codescanning-config="$config" --overwrite
  fi
  if [ "$mode" != create ]; then
    echo "==> [$lang] analyzing"
    pack="codeql/${lang%%-*}-queries"
    suite="$pack:codeql-suites/${lang%%-*}-code-scanning.qls"
    "$CODEQL_BIN" database analyze "$db" "$suite" --download \
      --format=sarif-latest --output=".codeql/results/$lang.sarif" \
      --sarif-category="/language:$lang" --threads=0
    echo "    results: .codeql/results/$lang.sarif"
  fi
done
