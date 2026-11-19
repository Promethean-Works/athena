# Spec: <feature>

**Status:** Draft | Approved (date) | Done (#PRs) · **Milestone:** <M#, part> · **Design:** `docs/design/<section>.md`

## Goal

What the admin can do afterwards that they can't now, in two or three sentences. Who it's for.

## Non-goals

What this deliberately doesn't do (so nobody builds it by accident).

## Platforms

How it works on Linux, macOS and Windows: the capability id(s), what's detected, and what the UI shows when the host can't do it.

## Design

- **Server:** modules, routes (with `operation_id`), models and migrations, jobs, audit entries.
- **Web:** pages and components (shadcn first), capability gating, empty and error states.
- **Assistant / MCP:** tools to add, and which need approval.
- **Security:** who can call it, input validation, secrets, what's logged.
- **Dependencies:** new ones and their licenses (open source only).

## Parts

1. <part> — what ships, what's verified. One PR each.

## Acceptance checks

How we'll know it works: the tests to write, the browser checks (`athena-ui-verify`), real-host checks (`athena-host-test`), and the failure cases.

## Open questions

- <question> — recommendation: <answer, and why>.
