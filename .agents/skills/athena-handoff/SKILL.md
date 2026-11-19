---
name: athena-handoff
description: Ends an Athena session so the next agent (possibly a different tool) can continue - updates docs/STATUS.md, docs/HISTORY.md and the gotchas, then reports. Use before ending any session, when the maintainer says "handoff", "wrap up" or "stop here", or when context is running out.
---

# Handoff

The next agent has no memory of this session; the repo is all it gets.

1. **STATUS** (`docs/STATUS.md`, size-checked; keep each line short):
   - Merged work: remove it from STATUS and add one bullet to the end of `docs/HISTORY.md`: what, the PR number, what was verified and what wasn't.
   - Unfinished work under **In progress**: the branch and worktree, files touched, what works, what's broken, and the next concrete step.
   - New **Open questions** (with your recommendation) and **Blockers**. Ideas with no milestone go to `docs/design/milestones.md` → Backlog.
2. **Lessons:** anything non-obvious that cost you time goes to `docs/agents/gotchas/<area>.md` as one bullet with the _why_. A command worth reusing goes to `docs/agents/commands.md`. A design decision goes to its `docs/design/` section plus a row in `docs/design/decisions.md`.
3. Put the doc changes on your open PR's branch, or in a `docs:` PR with auto-merge (`athena-ship`). Not in the base checkout.
4. Report to the maintainer: what merged (links), what's still running, what was verified and what wasn't, "Fixed along the way" and "Not tested yet".

Don't write any of this only to private agent memory; other agents can't see it.
