# 2. Architecture

```
┌──────────────────────────── Browser ───────────────────────────┐
│  Next.js (static export) + shadcn/ui  ·  xterm.js  ·  AI chat  │
└───────────────▲──────────── REST / SSE / WebSocket ────────────┘
                │                 MCP clients, webhooks, tunnels
┌───────────────┴─────────── athena-server (Python, uv) ─────────┐
│ api/ (thin FastAPI routers) → the area packages below          │
│                                                                │
│ platform/    probe · detect ─► CapabilityManifest              │
│ containers/  Docker-compatible CLI: Docker Engine, Colima,     │
│              Podman, Docker in WSL                             │
│ apps/ catalog/   compose apps, built-in and remote catalogs    │
│ packages/    apt dnf pacman zypper apk brew flatpak snap       │
│              winget scoop choco                                │
│ terminal/    stdlib pty (POSIX) · pywinpty (Windows)           │
│ files/       locations · share links · WebDAV · SMB            │
│ cloud/       rclone rcd (sidecar process)                      │
│ assistant/   pydantic-ai Agent + harness + Athena tools        │
│ automation/  cron and webhook triggers                         │
│ mcp/         Athena's MCP server at /api/mcp                   │
│ tunnel/      cloudflared · tailscale · ngrok                   │
│ service/     athena service install (systemd, launchd, Task)   │
│ auth/ db/ jobs.py (in memory) audit.py monitor.py crypto.py    │
│ SQLite: users, sessions, apps, settings, file locations,       │
│         shares, AI chats, audit log, automation triggers/runs  │
└────────────────────────────────────────────────────────────────┘
        │ Docker-compatible CLI   │ CLI subprocess       │ HTTP
   Docker Engine / Colima /   package managers       rclone rcd
   Podman / Docker in WSL
```

## Decisions

- **One backend process serves everything.** Next.js is built with `output: "export"` and the static files are served by FastAPI. Users don't need Node.js on their server and packaging stays simple. The trade-off is no SSR or server actions; every page is a client component that calls the API. That's acceptable for a LAN dashboard.
- **Typed contract.** FastAPI generates OpenAPI. `openapi-typescript` and `openapi-fetch` generate the TS client in `packages/api-client`, so the frontend never hand-writes request types.
- **Realtime.** Server-Sent Events carry stats, logs, job progress and the AI chat stream. WebSockets are used only where input is two-way, which means the terminal.
- **Long operations are jobs.** Image pulls, package installs and rclone syncs return a `job_id` right away and stream progress over SSE. A small in-memory job runner (`athena/jobs.py`, keeping the last 100 finished jobs) is enough; no Celery or Redis. Jobs don't survive a restart: the durable records are the audit log and, for automation, `automation_job_runs`.
- **Talk to container engines through a Docker-compatible CLI** (`docker --host <endpoint>`, `podman --url <endpoint>`, or `wsl.exe -e docker`), using `python-on-whales` for structured reads and direct subprocesses for streamed operations (logs, compose up, pulls). Revised in M2 from "Docker API via the docker SDK": Docker inside WSL2 has no socket reachable from Windows, and the CLI is the one path that covers it, Docker Engine, Colima, Podman and Rancher Desktop alike. Detection still pings the Docker API socket directly (no CLI needed for that).
