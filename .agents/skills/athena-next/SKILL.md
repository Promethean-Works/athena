---
name: athena-next
description: Picks the next piece of Athena work - reads STATUS, checks open PRs, and proposes one concrete next step with a recommendation, then waits for a yes. Use when the maintainer says "next", "continue", "what's next" or names a milestone or part to start.
---

# What's next

1. Read `docs/STATUS.md` (current milestone, In progress, Next, Open questions, Blockers).
2. Check what's in flight so you don't redo it: `gh pr list --author @me --state open` and `git worktree list`. A PR of yours that's open with failing checks comes first (use `athena-check-prs`).
3. Pick the step:
   - Unfinished In progress items before new work.
   - Then the first item under **Next**; if STATUS has none, the next milestone in `docs/design/milestones.md`.
   - A big feature (a new milestone part, a new area, or more than one PR of work) starts with a spec: copy `docs/specs/_template.md` to `docs/specs/<feature>.md`, fill it in, and get it approved before code (see `docs/specs/README.md`).
4. Propose it in a few lines: what you'll do, which files and areas it touches, how you'll verify it, and any open question with your recommendation. If the maintainer said "discuss questions first", list the questions only.
5. **Wait for a yes** before starting a new milestone or part. A follow-up inside work already approved (a failing check, a review fix) needs no new yes.

When you start, create the worktree first (AGENTS.md → Git workflow) and read the "Read when" rows that match the task.
