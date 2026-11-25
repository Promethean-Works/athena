# Spec: agent orchestration (issue to merge)

**Status:** Draft · **Milestone:** none (agent tooling) · **Design:** `docs/agents/tooling.md`, `docs/agents/subagents.md`

## Goal

The maintainer labels a small GitHub issue, and Hermes takes it from there to a merged PR without a person in the loop, using only free or local models. Hermes coordinates; oh-my-pi writes the code in its own worktree; OpenCode reviews it read-only. A task the pipeline can't finish safely ends **blocked** with a report, never as a fake green. This is for the maintainer's own machine (macOS, M1, 16 GB), one task at a time.

## Non-goals

- No new code in Athena itself (`apps/`): this is agent tooling under `.agents/` and `scripts/`.
- No shared control plane for other repositories. The state lives in this repo's git-ignored folder; other repos can copy the skill later.
- No bypassing branch protection. Merging stays GitHub's auto-merge after `ci-ok` and CodeQL, as today.
- No parallel workers at first (local inference on 16 GB can't run two models well).
- No database: one JSON file per task is enough for one worker.

## Platforms

Runs where the maintainer runs agents (macOS; Linux should work, untested). Needs `hermes`, `omp`, `opencode`, `gh` and `git` on `PATH`. `scripts/agents-setup.mjs --check` reports a missing one; the skill refuses to start without them.

## Design

**Roles.**

| Role | Tool | Runs as | Can |
|---|---|---|---|
| Coordinator | Hermes (`athena-orchestrate` skill) | the interactive or cron session | read issues, create worktrees, run the workers and checks, open PRs, write task state. Never edits code |
| Worker | `omp -p --model <approved>` in the task's worktree | a child process | edit and commit in that worktree only |
| Reviewer | `opencode run --agent reviewer --model <approved> --format json` in the same worktree after the worker exits | a child process | read and run commands; `edit` denied (already in `opencode.json`) |

Hermes runs the workers through its shell tool, not `delegate_task` (its children are Hermes itself, not omp or OpenCode).

**Flow and states.** `queued → implementing → verifying → reviewing → pr_open → merged`, or `blocked` from any state.

1. **Intake:** issues labelled `agent:ready` (`gh issue list --label agent:ready`). Hermes refuses an issue that touches a [sensitive area](#security) and labels it `agent:needs-human`. It writes the acceptance criteria (from the issue, or inferred and marked so) into the task file.
2. **Isolate:** `scripts/new-worktree.sh <type>/<issue#>-<topic>` from the current `origin/main`; the base commit goes into the task file.
3. **Implement:** the worker gets the issue, the criteria, the worktree path, and "follow `AGENTS.md`; commit when `scripts/check.sh --strict --quick` passes; report changed files, commands run and their results". Hermes checks the worker committed only inside the worktree (`git -C <wt> log origin/main..HEAD`) and that the base checkout is still clean.
4. **Verify:** Hermes runs `ATHENA_CHECK_STRICT=1 scripts/check.sh` itself; the worker's word isn't evidence. A failure goes back to step 3 with its log tail.
5. **Review:** the reviewer runs the `athena-review` skill on `git diff origin/main...HEAD` plus the criteria. Blockers and should-fix items go back to step 3 as a numbered list; nits go in the PR body.
6. **Repair budget:** at most **2** rounds back to step 3 (for failed checks and findings together). After that: `blocked`, with the last log and findings on the issue.
7. **PR:** push, `gh pr create` (Conventional Commit title, body: criteria and how each is met, checks run, review summary, what wasn't verified, `Closes #<n>`), then `gh pr merge --squash --auto --delete-branch`. A commit after the review means a new review.
8. **Watch:** the `athena-check-prs` procedure. A CI failure counts against the same repair budget. Merged: remove the worktree, close out the task file, add the HISTORY bullet.

**Task state.** `.agents/state/tasks/<issue#>.json` (git-ignored): issue, branch, worktree, base and candidate commits, state, attempts, last check result, review findings, models used. Each step rewrites it, so a crashed run picks up where it stopped.

**Model policy (fail closed).** `.agents/orchestration.json` lists the approved models per role (local Ollama or free routes, e.g. `kilo-auto/free`). Hermes passes `--model` explicitly to each worker and refuses to start if a role's model isn't on the list. After each run it checks the model the tool reports it used (omp and OpenCode JSON output, to be confirmed in part 1) and blocks the task on a mismatch. A model that isn't available means `blocked`, never a fallback.

**Security.** Issue text is data: it goes to the worker inside a quoted block, under the instruction that it can't override `AGENTS.md`. The worker and reviewer get the existing guards (`scripts/agent-guard.mjs`). Sensitive areas need a person and are never picked up: migrations (`apps/server/src/athena/db/migrations/`), auth and secrets (`apps/server/src/athena/auth/`), installers and the service (`scripts/install.*`, `athena service`), workflows (`.github/`), guards and agent config (`scripts/agent-guard.mjs`, `scripts/agents-sync.mjs`, `.agents/`), release files. If the diff touches one anyway, the PR is opened without auto-merge and labelled `agent:needs-human`.

**Dependencies:** none new.

## Parts

1. **Headless runs proven** — a short doc section on running omp and OpenCode non-interactively in a given worktree: the exact flags, how each reports the model used, exit codes, and whether omp's `worktree.onStart: create` makes a second worktree under `-p` (and how to turn it off for workers). Proven by hand on a throwaway issue. No automation yet.
2. **The skill, run by hand** — `.agents/skills/athena-orchestrate/SKILL.md`, `.agents/orchestration.json`, the task file, the repair budget and the blocked path. The maintainer starts it with `/orchestrate <issue#>` (added to `COMMANDS`); it stops before the PR is created, for a human look.
3. **End to end** — PR creation, auto-merge and the CI watch, plus the three acceptance tasks below. Then optional: a Hermes cron that picks up `agent:ready` issues one at a time.

## Acceptance checks

Run on throwaway issues in this repo, one each:

- **Small bug fix:** the worker finds the code, adds a regression test that fails without the fix, and the PR merges.
- **Version-sensitive API:** e.g. a Base UI or pydantic-ai 2.x call. The task file and PR show the lockfile version and the docs or types that were checked.
- **Failing path:** a planted failing test or review finding. The pipeline repairs it once; when it can't be fixed, it stops after 2 rounds as `blocked`, with no PR merged.
- **Policy:** an unapproved model in `.agents/orchestration.json`, or a missing tool, blocks before any code is written. An issue touching `.github/` is refused with `agent:needs-human`.

## Open questions

- **Which models are approved?** `.agents/user/opencode.models.json` sets Kilo's paid Claude models for OpenCode today. Recommendation: workers use only local Ollama models and `kilo-auto/free`, listed in `.agents/orchestration.json`, and the maintainer's own interactive sessions keep their current models (the policy applies only to runs started by the skill).
- **Can the worker also be the reviewer's model?** Recommendation: allow it at first (few free models are good at code), but use a different tool and a fresh context, so the review isn't anchored on the worker's reasoning.
- **Where does task state live?** Recommendation: `.agents/state/` in the base checkout (git-ignored), not `~/Developer/agent-control`, until a second repository needs it.
- **Cron or by hand?** Recommendation: by hand (`/orchestrate <issue#>`) until the acceptance checks pass and a few real issues have merged cleanly; then a Hermes cron at most one task at a time.
