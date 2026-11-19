# Plan: Raspberry Pi fixes and features from the competitor review

_Written 2026-11-19 from a review of the code, a read-only Raspberry Pi audit and a competitor survey. Nothing in it was run on a real Pi. Tick items off here and in `docs/STATUS.md` as they merge; move a phase to STATUS → Next when it's picked up._

## Summary

- **Raspberry Pi:** a Pi 4 or 5 on 64-bit Pi OS should mostly work. Every compiled Python dependency in `uv.lock` has a manylinux aarch64 wheel, Docker installs through get.docker.com, and the systemd unit is generic. What breaks: 32-bit Pi OS, the cloudflared install, store apps without an arm64 image that the store still offers, and memory on 1 GB boards.
- **Competitors:** the biggest gaps against them are backup and restore, HTTPS with a reverse proxy, and 2FA.
- **Where Athena leads:** it is the only one of these that runs on Linux, macOS and Windows; the only open-source one with an AI assistant that asks before acting and MCP in both directions; and the only one with system package management, cron/webhook automation and an audit log.

## Phase 1: fix what's broken (Raspberry Pi and catalog)

- [ ] **cloudflared download (every Linux host, Windows too).** `install` in `apps/server/src/athena/tunnel/cloudflare.py` asks for `cloudflared-linux-{arch}.tgz` and `cloudflared-windows-{arch}.zip`. The releases ship bare Linux binaries (`cloudflared-linux-amd64`, `-arm64`, `-arm`, `-armhf`) and a Windows `.exe`/`.msi`. Download the bare binary on Linux (chmod +x), the `.exe` on Windows, and map `armv7l` to `arm`. Only macOS has a `.tgz`.
- [ ] **Store apps by host architecture.** `platforms` defaults to `["linux/amd64", "linux/arm64"]` (`apps/server/src/athena/catalog/model.py`) and only 34 apps set it. The host arch is detected in `platform/detect.py` but never used, and `platforms` is only displayed (`apps/web/components/store/store-app-view.tsx`). Fix: (1) a script that fills `platforms` from the registry manifests and a `test_catalog.py` check (network-gated, like the image tag checks); (2) the store badges or hides apps that don't match the host, and install refuses with a clear message.
- [ ] **Catalog apps with no arm64 image** (as of 2026-11-19; 14 of 178 resolved apps): deepseek-ocr-nvidia, handbrake, llama-factory-nvidia, logseq (`correctroad/logseq`), motioneye (tag `master-amd64`), petio (pinned to the amd64 digest), pocketbase (`argonptg/pocketbase`), projectnomad, ragflow, roonserver, stablediffusionwebui, turbodiffusion-nvidia, vocechat, webdav (`ugeek/webdav:amd64`). Set their `platforms` to amd64, or switch to a multi-arch image where one exists (motioneye, petio, pocketbase, webdav, logseq). Only 31% of apps have armv7 for every image.
- [ ] **Broken image references (fail on every host)**: clumoove (uppercase in the image name); tags or images not found for crafty, dify (`langgenius/dify-server`), excalidraw, homebridge, hugo, mineos, ollama (`0.40.17`), opodsync, photoprism, librechat, playit-agent, playitagent, pinchflat, prowlarr, radarr, readarr, sonarr (lscr tags); ghcr "denied" for deepseekharness, indextts, gateway-go. n8n wasn't checked (Docker Hub rate limit). Re-check each before changing it; use the `athena-catalog-app` skill.
- [ ] **32-bit userland in `scripts/install.sh`.** The arch check rejects `armv7l`, but 32-bit Pi OS on a Pi 4/5 runs a 64-bit kernel, so `uname -m` says `aarch64` and the install goes on to build armhf wheels from source (several need Rust). Check `dpkg --print-architecture` (or `getconf LONG_BIT`) and stop with a message pointing to 64-bit Pi OS. Supporting armhf isn't worth it: Docker is dropping 32-bit Pi OS.
- [ ] **arm64 in CI.** Nothing tests Linux arm64. Add `ubuntu-24.04-arm` (free for public repos) to the server matrix in `ci.yml` and the install + smoke matrix in `e2e.yml`.
- [ ] **Memory on small boards.** Importing `athena.main` takes about 284 MB RSS and 2.1 s on a Mac, about two thirds of it the assistant stack (pydantic-ai, openai, fastmcp, exa) loaded eagerly through `api/assistant`. Import it on first use. Target: a usable Pi 3 / 1 GB board. A Pi Zero 2 W (512 MB) is out of scope.
- [ ] **Pi health in the stats.** Show under-voltage and throttling (`vcgencmd get_throttled`, or `/sys/devices/platform/soc/soc:firmware/get_throttled`) on the dashboard; it is the most common cause of Pi instability. Cache the `nvidia-smi` lookup in `monitor.py` instead of checking every 2 s tick.
- [ ] **Tunnel follow-ups** (already in STATUS, #150): `tunnel_auto_start` is never read at startup, and ngrok service files hold a literal token placeholder.
- [ ] **Verify on a real Pi** (or an arm64 Lima VM first, see `athena-host-test`): install, the service, the dashboard, and installing a few store apps.

## Phase 2: features, in priority order

1. [ ] **Backup and restore.** App volumes, compose files and Athena's own database; scheduled, encrypted, incremental; to a local disk or any rclone remote (Restic is the usual choice, check its license for §9). Cosmos, Umbrel, ZimaOS and Homeio have it; CasaOS (#1865) and Runtipi (#2312) users ask for it. Builds on rclone, the cron scheduler and jobs.
2. [ ] **HTTPS and a reverse proxy.** A domain per app (`app.home.lan` or a real domain), Let's Encrypt or a local CA, probably Caddy. Umbrel's most-upvoted issue (#546) and CasaOS #1074. Tunnels don't help on the LAN.
3. [ ] **2FA, then passkeys.** TOTP first. Athena exposes a terminal, package installs and an AI that acts on the host, so one password is too weak, especially with a tunnel on.
4. [ ] **Multiple users with roles** (admin, user, guest), per-user files and which apps each user sees. Today every account is an admin (`auth/service.py` `create_user`). Top request on CasaOS (#1789, #814) and Umbrel (#1711); Umbrel 2.0 shipped it.
5. [ ] **App updates.** Detect newer image versions, update in one click or automatically, and prune old images (Runtipi #1009, Cosmos #163).
6. [ ] **Alerts.** Email, ntfy or webhook when a disk fills up, a container goes down or a job fails; driven by the automation triggers.
7. [ ] **Stats history.** Stats are live only; keep a downsampled history to show trends (a filling disk, a memory leak).
8. [ ] **Disk management.** Mount and format USB drives, SMART health; later MergerFS or Btrfs RAID (ZimaOS, Umbrel, Cosmos do this; CasaOS #1088).
9. [ ] **Later:** SSO/OIDC for installed apps (Cosmos, YunoHost); a PWA or companion app; per-app data paths and several instances of one app (Runtipi #1543, #269); a guest dashboard (Runtipi #1249); importing existing compose projects (already in `docs/design/milestones.md` → Backlog).

Each feature needs a design section and a §11 decisions-log row in `docs/design/` before it starts.

## Competitor snapshot (2026-11-19)

| Feature | Athena | CasaOS | ZimaOS | umbrelOS 2.0 | Homeio | Cosmos | Runtipi | Udon |
|---|---|---|---|---|---|---|---|---|
| Host OS | Linux/macOS/Windows | Linux | Own OS (x86) | Own OS (x86, Pi 5) | Debian/Pi OS | Linux | Linux 64-bit | macOS only |
| Store size | ~200 | ~150 | as CasaOS | 300+ | ~160 | market + compose | ~300 | curated |
| Backup/restore | no | no | yes | yes | yes | yes (Restic) | per app | ? |
| HTTPS / reverse proxy | tunnels only | no | ? | no | ? | yes | yes (Traefik) | Tailscale |
| 2FA | no | no | ? | yes | no | yes | ? | ? |
| Multi-user | admins only | no | yes (3 free) | yes | no | yes | no | no |
| Disks / RAID | no | no | yes | yes | USB mounts | MergerFS | no | drive health |
| Alerts | no | no | ? | ? | no | yes | update notices | ? |
| AI assistant / MCP | yes / yes | no | local AI search | MCP server only | no | no | no | yes / yes |
| License | open source | Apache-2.0 | freemium | noncommercial | AGPL | Apache + Commons Clause | GPL-3.0 | proprietary |

Notes:
- **CasaOS** has seen little core development since v0.4.15 (Dec 2024) while IceWhale works on ZimaOS; users report breakage with Docker 29.
- **Udon** (udon.sh) is a paid, closed macOS-only "AI sysadmin" for Mac home servers, pre-release from one developer; the closest to Athena's idea.
- **Homeio** (github.com/ikhsanddy/homeio) is a single-user CasaOS-style panel that imports CasaOS store archives.

Sources: [Cosmos](https://github.com/azukaar/Cosmos-Server), [Umbrel](https://github.com/getumbrel/umbrel), [umbrelOS 2.0](https://community.umbrel.com/t/introducing-umbrelos-2-0/25444), [ZimaOS 1.5](https://itsfoss.com/news/zimaos-1-5-release/), [Runtipi](https://runtipi.io/), [CasaOS](https://github.com/IceWhaleTech/CasaOS), [Homeio](https://github.com/ikhsanddy/homeio), [Udon](https://www.udon.sh/). The "?" cells weren't confirmed.
