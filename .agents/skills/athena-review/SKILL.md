---
name: athena-review
description: Reviews an Athena diff for bugs and rule breaks - cross-platform, security, API and migration rules, UI conventions, tests, docs - without editing anything. Use before opening a PR, when asked to review a change or PR, or as the reviewer subagent.
---

# Review a change

Read-only: report, don't edit.

1. **Get the diff and the goal:** `git diff origin/main...HEAD` (or `gh pr diff <n>` for a PR), plus what the change is meant to do (the issue, spec part or PR body, `gh pr view <n>`). Write down its acceptance criteria; if none are stated, infer them and say so. Note which areas the diff touches. Review the whole final diff, including fixes made after an earlier review.
2. **Load the rules for those areas only:** `AGENTS.md` → Rules, the app rules (`apps/server/AGENTS.md`, `apps/web/AGENTS.md`), and the matching `docs/agents/gotchas/<area>.md`. The gotchas list real bugs from earlier sessions: check the diff against each relevant one.
3. **Check, in this order:**
   - **Goal:** each acceptance criterion is met; nothing unrelated slipped in (refactors, dependency bumps, formatting churn).
   - **Correctness:** logic errors, unhandled errors and edge cases (empty, missing tool, offline, concurrent use), races, resources not closed.
   - **Security:** new routes require a session (`require_user`) and audit privileged actions; no `shell=True`; user input validated before reaching a CLI or path (containment, leading `-`); no secrets returned by the API or logged; CodeQL-prone shapes from `docs/agents/gotchas/codeql.md`.
   - **Cross-platform:** host access through a capability, never `sys.platform` in a router; the Windows rules in `docs/agents/gotchas/windows.md` (encoding, paths, CRLF).
   - **APIs and dependencies:** every library call exists in the installed version (check the lockfile, the package's own types or source, and `docs/agents/dependencies.md`; don't trust memory). New or upgraded dependencies are justified, open source and in `docs/design/licenses.md`.
   - **Contracts:** model change → migration; route change → `pnpm gen:api` output committed; no hand-written request types; UI gated by capability; theme tokens only.
   - **Tests and verification:** new behaviour has a test that would fail without the change (a bug fix has a regression test); no test, lint rule or type check was skipped, loosened or silenced to pass; UI changes were browser-verified (`athena-ui-verify`); claimed results match what ran (run the focused tests yourself when you can); the PR body says what wasn't verified.
   - **Docs:** renames reflected in agent docs; design changes in `docs/design/` and `docs/design/decisions.md`.
4. **Report** findings ordered by severity (blocker, should fix, nit), each with `file:line`, why it's wrong, the evidence (the line, a command's output, the installed type or docs), and a concrete fix. Only report what you can back with evidence; mark a suspicion you couldn't confirm as such. Say what you didn't check and which commands you ran. If nothing is wrong, say so plainly; don't invent findings.
