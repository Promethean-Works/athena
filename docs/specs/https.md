# Spec: HTTPS for Athena (self-signed and Let's Encrypt)

**Status:** Approved (2026-11-20), parts 1–2 done (#192, #196) · **Milestone:** Backlog (competitor review, `docs/plans/improvements.md` → Phase 2 item 2, first half) · **Design:** `docs/design/security.md` (new section "HTTPS")

## Goal

The admin can turn on HTTPS for Athena's own UI and API from Settings → HTTPS, in one of two modes:

- **Self-signed:** Athena makes its own local certificate authority and a certificate for every name and LAN address the host has. The admin downloads the CA once, trusts it on their devices, and gets a padlock with no warnings.
- **Let's Encrypt:** for a domain the admin owns. Athena gets a free, publicly trusted certificate and renews it on its own.

Today everything is plain HTTP on port 8420, so passwords and session cookies cross the LAN unencrypted, and browser features that need a secure context (clipboard, service workers, PWA install) don't work.

## Non-goals

- A domain per store app (`jellyfin.home.lan`) or a reverse proxy in front of apps. That is the second half of the improvements item and gets its own spec; this one only builds the certificate pieces it will reuse.
- Uploading your own certificate and key. Easy to add later (same storage); left out to keep the first version small. See open questions.
- HSTS. One wrong switch would lock browsers out of a LAN server for months.
- DNS providers other than Cloudflare in the first version (each later one is a table entry).
- Assistant or MCP tools that change HTTPS (a mistake would cut off the UI). A read-only status tool only.

## Platforms

Pure Python (`cryptography` is already a dependency, uvicorn serves TLS), so it works the same on Linux, macOS and Windows. New capability `https`, always reported. Let's Encrypt runs the lego binary, which exists for every OS and architecture Athena supports (Linux amd64, arm64 and armv7, macOS, Windows). The HTTP-01 challenge needs port 80: before starting, the server checks it can bind port 80 and shows "port 80 is in use by …" or "Athena can't open port 80" otherwise (on macOS and Windows the service runs as the user; macOS 10.14+ allows it, Windows does too; Linux runs as root). Each OS's firewall may need the new HTTPS port opened; the page says so, and installers don't change.

## Design

### Listeners

- HTTP stays on `port` (8420). HTTPS listens on a new `https_port` (default 8443) when a mode is on. Both are `uvicorn.Server` instances in one process serving the same app; the second runs with `lifespan="off"` so startup tasks (scheduler, job worker) run once.
- **Redirect HTTP to HTTPS** (on by default when HTTPS is on), as a 307 (browsers cache 308 forever). Only browser page loads are redirected: GET/HEAD navigations outside `/api/` and `/dav`. API calls, WebDAV, MCP, webhooks, loopback and proxied (tunnel) requests never are, so a page open over HTTP, mounts and apps in containers keep working, and `curl http://127.0.0.1:8420` is a way back in.
- Changing the mode or port restarts only the HTTPS listener, in process. A renewed certificate is loaded into the running `SSLContext` with `load_cert_chain` (new handshakes use it), so renewals need no restart.
- Session cookies already set `Secure` when the request is HTTPS (`api/auth.py`, `api/shares.py`); nothing changes there.
- Tunnels keep pointing at the HTTP port (they terminate TLS themselves).

### Storage

- Settings are `HttpsSettings` in their own `https` row of `system_settings` (`athena/https/settings.py`), so saving Settings → System can't overwrite them: `mode: "off" | "self_signed"` (part 3 adds `"letsencrypt"`), `port`, `redirect`, `extra_names: list[str]`, and in part 3 `letsencrypt: { domains, email, challenge: "http" | "dns", dns_provider, dns_config, staging }`. DNS provider tokens are secrets: encrypted with `SecretBox`, never returned (same pattern as `tunnel_config`). The HTTPS listener reads them from the DB in the app's lifespan.
- Files in `<data-dir>/tls/` (created 0700, keys 0600; on Windows the data dir is already per-user): `ca.key`, `ca.crt`, `server.key`, `server.crt` for self-signed; `lego/` (lego's account and certificates), `le.key`, `le.crt` (full chain) for Let's Encrypt. Private keys aren't encrypted with `SecretBox`, because uvicorn needs a plain file; file permissions protect them, like the SQLite DB and the secret key next to it.

### Self-signed (`athena/https/local_ca.py`)

- CA: EC P-256, `Athena Local CA (<hostname>)`, 10 years, `BasicConstraints(ca=True, path_length=0)`, made once.
- Server certificate: EC P-256, 365 days (under Apple's 825-day limit for user-trusted CAs), signed by the CA. SANs: `localhost`, the hostname, `<hostname>.local`, `127.0.0.1`, `::1`, every non-loopback address of the host's interfaces (psutil), plus `https_extra_names` (validated as hostnames or IPs).
- A daily check (and startup) reissues the server certificate when it has under 30 days left or the address list changed. The CA never changes unless the admin clicks "Make a new CA".

### Let's Encrypt (`athena/https/letsencrypt.py`)

- Runs [lego](https://github.com/go-acme/lego) (MIT) as a subprocess. Athena downloads a pinned lego release for the host's OS and architecture into `<data-dir>/bin/`, checks it against the release's published SHA-256 checksums, and refuses to run a file that doesn't match. The download helper is shared, so the cloudflared download can move to it later.
- Challenges: **HTTP-01** (lego answers on a temporary port-80 listener during validation; the domain must point at this host and port 80 must be reachable from the internet) and **DNS-01** (lego creates and removes the `_acme-challenge` TXT record through the DNS provider's API; works with no open ports, and for wildcards). The first DNS provider is **Cloudflare**; each provider is one entry in a table in `athena/https/dns_providers.py` (lego provider code plus the fields and environment variable names it needs), so more are a small change.
- Provider credentials are passed to lego only as environment variables of the child process (never on the command line, never logged). lego's own data lives in `<data-dir>/tls/lego/`; Athena copies the issued certificate to `le.crt`/`le.key`.
- "Use the staging server" toggle for testing without hitting rate limits.
- Getting and renewing a certificate runs as a **job** (`jobs.py`) that streams lego's output into the job log. A daily check runs `lego renew --days 30`; a failure keeps the old certificate, records the error, and the Settings page and dashboard show it. Audit entries: `https.mode_changed`, `https.certificate_issued`, `https.renewal_failed`.

### Server routes (`api/https.py`, admins only)

- `GET /api/https` (`getHttpsStatus`): mode, ports, redirect, URLs to open, current certificate (issuer, names, not-after, fingerprint), last renewal and last error, whether port 80 is free.
- `PUT /api/https` (`setHttpsSettings`): saves settings; validates names, domains, email and port (not equal to `port`, 1–65535, bindable: the server binds it first and refuses with a clear error otherwise, so a bad port can't take the UI down).
- `POST /api/https/certificate` (`issueHttpsCertificate`, part 3): get or renew a Let's Encrypt certificate now; returns a job id.
- `POST /api/https/ca/rotate` (`rotateHttpsCa`): new local CA.
- `GET /api/https/ca.crt` (`downloadHttpsCa`): the CA certificate (public, but behind login anyway).

### CLI (escape hatch)

- `athena https status --data-dir …` and `athena https off --data-dir …` (turns HTTPS off in the DB; the next start serves plain HTTP). Documented on the Settings page and in `docs/`.

### Web: Settings → HTTPS

- Status card: mode, the HTTPS URL, certificate names and expiry, last error (`Alert`).
- Mode as a radio group: Off / Self-signed / Let's Encrypt.
- Self-signed: extra names (tag input), "Download CA certificate" with short per-OS steps (macOS Keychain, Windows certificate store, Linux, iOS, Android), "Make a new CA" (confirm dialog).
- Let's Encrypt: domains, email, challenge (HTTP / DNS with a provider picker and its fields), staging switch, "Get certificate" (opens the job's log).
- HTTPS port and the redirect switch. Before saving a change that turns on redirect, a dialog shows the new URL and the CLI way back in. After saving, the page offers a link to the HTTPS URL.

### Assistant / MCP

- One read-only tool, `https_status`, so "is my certificate expiring?" works. No approval needed.

### Security

- Admin-only routes, CSRF on writes like every other route. DNS provider tokens are encrypted, write-only, and reach lego only through its environment. The lego binary is checksum-verified before every first run after download. Keys never leave the server (no download of `*.key`). Domains, names and email are validated; the port is test-bound before saving. Logs never include keys or tokens.

### Dependencies

- lego (MIT), downloaded at runtime and recorded in `docs/design/licenses.md`. No new Python packages (`cryptography`, `httpx`, `psutil`, uvicorn are already there).

## Parts

1. **Server: listeners and self-signed.** `athena/https/`, settings fields, two listeners, redirect, local CA, daily reissue check, routes, CLI `athena https`, `https` capability, `pnpm gen:api`. Tests for cert contents, SANs, reissue rules, redirect (and loopback/health exceptions), port validation, a real TLS request with `httpx` against a test server.
2. **Web: Settings → HTTPS (off and self-signed).** Page, CA download and steps, lockout dialog. Verified with `athena-ui-verify` on a spare port, including opening the HTTPS URL.
3. **Let's Encrypt.** lego download and checksum check, HTTP-01, Cloudflare DNS-01, renewal job and daily check, UI section, audit, `https_status` tool. Tests against Pebble (Let's Encrypt's test ACME server, MPL-2.0, run in a container in CI) for the HTTP-01 flow; lego invocations mocked for DNS-01.
4. **Docs and real hosts.** Design section and decision row, `docs/agents/gotchas` notes, `athena-host-test` on a Linux VM (service restart keeps HTTPS, port 80 for HTTP-01) and the Windows E2E workflow.

## Acceptance checks

- Self-signed on: `https://<lan-ip>:8443` serves a certificate signed by the downloaded CA, with the LAN IP and hostname in the SANs; `http://<lan-ip>:8420` redirects; `http://127.0.0.1:8420` doesn't.
- Login over HTTPS sets a `Secure` cookie.
- Renewal: a certificate with 10 days left is reissued by the daily check without a restart (handshake shows the new serial).
- A port already in use is refused at save time, and the UI stays up.
- `athena https off` brings back plain HTTP on the next start.
- Let's Encrypt staging: a certificate is issued against Pebble in CI; a failed renewal keeps the old certificate and shows the error.
- All of it on Linux, macOS and Windows (CI runs the server tests on all three).

## Decisions (2026-11-20)

- Separate HTTPS port (8443) with a redirect from 8420: one port can't speak both, and 8420 keeps bookmarks, tunnels and the CLI working.
- lego over the Python `acme` library: many DNS providers for a table entry each, and no ACME code to maintain in Athena; the download is pinned and checksum-verified.
- Cloudflare is the first DNS provider.
- No uploading your own certificate in this round (small follow-up).
- No installer `--https` flag.
