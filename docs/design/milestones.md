# 10. Milestones

| # | Milestone | Done when |
|---|---|---|
| M0 | Monorepo skeleton | shadcn init done, uv server, turbo, API client generation, CI on all 3 OSes (GitHub Actions matrix) |
| M1 | Platform + capabilities | The manifest is correct on Linux, macOS and Windows, the UI hides missing features, and the first-run wizard and login work |
| M2 | Containers + apps | Runtime detection on all OSes (start for Colima), Windows setup instructions, app lifecycle, logs, compose and docker-run import |
| M3 | App store | Built-in catalog, remote catalogs, CasaOS importer, install form |
| M4 | Dashboard + appearance | Live stats and charts. Runtime theme/base/chart/font/radius switching, plus the style decision |
| M5 | Packages + terminal | All detected managers with jobs. Host terminal and container exec on all OSes |
| M6 | Files, shares, cloud | File manager, share links, WebDAV, rclone remotes and copy/sync |
| M7 | AI assistant | Agent with service tools, approval flow, provider settings, streaming chat UI |
| M8 | Automation | Cron and webhook triggers with job-run history, Athena's MCP server, the Automation page |

M2–M4 can proceed in parallel once M1 lands, and so can M5 and M6. M7 depends on the service layers it wraps, and M8 on the app and package services its actions call.

## Backlog

Ideas with no milestone yet. Move one into `docs/STATUS.md` → Next when it's picked up.

- **from the competitor review** (`docs/plans/improvements.md` → Phase 2): backup and restore, HTTPS with a reverse proxy, 2FA, users with roles, app updates, alerts, stats history, disk management.

- **cloud:** mounts (FUSE; `rclone nfsmount` on macOS), scheduled or saved syncs, encrypting the rclone config with the OS keyring (§7), uploads to a remote without staging the whole file on the server first, Range requests for seeking in remote videos, and stopping an orphaned `rclone rcd` if Athena is killed (`SIGKILL` leaves it running).
- **shares:** a size limit for upload links, per-file audit of WebDAV changes, locks that survive a restart, WebDAV for more than one account, and NFS shares.
- **files:** folder uploads (drag a folder), resumable uploads across page reloads, and search.
- a switch for package installs in Settings → System (§7), next to the terminal's (the assistant's shell already has one in Settings → AI). Proxying the terminal WebSocket in `next dev` hasn't been checked; use the release build to work on it.
- a CI check that `themes.css` matches the registry (needs network; run `pnpm gen:theme` after shadcn upgrades for now), and switching shadcn styles at runtime (§5.4).
- auto-refreshing catalogs on a schedule, stripping missing host devices from imported apps, and Docker Hub login for pulls (rate limits).
- per-container stats, verifying temperatures on a real Linux host, importing existing compose projects not created by Athena, and Windows path translation for WSL bind mounts.
