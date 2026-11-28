# Spec: per-user file folders

**Status:** Approved (2026-11-27) · **Milestone:** multi-user follow-up · **Design:** `docs/design/files.md`, `docs/design/security.md`

## Goal

Every account, admins included, gets a private "My files" folder of their own and sees only the locations an admin chose to share with users. Today every user sees every location (Home included) read/write, which the pentest showed is far too much (F1). The data-folder guard that shipped with it closes the worst part; this finishes the job.

## Non-goals

Quotas, per-user trash, sharing between two users, per-user rclone remotes, changing what admins see.

## Platforms

Same on Linux, macOS and Windows: plain folders under the data dir, no capability needed.

## Design

- **Server:** migration adds `file_locations.owner_id` (nullable FK to `users`, cascade) and `file_locations.users_can_open` (bool). A location with `owner_id` is that user's alone (admins see it too). Others are visible to plain users only when `users_can_open` is true. The first time an account lists its locations (new users, and everyone after upgrading) Athena makes `<data-dir>/users/<id>/files` and its "My files" location; deleting the account deletes the row and the folder with everything in it (the UI warns first). Existing Home and App data get `users_can_open = false`, so upgrading closes access; the admin opens a location again in Settings.
- **Guard:** `files.paths.is_protected` lets a request open `users/<own id>/files` only (no other user's, none of the rest of `users/`). The `.env` and data-folder rules stay.
- **Routes:** `listFileLocations` filters per user; every route that takes a `location` id answers 404 for a location the caller can't open (share creation and transfers included). `POST/PATCH /api/files/locations` takes `users_can_open`. Share links keep `owner_id`.
- **Web:** Files shows "My files" first for users; Settings → Files gets a "Visible to users" switch per location; empty state when a user has no location.
- **Assistant / MCP:** none; its file tools stay admin-only.
- **Security:** the 404-not-403 rule avoids leaking ids; tests cover user A vs user B, user vs admin-only location, and ids in transfers and shares.
- **Dependencies:** none.

## Parts

1. Server: migration, location visibility, per-user folder, guard rule, tests.
2. Web: My files, the visibility switch, empty state; browser-verified.
One PR for the whole feature (the maintainer's rule), built part by part on one branch.

## Acceptance checks

- Tests: user A can't list, read, write, share or transfer from B's folder or an admin-only location; admin can; deleting a user removes their location; a new user has "My files" and nothing else.
- Browser (`athena-ui-verify`): admin and user in two contexts; the switch hides and shows Home for the user.
- Failure cases: id guessing, `..` and symlinks out of "My files", a user named so that the folder name collides (ids are used, not names).

## Open questions

- Should existing locations default to hidden from users on upgrade? — recommendation: yes, safer; the admin flips the switch.
- Delete the folder with the account? — **decided: yes, always** (the maintainer).
- Can a user create more folders-as-locations? — recommendation: no, they use subfolders.
