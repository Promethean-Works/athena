# Spec: customizable dashboard

**Status:** Approved (2026-11-20) · **Milestone:** Backlog (screen review) · **Design:** `docs/design/README.md` → web UI

## Goal

Each admin arranges their own dashboard: turn on edit mode, drag cards into a new order, make a card half or full width, remove cards they don't use and add ones they do. The layout follows the account to other browsers, like Appearance. New cards show what a home server owner checks most: containers, automation, recent activity and remote access. The app card gets clearer status and actions.

## Non-goals

- Free resizing or a pixel grid (react-grid-layout style). Cards are half or full width only.
- Several dashboards or shared layouts. One layout per user.
- Cards with their own settings beyond size (no "pick which disk" options yet).
- Third-party or plugin cards.

## Platforms

Nothing new touches the host. Each card names the capability it needs; the "Add card" picker hides cards whose capability isn't reported, and a placed card whose capability is missing renders `Empty` with the capability's `detail` (same rule as pages). Containers needs `containers`, Automation needs `automation`, Remote access needs any `tunnel.*`, Capabilities and the rest need nothing.

## Design

- **Server:**
  - `users.dashboard` (nullable JSON text), migration `0016_user_dashboard`, like `users.appearance` (`0006`).
  - `GET /api/settings/dashboard` (`getDashboardLayout`) and `PUT /api/settings/dashboard` (`setDashboardLayout`) in `api/settings.py`. Model `DashboardLayout { cards: list[DashboardCard] }`, `DashboardCard { id: str, size: "half" | "full" }`.
    - `id` matches `^[a-z][a-z0-9-]{0,39}$`; there are at most 40 cards and no duplicate ids. The server doesn't know the card list, so a new card needs no server change, and the UI ignores ids it doesn't know.
    - `GET` returns `{ cards: null }` when nothing is saved, so the UI uses its default layout. Stored data that no longer validates is logged and treated as unsaved, like Appearance.
  - `GET /api/audit?limit=` (`listAuditEntries`, admins only, limit 1–50, default 10, newest first) for Recent activity. It is read-only and never returns `detail` fields that could hold secrets. (Check what callers put in `detail` first; if any hold secrets, return only `at`, `username`, `action` and `target`.)
- **Web:**
  - `components/dashboard/cards.tsx`: a registry of `{ id, title, description, icon, capability?, defaultSize, render }`, and the default layout.
  - `dashboard-grid.tsx`: a two-column grid (`xl:grid-cols-2`, one column below). Full cards span both columns.
    - **Edit** (header button) shows a drag handle, a size toggle and a remove button on each card, plus **Add card** (a dialog listing the hidden cards) and **Reset**, then **Done**.
    - Changes save on Done (one PUT), with a toast on error and the layout rolled back.
  - Drag and drop with `@dnd-kit/core` + `@dnd-kit/sortable` (MIT): pointer, touch and keyboard sensors, and screen-reader announcements. Each card's edit menu also has Move up / Move down for anyone who can't drag.
  - Existing pieces become cards: system stats (full), apps (full), storage, temperatures, server, capabilities (now a compact grid of status chips; details in a tooltip).
  - New cards:
    - **Containers:** running, stopped and unhealthy counts, and the top 5 by status, from `listContainers`. Links to `/containers/`.
    - **Automation:** enabled triggers with their next run (cron), and the last 5 job runs with status.
    - **Recent activity:** the last 10 audit entries. Admins only; hidden from the picker for other users.
    - **Remote access:** tunnel status badge, the public address with a copy button, and a link to Settings → System.
  - **App card:**
    - Status dot and label (running, stopped, starting, error) and a prominent **Open** button when the app has a web port.
    - "Update available" badge when the API reports one (only if it already does; no new server work for this).
    - Start/stop/restart in the menu; tooltips on icon buttons.
    - The empty state is compact (one line plus a "Browse the store" button), not a full-height panel.
- **Assistant / MCP:** none.
- **Security:** the layout is per user (any signed-in user can save their own). The audit endpoint is admin-only, read-only and capped at 50 rows. Layout input is validated as above.
- **Dependencies:** `@dnd-kit/core`, `@dnd-kit/sortable`, `@dnd-kit/utilities` (MIT), recorded in `docs/design/licenses.md`.

## Parts

1. **Server:** dashboard layout column, migration and endpoints; the audit list endpoint; tests; `pnpm gen:api`. One PR.
2. **Web, the customizable grid:** registry, edit mode, drag and drop, add/remove/reset/size, saving; existing cards moved in; the improved App card and compact Capabilities. One PR.
3. **Web, new cards:** Containers, Automation, Recent activity, Remote access. One PR.

## Acceptance checks

- **pytest:**
  - Layout round-trip, validation (bad id, duplicates, more than 40 cards, bad size), per-user isolation, and invalid stored JSON ignored.
  - Audit list: admin only (403 for others), limit bounds, newest first.
- **Browser (`athena-ui-verify`), at 1440 / 768 / 390 and in dark mode:**
  - Reorder with the mouse and with the keyboard, change a size, remove and re-add a card, then Reset.
  - Reload, and sign in from a second browser context, and the layout is kept.
  - A failed save (stopped server) rolls back with an error toast.
  - Cards whose capability is missing don't appear in the picker.
- **Reduced motion:** drag animations are off.

## Open questions

- None. Storage on the server, `@dnd-kit`, half/full sizes and the first four new cards were approved on 2026-11-20.
