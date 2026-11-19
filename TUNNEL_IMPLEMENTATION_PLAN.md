# Remote Access Tunnel Feature - Implementation Plan

## Overview
Add support for three tunnel providers (Cloudflare Tunnel, Tailscale Funnel, Ngrok) with unified UI in Settings → System, auto-start on boot when enabled, and easy setup/download if not installed.

## Decisions Made

1. **Cloudflare Tunnel**: Support both named tunnels (persistent, needs domain) AND quick tunnels (trycloudflare.com, ephemeral)
2. **Ngrok**: Warn about free tier limits (1 tunnel, 40 connections/min) in UI
3. **Tailscale**: Detect login status; if not logged in, guide user through `tailscale up`
4. **Provider priority**: Cloudflare → Tailscale (if installed) → Ngrok
5. **Default port**: Athena's port (8420), allow override in config
6. **Storage**: Use existing `system_settings` table (key="system"), JSON value with encrypted secrets via `SecretBox`

---

## Implementation Tasks

### Phase 1: Backend Core

#### 1.1 Capability Detection ✅ (Design complete, needs implementation)
**File**: `apps/server/src/athena/platform/detect.py`
- Add three new detector functions:
  - `detect_tunnel_cloudflare(probe)` → `tunnel.cloudflare`
  - `detect_tunnel_tailscale(probe)` → `tunnel.tailscale`
  - `detect_tunnel_ngrok(probe)` → `tunnel.ngrok`
- Each returns `ready`/`stopped`/`missing` with appropriate `actions` (`start`, `setup`)
- Add to `detect_builtin()` list

#### 1.2 Tunnel Provider Package
**Directory**: `apps/server/src/athena/tunnel/`

| File | Purpose |
|------|---------|
| `__init__.py` | Registry `TUNNEL_PROVIDERS` keyed by capability id |
| `base.py` | Abstract `TunnelProvider` base class |
| `cloudflare.py` | Cloudflare Tunnel implementation |
| `tailscale.py` | Tailscale Funnel implementation |
| `ngrok.py` | Ngrok implementation |

**Provider Interface** (in `base.py`):
```python
class TunnelProvider(ABC):
    @abstractmethod
    async def start(self, job: Job, config: TunnelConfig) -> str:  # Returns public URL
    
    @abstractmethod
    async def stop(self, job: Job) -> None:
    
    @abstractmethod
    def status(self) -> TunnelStatus:  # running/stopped, public_url, config
    
    @abstractmethod
    def get_config_schema(self) -> dict:  # JSON schema for UI form
    
    @abstractmethod
    async def install(self, job: Job) -> None:  # Download/install binary
    
    @abstractmethod
    async def configure_service(self, job: Job, enabled: bool) -> None:  # systemd/launchd/Task
```

#### 1.3 System Settings Extension
**File**: `apps/server/src/athena/system_settings.py`

Extend `SystemSettings` model:
```python
class SystemSettings(BaseModel):
    terminal_enabled: bool = True
    tunnel_enabled: bool = False           # Master toggle
    tunnel_provider: str | None = None     # "cloudflare" | "tailscale" | "ngrok"
    tunnel_config: dict = {}               # Provider-specific config (encrypted secrets)
    tunnel_auto_start: bool = True         # Auto-start on boot when enabled
    tunnel_port: int = 8420                # Local port to expose
```

#### 1.4 API Router
**File**: `apps/server/src/athena/api/tunnel.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tunnel/status` | GET | Current status, public URL, provider |
| `/api/tunnel/start` | POST | Start tunnel (returns job_id) |
| `/api/tunnel/stop` | POST | Stop tunnel (returns job_id) |
| `/api/tunnel/config` | PUT | Update provider + config (admin) |
| `/api/tunnel/install` | POST | Download/install binary (admin) |
| `/api/tunnel/service` | PUT | Enable/disable auto-start service (admin) |

#### 1.5 Register Router
**File**: `apps/server/src/athena/main.py`
- Import and include tunnel router with `require_user` dependency

#### 1.6 Database Migration
- Run `uv run alembic revision --autogenerate -m "add tunnel settings"` after model changes
- Migration will be auto-generated from `SystemSettings` model changes

---

### Phase 2: Service Management (Auto-start on Boot)

| OS | Mechanism | Implementation |
|----|-----------|----------------|
| Linux | systemd unit | `cloudflared.service`, `tailscaled` (already runs), `ngrok.service` |
| macOS | launchd agent | `~/Library/LaunchAgents/com.athena.tunnel.plist` |
| Windows | Scheduled Task | At logon (like Athena service in `service/platforms.py`) |

**Provider-specific service config**:
- **Cloudflare**: systemd unit running `cloudflared tunnel run --config /etc/cloudflared/config.yml <tunnel-name>`
- **Tailscale**: `tailscaled` already runs as daemon; funnel configured via `tailscale funnel <port>`
- **Ngrok**: systemd/launchd running `ngrok http --authtoken=<token> <port>`

---

### Phase 3: Installation Helpers

When binary missing, "Install" button downloads and installs:

| Provider | Method |
|----------|--------|
| **cloudflared** | Download latest release from GitHub, verify checksum, install to `/usr/local/bin` (Linux/macOS) or `~/scoop/shims` (Windows) |
| **tailscale** | Run official install script: `curl -fsSL https://tailscale.com/install.sh \| sh` |
| **ngrok** | Download from ngrok.com, install to PATH |

---

### Phase 4: Frontend UI

#### 4.1 New Component: TunnelCard
**File**: `apps/web/components/settings/tunnel-card.tsx`

Features:
- Provider selector dropdown (Cloudflare / Tailscale / Ngrok)
- Config form per provider:
  - **Cloudflare**: API Token (secret), Tunnel Name, Domain (optional, for named tunnels), Quick Tunnel checkbox
  - **Tailscale**: No extra config (uses existing tailnet); show tailnet name if logged in
  - **Ngrok**: Auth Token (secret), Domain/Subdomain (optional), show free tier warning
- Status display: Public URL with copy button, connection state badge
- Start/Stop buttons (opens JobDialog with live logs)
- "Install" button when binary missing (downloads + verifies)
- "Auto-start on boot" toggle
- Test connection button

#### 4.2 Update System Form
**File**: `apps/web/components/settings/system-form.tsx`
- Add tunnel enable/disable toggle in Security card (like terminal toggle)

#### 4.3 Update Settings Page
**File**: `apps/web/app/(app)/settings/system/page.tsx`
- Include `<TunnelCard />` after `<SystemForm />` and `<WebDavCard />`

#### 4.4 API Client Generation
```bash
pnpm gen:api
```
Run from repo root after API router is created.

---

### Phase 5: Testing

#### 5.1 Unit Tests
**File**: `apps/server/tests/test_tunnel.py`
- Detection tests: Mock `shutil.which` and subprocess
- Provider tests: Recorded CLI output fixtures in `tests/fixtures/tunnel/`
- Config encryption/decryption tests

#### 5.2 Fixtures
**Directory**: `apps/server/tests/fixtures/tunnel/`
- `cloudflare_version.txt`, `cloudflare_tunnel_list.txt`
- `tailscale_status_logged_in.json`, `tailscale_status_not_logged_in.json`
- `ngrok_version.txt`, `ngrok_api_tunnels.json`

#### 5.3 Integration Tests
- Use `ATHENA_DOCKER_TESTS=1` for real binary tests where available
- Test service creation on each OS

#### 5.4 Browser Verification
- Use `athena-ui-verify` skill after UI changes
- Test on phone width (390px) and dark mode

---

## Provider-Specific Details

### Cloudflare Tunnel
**Two modes**:
1. **Quick Tunnel** (trycloudflare.com): `cloudflared tunnel --url http://localhost:8420` - ephemeral URL, no auth needed
2. **Named Tunnel**: Requires API Token, creates persistent tunnel with custom domain

**Config schema**:
```json
{
  "api_token": "string (encrypted)",
  "tunnel_name": "string",
  "domain": "string (optional)",
  "quick_tunnel": "boolean"
}
```

**Installation**: Download from https://github.com/cloudflare/cloudflared/releases

### Tailscale Funnel
**Requirements**: Tailscale installed, logged in (`tailscale up`), Funnel enabled in admin console

**Config schema**:
```json
{
  "tailnet_name": "string (read-only, detected)"
}
```

**Commands**:
- Enable: `tailscale funnel 8420`
- Disable: `tailscale funnel off`
- Status: `tailscale funnel status`

### Ngrok
**Free tier limits**: 1 tunnel, 40 connections/min, random URL each session

**Config schema**:
```json
{
  "auth_token": "string (encrypted)",
  "domain": "string (optional, requires paid plan)",
  "subdomain": "string (optional, requires paid plan)"
}
```

**Commands**:
- Start: `ngrok http --authtoken=<token> 8420`
- API: `ngrok api tunnels` (check running tunnels)

---

## File Summary

### New Files
```
apps/server/src/athena/tunnel/
├── __init__.py
├── base.py
├── cloudflare.py
├── tailscale.py
└── ngrok.py

apps/server/tests/test_tunnel.py
apps/server/tests/fixtures/tunnel/*.txt

apps/web/components/settings/tunnel-card.tsx
```

### Modified Files
```
apps/server/src/athena/platform/detect.py           # Add 3 detectors
apps/server/src/athena/system_settings.py           # Add tunnel fields
apps/server/src/athena/api/tunnel.py                # New router
apps/server/src/athena/main.py                      # Register router
apps/server/db/migrations/versions/xxx_add_tunnel_settings.py  # Auto-generated

apps/web/components/settings/system-form.tsx        # Add tunnel toggle
apps/web/app/(app)/settings/system/page.tsx         # Include TunnelCard
```

---

## Implementation Order

1. **Backend detection** → `detect.py` (copy designed functions)
2. **Provider package** → `tunnel/` (base + 3 implementations)
3. **System settings** → `system_settings.py` model changes
4. **API router** → `api/tunnel.py`
5. **Register router** → `main.py`
6. **Run migration** → `alembic revision --autogenerate`
7. **Generate API client** → `pnpm gen:api`
8. **Frontend** → `tunnel-card.tsx`, update `system-form.tsx`, `page.tsx`
9. **Tests** → `test_tunnel.py`, fixtures
10. **Browser verify** → `athena-ui-verify`

---

## Notes for Next Session

- Work in the worktree: `/Users/tiago/Projects/athena-feat-tunnel`
- Branch: `feat/tunnel`
- Run tests with: `cd apps/server && uv run pytest -q`
- Run lint: `cd apps/server && uv run ruff check && uv run ruff format --check`
- Run web checks: `pnpm lint && pnpm typecheck && pnpm build`
- Full check: `scripts/check.sh --quick` from repo root