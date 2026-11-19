# Specs

A spec is a short plan for a big feature, written by the agent and approved by the maintainer **before any code**. It catches a wrong direction while it's still cheap to fix and gives every later PR (and every later agent) the same target.

**When:** a new milestone part, a new area or capability, a change across server, web and docs, or anything that will take more than one PR. Small fixes and follow-ups don't need one.

**How:**

1. Copy `docs/specs/_template.md` to `docs/specs/<feature>.md` in your worktree and fill it in. Read the matching `docs/design/` section and the closest existing feature first; don't guess APIs.
2. Open it as a `docs:` PR (or show it in chat) and wait for the maintainer's yes. List open questions with a recommendation each.
3. Build it in the parts the spec lists, one PR per part. Each PR says which spec part it implements.
4. When it's done, move what stays true into the `docs/design/` section (plus a row in `docs/design/decisions.md`), mark the spec **Done** with the PR numbers, and keep it as the record.
