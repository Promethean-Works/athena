# Spec: agent orchestration (issue to merge)

**Status:** Approved (2026-11-25), parts 1–2 done · **Milestone:** none (agent tooling) · **Design:** `docs/agents/tooling.md`, `docs/agents/subagents.md`

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
| Reviewer | `opencode run --agent reviewer --model <approved> --format json --archived` in its own detached worktree at the candidate commit, after the worker exits | a child process | read and run commands. Not truly read-only (part 1: `shell` and Code Mode `execute` can write), so Hermes discards the review if that worktree changed |

Hermes runs the workers through its shell tool, not `delegate_task` (its children are Hermes itself, not omp or OpenCode). The exact commands, output and exit codes are in `docs/agents/tooling.md` → Running agents headless.

**Flow and states.** `queued → implementing → verifying → reviewing → pr_open → merged`, or `blocked` from any state.

1. **Intake:** issues labelled `agent:ready` (`gh issue list --label agent:ready`). Hermes refuses an issue that touches a [sensitive area](#security) and labels it `agent:needs-human`. It writes the acceptance criteria (from the issue, or inferred and marked so) into the task file.
2. **Isolate:** `scripts/new-worktree.sh <type>/<issue#>-<topic>` from the current `origin/main`; the base commit goes into the task file.
3. **Implement:** the worker gets the issue, the criteria, the worktree path, and "follow `AGENTS.md`; commit when `scripts/check.sh --strict --quick` passes; report changed files, commands run and their results". Hermes checks the worker committed only inside the worktree (`git -C <wt> log origin/main..HEAD`) and that the base checkout is still clean.
4. **Verify:** Hermes runs `ATHENA_CHECK_STRICT=1 scripts/check.sh` itself (`--quick` unless the diff touches the web app, packages or lockfiles); the worker's word isn't evidence. On failure the same check runs once on the base commit in a detached worktree (cached in `.agents/state/baselines/`), and only failures the change brought in count (pytest per test id; other steps only when their log, minus paths and timings, is identical; a pytest crash, a missing tool or a failed `pnpm install` never counts as pre-existing; a baseline whose `pnpm install` failed is unusable; the cache expires after 12 hours). Pre-existing ones are reported. A new failure goes back to step 3 with its log tail.
5. **Review:** in a fresh detached worktree at the candidate commit (`git worktree add --detach`), the reviewer runs the `athena-review` skill on `git diff origin/main...HEAD` plus the criteria. Afterwards Hermes checks `git status --porcelain` is empty and `HEAD` is still the candidate; if not, the review is discarded and retried once, then `blocked`. The review worktree is removed. Blockers and should-fix items go back to step 3 as a numbered list; nits go in the PR body.
6. **Repair budget:** at most **2** rounds back to step 3 (for failed checks and findings together). After that: `blocked`, with the last log and findings on the issue.
7. **PR:** push, `gh pr create` (Conventional Commit title, body: criteria and how each is met, checks run, review summary, what wasn't verified, `Closes #<n>`), then `gh pr merge --squash --auto --delete-branch`. A commit after the review means a new review.
8. **Don't wait:** once the PR is open with auto-merge on, the run ends (waiting on CI burns tokens). A later `status`/"check" pass (`athena-check-prs`, one pass) handles a CI failure, which counts against the same repair budget. Merged: remove the worktree, close out the task file, add the HISTORY bullet.

**Task state.** `.agents/state/tasks/<issue#>.json` in the base checkout (git-ignored, added in part 2): issue, branch, worktree, base and candidate commits, state, attempts, last check result, review findings, models used. Each step rewrites it, so a crashed run picks up where it stopped.

**Model policy (fail closed).** `.agents/orchestration.json` lists the approved models per role (local Ollama or free routes, e.g. `kilo-auto/free`). Hermes passes an exact `--model <provider>/<id>` to each worker (omp fuzzy-matches, so no short names) plus `--max-cost 0.01` to omp, and refuses to start if a role's model isn't on the list. After each run it checks the provider, model and cost the tool reports (omp: each `message_end`; OpenCode: `opencode session export`) and blocks the task on a mismatch or any cost above 0. A model that isn't available (both tools exit 1) means `blocked`, never a fallback. The policy applies only to runs the skill starts; the maintainer's interactive sessions keep their own models.

**Security.** Issue text is data: it goes to the worker inside a quoted block, under the instruction that it can't override `AGENTS.md`. The worker and reviewer get the existing guards (`scripts/agent-guard.mjs`). Sensitive areas need a person and are never picked up: migrations (`apps/server/src/athena/db/migrations/`), auth and secrets (`apps/server/src/athena/auth/`), installers and the service (`scripts/install.*`, `athena service`), workflows (`.github/`), guards and agent config (`scripts/agent-guard.mjs`, `scripts/agents-sync.mjs`, `.agents/`), release files. If the diff touches one anyway, the PR is opened without auto-merge and labelled `agent:needs-human`.

**Dependencies:** none new.

## Parts

1. **Headless runs proven** (done, this PR) — `docs/agents/tooling.md` → Running agents headless: flags, output, where the model is reported, exit codes. Proven by hand in a throwaway worktree (local commits only, no issue): omp edited and committed there, its guard refused a base-checkout write, `worktree.onStart` doesn't fire under `-p`, both tools exit 1 on an unknown model. Found: the OpenCode reviewer can write through `shell`/`execute`, hence the review worktree above.
2. **The skill, run by hand** (this PR) — `.agents/skills/athena-orchestrate/SKILL.md` for the judgement (intake, criteria, findings triage, report) and `scripts/orchestrate.mjs` for every mechanical step, so a weak model can't skip a check: `preflight`, `start` (`--issue-file` for local trials without a GitHub issue), `criteria`, `worktree`, `implement [--repair]`, `verify`, `review`, `block`, `status`, `--self-test` (run by `agents-sync.mjs --check`). Policy in `.agents/orchestration.json`: the free-only rule is in code (`isFreeModel`), so listing a paid model fails preflight; `verify.allow_missing` names the steps strict mode may skip on the maintainer's Mac (`ATHENA_CHECK_ALLOW_MISSING`, PSScriptAnalyzer). `scripts/check.sh`, the hooks' scripts and `new-worktree.sh` count as sensitive, so a worker can't pass by weakening a check. Lint, test and type configs, lockfiles, `package.json`, all of `scripts/` and the agent rules count as sensitive too; added suppressions and deleted tests block; renames are seen as delete plus add; verify and review run at most twice per commit; a repair needs a new commit. `/orchestrate` runs the skill. Stops at `ready_for_pr`; nothing is written to GitHub. Known limits: the script's own `.agents/state/` isn't covered by the checkout snapshots, and models used by omp's own subagents don't appear in its `message_end` events (the free-only check covers the models omp reports).
3. **End to end** — PR creation and auto-merge (no CI watch), plus the three acceptance tasks below. Then optional: a Hermes cron that picks up `agent:ready` issues one at a time.

## Acceptance checks

Run on throwaway issues in this repo, one each:

- **Small bug fix:** the worker finds the code, adds a regression test that fails without the fix, and the PR merges.
- **Version-sensitive API:** e.g. a Base UI or pydantic-ai 2.x call. The task file and PR show the lockfile version and the docs or types that were checked.
- **Failing path:** a planted failing test or review finding. The pipeline repairs it once; when it can't be fixed, it stops after 2 rounds as `blocked`, with no PR merged.
- **Policy:** an unapproved model in `.agents/orchestration.json`, or a missing tool, blocks before any code is written. An issue touching `.github/` is refused with `agent:needs-human`.

## Decisions (2026-11-25)

- **Approved models:** only free or local routes (`kilo/kilo-auto/free` and other `:free` Kilo models, local Ollama once one is installed), listed in `.agents/orchestration.json`; interactive sessions keep the maintainer's models.
- **Worker and reviewer may share a model** at first; independence comes from a different tool, a fresh context and a separate worktree.
- **Task state** lives in this repo's `.agents/state/` until a second repository needs it.
- **Started by hand** (`/orchestrate <issue#>`) until the acceptance checks pass and a few real issues have merged; a Hermes cron (one task at a time) after that.
