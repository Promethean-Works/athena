# 1. MVP scope

| Area | In the MVP | Later |
|---|---|---|
| Dashboard | Host stats (CPU, RAM, disk, network, uptime), running apps grid, runtime status | Custom widget layout, multi-node |
| Container runtime | Detect, report status, start the runtime (Colima on macOS), guided setup when missing | One-click runtime install on every OS |
| Apps (containers) | List, start/stop/restart, logs, stats, remove, update image | Backups, auto-update policy |
| App store | Built-in catalog plus remote catalogs (Git/HTTP), install with editable env/ports/volumes | Ratings, signed catalogs |
| Custom apps | Import a `docker run` command, paste/upload a `compose.yaml`, edit before deploy | Import from a Git repo |
| Package managers | Search, install, uninstall, list installed, upgrade, for each detected manager | Scheduled upgrades |
| Terminal | Web terminal to the host shell (bash/zsh/PowerShell) and `exec` into containers | Session sharing, recordings |
| Files | Browse, upload, download, rename, move, delete, preview text and images | Thumbnails, search index |
| File sharing | Public/expiring share links, WebDAV share of chosen folders, SMB shares (Linux, macOS, Windows) and NFS shares (Linux, macOS), when Athena runs privileged | NFS on Windows (no server outside Windows Server) |
| Cloud storage | Add remotes via rclone (Google Drive, OneDrive, Dropbox, S3, WebDAV…), browse, copy/sync jobs | Mounts as local drives, scheduled sync |
| AI assistant | Chat that can query state and do actions through Athena's own services, with approval for destructive actions | Proactive alerts, runbooks |
| Settings | Appearance (style, base color, theme, chart color, heading font, body font, radius), users, AI provider, catalogs | RBAC, SSO |
| Auth | Single admin account, created in a first-run wizard | Multiple users with roles |
| Automation (M8) | Cron and webhook triggers that run app and package actions, and an MCP server for outside agents (§4.7) | Event triggers |
| Remote access | Cloudflare Tunnel, Tailscale Funnel or ngrok, set up from Settings → System (§4.8) | Athena starting the tunnel itself at boot |
