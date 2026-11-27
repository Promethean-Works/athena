# Spec: multi-user

**Status:** Built, PR open (approved 2026-11-27, all recommendations accepted; users don't see menus they can't use) · **Milestone:** Release 0.1.0 candidate (not yet in `docs/plans/release-0.1.0.md`) · **Design:** `docs/design/security.md`, decision "Auth (M1)"

## Goal

The admin can create more accounts for family or team members, each with one of two roles: **admin** (everything) or **user** (day-to-day use: apps, files, store, dashboard, own assistant chats; no host or system changes). Now Athena has one admin; the `users.is_admin` column and many admin-only checks already exist, but nobody can add a second account.

## Non-goals

- More than two roles, per-app or per-folder permissions, groups.
- Per-user file spaces or quotas (users see the same file locations; see open questions).
- SSO/OIDC, 2FA, email invites, self-registration.
- Per-user MCP tokens (`ATHENA_MCP_TOKEN` keeps acting as the oldest admin).

## Platforms

No host access: users are Athena accounts, not OS accounts. Same on Linux, macOS and Windows; no new capability.

## Design

- **Server:**
  - No new column: `users.is_admin` is the role (`admin` / `user`). No migration unless we add `disabled` (see questions).
  - New `apps/server/src/athena/api/users.py`, admin-only, `/api/users`: `listUsers`, `createUser` (username, password, role), `updateUser` (role, reset password), `deleteUser`. Reuse `USERNAME_RE`, `MIN_PW_LENGTH` and argon2 from `auth/service.py`.
  - Guards: the last admin can't be demoted or deleted; you can't delete yourself; deleting or demoting a user ends their sessions (`sessions` cascades on delete). A password reset signs that user out everywhere.
  - A shared `require_admin` dependency replaces the repeated `if not user.user.is_admin` blocks (behavior-preserving refactor, own part).
  - **Route audit:** every router now behind plain `require_user` is checked and classed admin-only or user-ok (table in the PR). Default is admin-only for anything that changes the host: runtime, packages, terminal, tunnel, HTTPS, backup, settings, cloud, mounts, shares/SMB/NFS, WebDAV, automation, MCP, audit, feedback logs. Users may: view the dashboard and apps, start/stop/open apps, browse the store, use files and share links, use their own assistant chats. Installing or removing apps is open question 2.
  - Login throttle, CSRF, cookies and password change are unchanged. Audit rows already carry the username; new actions `user.create`, `user.update`, `user.delete`, `user.password_reset`.
- **Web:** Settings → **Users** tab (admin only): table with role badge, create dialog, role select, reset password, delete with confirm. Sidebar and pages hide admin-only entries for users (from `user.is_admin`, same pattern as the capability gating); direct URLs show the same "admins only" empty state as the API's 403. No new i18n debt: strings go through the i18n catalog.
- **Assistant / MCP:** assistant stays admin-only for now (it can act on the host); a user-level assistant limited to user-ok tools is a follow-up. MCP tools keep acting as the oldest admin for the token; with a session cookie they act as the signed-in user, so MCP tools that change the host get the same role check.
- **Security:** every new route admin-only and CSRF-protected; passwords never logged; generic error when a username exists is fine (admin-only endpoint). A 403 test for every admin-only router, so a new unguarded route fails CI.
- **Dependencies:** none.

## Parts

1. **Role guard** — `require_admin`, route audit, fix any host-changing route a plain user can reach today, 403 test per router. No UI.
2. **Users API** — `/api/users` plus guards (last admin, self), audit entries, `pnpm gen:api`.
3. **Users UI** — Settings → Users, role-aware sidebar and pages, browser-verified with an admin and a user (phone width, dark mode).
4. **Docs** — design section and decisions row, mark Done.

Per the maintainer's preference, one PR for the whole feature (parts as commits), not one per part.

## Acceptance checks

- Tests: user gets 403 on each admin-only router and 200 on the allowed ones; last-admin and self-delete refused; deleted/demoted user's cookie stops working; password reset signs out the user's sessions.
- Browser (`athena-ui-verify`): admin creates a user, signs in as them in a second context, sees the reduced sidebar, gets the empty state on an admin URL, can't call admin API from the console.
- Failure cases: duplicate username, short password, invalid role, deleting the only admin.

## Open questions

1. **Should a user's chats, dashboard layout and appearance be private?** Already per user (`users.dashboard`, `users.appearance`); assistant chats and memory are per admin namespace. Recommendation: yes, keep per user, nothing to build.
2. **Can a user install or remove store apps?** Recommendation: no. Installing runs containers (often with host mounts or the Docker socket), which is a host change. Users start/stop/open apps and browse the store; admins install. Revisit later with an admin setting.
3. **File locations: do users see all locations?** Recommendation: yes, the same list, read/write; per-user home folders are a follow-up.
4. **Add a `disabled` flag (suspend without deleting)?** Recommendation: not now; delete plus recreate is enough for two roles and avoids a migration.
5. **Does a user get to change their own password?** Recommendation: yes, the existing `/api/auth/password` already works for any account.
