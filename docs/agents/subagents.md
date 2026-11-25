# Subagents

_When and how to hand work to a subagent, in every agent this repo supports. Read it when a task needs a wide search, research on several fronts, a review or a browser check._

A subagent starts with only the brief you give it and returns only its final report. That is the point (its file dumps never reach your context) and the cost (it repeats reading you may already have done, and it can be confidently wrong). Delegate when that trade pays.

## When to delegate

- **Wide searches:** "where is X handled", "every caller of Y", "which store apps use Z" across many files. You keep the answer, not the dumps.
- **Independent research in parallel:** several questions that don't depend on each other (current docs of two libraries, how three agents configure the same thing). Start them all in one turn, keep working, and combine the reports.
- **Fixed roles:** the `reviewer` before every PR (`athena-review`), and `ui-verify` for browser checks (`athena-ui-verify`). They keep long, repetitive steps out of the main session (and run on a cheaper model in Claude Code and oh-my-pi; in OpenCode set one, see `docs/agents/tooling.md`).
- **A second opinion that isn't yours:** give the reviewer the diff, not your conclusion. A subagent handed a hypothesis tends to return it confirmed.

Do it yourself when it's a handful of tool calls, a file you already know the path of, or something you need to see line by line to edit. Never delegate a step and also do it yourself.

## Writing the brief

The brief is the only context the subagent has. Include:

1. **The goal and why**, in one or two sentences.
2. **What you already know or ruled out**, so it doesn't redo it.
3. **Where to look:** files, folders, docs, commands (it doesn't know the repo map in `AGENTS.md` unless you say so; point at the skill that holds the procedure).
4. **The scope and limits:** read-only or not, which paths, what not to touch (ports 8421+, only `athena-test-*` containers, no pushes).
5. **What to return:** the shape and length of the report ("under 500 words, file:line for each finding, mark what you couldn't verify").

## Rules

- **One editor per file.** Subagents that edit run in their own worktree (Claude Code `isolation: "worktree"`, omp `task.isolation`), or don't edit at all. Two agents editing the same checkout overwrite each other.
- **Verify what comes back.** Treat a report as a lead: check the one or two facts your next step depends on (read the file, run the command) before acting on it or reporting it as done.
- **Reports are for you, not the maintainer.** Relay what matters in your own words; the maintainer doesn't see the subagent's report.
- **Wait, don't poll.** Background subagents notify you when they finish; work on something else meanwhile. Don't predict their results.
- **Reuse a finished subagent for follow-ups** (it keeps its context) instead of starting a new one on the same topic.

## Per agent

| Agent | Tool | Built in | Ours (`scripts/agents-sync.mjs`) | Parallel / background |
|---|---|---|---|---|
| Claude Code | `Agent` | `Explore` (read-only search), `Plan`, `general-purpose` | `reviewer`, `ui-verify` (`.claude/agents/`, skill preloaded) | Several `Agent` calls in one message; `run_in_background` |
| OpenCode | the subagent tool (or `@<name>` in a prompt) | `explore`, `general` | `reviewer`, `ui-verify` (`opencode.json`; only `ui-verify` has Playwright) | Several calls in one turn |
| oh-my-pi | `task` | `scout`, `reviewer` (bundled: tell it to follow `.agents/skills/athena-review/SKILL.md`), `security-reviewer`, `task` | `ui-verify` (`.omp/agents/`, `@smol` model, uses omp's own browser) | Several tasks per call; `task.isolation` gives each its own worktree |
| Hermes Agent | `delegate_task` | Generic children (no named agents) | None: put "follow `.agents/skills/<skill>/SKILL.md`" (`athena-review`, `athena-ui-verify`) in `context` | `tasks=[...]` runs a batch at once; `background: true` |

Our `reviewer` has no edit tool in Claude Code (`tools:` without edit) or OpenCode (`edit` denied), but both can still write through the shell (and OpenCode through Code Mode's `execute`), so say "read-only" in every brief, and for unattended reviews check the worktree afterwards (`docs/agents/tooling.md` → Running agents headless). Subagent models are cheaper on purpose where set (Claude Code `sonnet`, omp `smol`); see `docs/agents/tooling.md` → Token budget.
