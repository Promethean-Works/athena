---
name: athena-review
description: Reviews an Athena diff for bugs and rule breaks - cross-platform, security, API and migration rules, UI conventions, tests, docs - without editing anything. Use before opening a PR, when asked to review a change or PR, or as the reviewer subagent.
---

# Review a change

Read-only: report, don't edit.

1. **Get the diff:** `git diff origin/main...HEAD` (or `gh pr diff <n>` for a PR). Note which areas it touches.
2. **Load the rules for those areas only:** `AGENTS.md` → Rules, the app rules (`apps/server/AGENTS.md`, `apps/web/AGENTS.md`), and the matching `docs/agents/gotchas/<area>.md`. The gotchas list real bugs from earlier sessions: check the diff against each relevant one.
3. **Check, in this order:**
   - **Correctness:** logic errors, unhandled errors and edge cases (empty, missing tool, offline, concurrent use), races, resources not closed.
   - **Security:** new routes require a session (`require_user`) and audit privileged actions; no `shell=True`; user input validated before reaching a CLI or path (containment, leading `-`); no secrets returned by the API or logged; CodeQL-prone shapes from `docs/agents/gotchas/codeql.md`.
   - **Cross-platform:** host access through a capability, never `sys.platform` in a router; the Windows rules in `docs/agents/gotchas/windows.md` (encoding, paths, CRLF).
   - **Contracts:** model change → migration; route change → `pnpm gen:api` output committed; no hand-written request types; UI gated by capability; theme tokens only.
   - **Tests and verification:** new behaviour has a test; UI changes were browser-verified (`athena-ui-verify`); the PR body says what wasn't verified.
   - **Docs:** renames reflected in agent docs; design changes in `docs/design/` and `docs/design/decisions.md`; new dependencies licensed in `docs/design/licenses.md`.
4. **Report** findings ordered by severity (blocker, should fix, nit), each with `file:line`, why it's wrong, and a concrete fix. Say what you didn't check. If nothing is wrong, say so plainly; don't invent findings.
