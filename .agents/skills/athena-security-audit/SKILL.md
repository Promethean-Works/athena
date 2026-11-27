---
name: athena-security-audit
description: Audits Athena for security vulnerabilities end to end - maps trust boundaries, runs scanners (gitleaks, trivy, semgrep, pnpm audit, uv), confirms findings with evidence, fixes them with regression tests, re-verifies and writes a sanitized report to .security-reports/. Use when the maintainer says "security audit", "/security-audit", or asks to harden the repo, scan for vulnerabilities or review the security of the whole codebase.
---

# Security audit and remediation

You are the security lead for this repo. Find and fix **confirmed** vulnerabilities and serious bugs, prove each fix with a test, and report honestly. Follow `AGENTS.md` throughout (worktree, evidence-not-claims, no shortcuts to green).

## Boundaries

- Work in a worktree on `fix/security-audit-<topic>` (`scripts/new-worktree.sh`), never the base checkout.
- Fix code-level issues. **Stop and ask** before: destructive or irreversible migrations, anything needing real credentials, architecture changes with compatibility impact, dependency upgrades with breaking changes. Keep working on other independent fixes meanwhile.
- Never touch the maintainer's Athena (port 8420) or non-`athena-demo-*`/`athena-test-*` containers. Use a spare port and a fresh data dir for anything you run.
- No attacks on real accounts, external services or production; no destructive proofs of concept. Tests run only against temp dirs / throwaway SQLite.
- Don't push, merge, rotate credentials or edit `CHANGELOG.md`/`version.txt`. Open a PR only if the maintainer asked (then `athena-ship`).
- Reports never contain secret values, personal data or exploit-ready detail. `.security-reports/` is git-ignored; create it with `mkdir -p`.

## Phase 1 - Understand

Read `docs/STATUS.md`, `docs/design/README.md` (auth, platform, assistant, cloud sections), `apps/server/AGENTS.md`, `docs/agents/gotchas/codeql.md`, `docs/agents/gotchas/windows.md`. Map: FastAPI routers and `require_user` coverage, auth/sessions/multi-user, host-password prompt and sudo paths, terminal/PTY, file explorer and shares, container/compose/catalog install, rclone, assistant tools and `ShellGuard`, webhooks/automation/MCP server, self-update, backups, HTTPS/tunnels, Next.js static export, installers (`scripts/install.*`), Docker/compose files, `.github/workflows`. Note trust boundaries, privileged operations, sensitive data, and existing tooling (CodeQL, gitleaks, secret-guard tests).

## Phase 2 - Baseline scans (before any edit)

Run what is installed; record each command and exit status; a missing tool is "skipped", not "passed" (offer `brew install trivy gitleaks semgrep`).

```
gitleaks dir . --redact --no-banner           # config: .gitleaks.toml
gitleaks git . --redact --no-banner           # history
trivy fs --scanners vuln,misconfig,secret --skip-dirs node_modules,.venv,.next .
semgrep scan --config auto --metrics off apps scripts catalog .github
pnpm audit --prod
cd apps/server && uv run pytest -q && uv run ruff check   # baseline tests
scripts/check.sh --strict                       # baseline, note pre-existing failures apart
```

A real secret in history: say so and recommend rotating it; deleting it from the tree is not enough. Triage scanner output for false positives.

## Phase 3 - Audit by hand

Cover the OWASP Top 10 and API Top 10 as they apply here, and trace full attack paths (enforcement may live in a dependency or middleware, not the route). Athena-specific hot spots:

- Routes without `require_user`, missing audit of privileged actions, IDOR between users (multi-user), session/cookie flags, login/brute-force limits, CSRF and CORS, WebSocket auth (terminal, logs).
- Command execution: `shell=True`, argument injection (leading `-`), unvalidated names passed to `docker`, `rclone`, package managers, `sudo`; path containment in file explorer, shares, uploads, backups/restore (zip/tar slip), catalog `compose.yaml` fields (privileged, host mounts, `network_mode: host`, docker socket).
- Secrets: API responses, logs, assistant context, `athena.json`, backups, installer scripts, `${...}` placeholders. <!-- docs-check: ignore -->
- SSRF (webhooks, fetchers, image/icon proxies, tunnels), unsafe redirects, template injection in installers, deserialization.
- Assistant: tool approval bypasses, prompt-injection paths to host actions, `ShellGuard` gaps.
- Supply chain: dependency CVEs, unpinned images/actions, workflow injection (`${{ github.event.* }}` in `run:`), excessive `permissions:`, secrets exposed to forks.
- DoS: unbounded uploads/bodies/jobs/streams, regex backtracking, missing timeouts.

For each candidate record: file:line, root cause, attacker prerequisites, impact (C/I/A), evidence (code, tool output or a safe test), severity, confidence, fix. Classify **confirmed / probable / unconfirmed**; never call a hypothesis an exploit.

## Phase 4 - Fix

Root causes only: least privilege, explicit authorization, validation at the boundary, safe argument lists, containment checks. No scanner suppression, no weakened checks, no unrelated refactors, no new dependency as a side effect. Route change → `pnpm gen:api`. Small coherent batches; each finding gets its own regression test before moving on.

## Phase 5 - Regression tests

One focused test per fix that **fails without it** (verify by temporarily reverting the fix, or reasoning from the failing assertion you saw). Cover anonymous / other-user / non-admin access, malformed, oversized and adversarial input, traversal, injection payloads, expired/revoked sessions, and workflow/Docker invariants where relevant. Follow the existing test layout (`athena-recipes`).

## Phase 6 - Verify independently

1. Targeted tests, then `scripts/check.sh --strict` for touched parts.
2. Re-run the Phase 2 scanners; compare before and after.
3. Review the full diff (lockfiles, generated files) with the `reviewer` subagent (`athena-review`) as an adversarial pass: ask it to find bypasses and incomplete fixes. Give it the diff, not your conclusions.
4. Every claimed result must match a command you ran and saw pass. Skipped or failing checks are reported as such.

## Phase 7 - Report

Write `.security-reports/security-audit.md`: executive summary and overall risk; scope and components inspected; findings ranked by severity and confidence (evidence, files, root cause, impact, remediation); files changed; tests added and results; exact commands and exit statuses; scanner findings before and after; dependency changes; items needing approval, remaining risks and unverified areas.

Statuses: Confirmed, Fixed and Verified, Fixed but Verification Incomplete, Unresolved, False Positive, Accepted Risk. "Fixed and Verified" requires a test run you saw pass.

Then do the `athena-handoff` (STATUS/HISTORY, gotchas for anything non-obvious). Finish with a short summary: fixes, test results, unresolved risks, next actions needed from the maintainer. A clean audit is not proof the system is secure; say so.

## Dynamic scan (optional, on request)

Against a release build on a spare port with a fresh data dir and a test account (see `athena-ui-verify`), never the maintainer's instance:

```
docker run --rm -v "$PWD/.security-reports:/zap/wrk/:rw" ghcr.io/zaproxy/zaproxy:stable \
  zap-baseline.py -t http://host.docker.internal:<port> -r zap-baseline.html
```

Passive baseline only. Remove the container afterwards (name it `athena-test-zap`).
