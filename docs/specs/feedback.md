# Spec: in-app feedback and reporting

**Status:** Approved (2026-11-20) · **Milestone:** none (backlog) · **Design:** `docs/design/frontend.md`, `docs/design/apps.md`

## Goal

From inside Athena, an admin can report a bug, suggest a change to how something works, request a feature, or report a store app that doesn't work. Each choice opens the right issue form, already filled in with the details a maintainer needs (Athena version, OS, CPU, container runtime, and for apps the catalog, app and images).

## Non-goals

- Athena never sends anything itself: no token, no hosted relay, no telemetry. The user's browser opens the issue page and the user submits it (or doesn't).
- No crash reporting or automatic log upload.
- No assistant or MCP tool.

## Platforms

Same on Linux, macOS and Windows; no capability. The container runtime line comes from the `containers` capability (provider and detail), or "none" when it isn't ready.

## Design

- **GitHub (`.github/ISSUE_TEMPLATE/`):** keep `bug_report.yml` and `feature_request.yml`, add `change_request.yml` (change how something already works) and `app_report.yml` (a store app that doesn't work). Labels `change`, `catalog` and `triage`. Every field Athena fills in has an `id`, so the form can be filled from the URL query (`?template=<file>&<id>=<value>`).
- **Server:**
  - `athena/feedback.py`: builds issue URLs. Athena's own repo comes from `Settings.feedback_repo` (`ATHENA_FEEDBACK_REPO`, default `https://github.com/tiagozaccaro/athena`) so forks can point elsewhere.
  - `GET /api/feedback` (`getFeedbackInfo`): the diagnostics shown before anything opens (version, OS and version, arch, container runtime, repo URL). No hostname, IPs, paths or secrets.
  - `POST /api/feedback/issue-url` (`buildIssueUrl`): takes the kind (`bug`, `change`, `feature`, `app`), an optional title, and for apps the catalog, app id and optional logs. Returns the URL and where it goes.
  - Where app reports go: built-in catalog → Athena's `app_report.yml`. A remote catalog whose URL is a GitHub, Codeberg or GitLab repo → that repo's new-issue page with a title and a Markdown body. Any other catalog URL (an archive link) → Athena's `app_report.yml` with the catalog URL in the form.
  - Logs are optional, sent only when the user includes them, and cut to the last 4,000 characters so the URL stays under the forges' length limits.
- **Web:**
  - "Send feedback" in the sidebar's secondary nav opens a dialog: Bug, Change, Feature. It shows the diagnostics that will be included, then opens the issue page in a new tab.
  - The store app page gets "Report a problem". The dialog says where the report goes. For an installed app it can load the last 50 log lines of its containers into an editable box (unticked by default) so secrets can be removed first.
- **Security:** both routes need a session. The catalog and app id are looked up in the registry (no free-form URLs from the client). Issues are public, so nothing is included without being shown first.
- **Dependencies:** none.

## Parts

1. Issue templates, labels and this spec (`docs:`).
2. Server routes, setting, tests, `pnpm gen:api`; web dialog and store button, verified with `athena-ui-verify` (one `feat:` PR: the web half needs the generated client).

## Acceptance checks

- pytest: URL per kind, diagnostics present, built-in vs GitHub vs Codeberg vs GitLab vs archive catalog targets, unknown app → 404, logs truncated, `ATHENA_FEEDBACK_REPO` override.
- Browser: the dialog opens from the sidebar, each choice opens a filled GitHub form; the store button on a built-in app and on an installed app (logs preview); phone width and dark mode.

## Open questions

All answered on 2026-11-20: reports for third-party catalogs go to that catalog's repo; submission happens on the forge in a new tab; logs only on request with a preview; the repo URL is configurable.
