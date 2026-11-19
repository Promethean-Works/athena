# 7. Security baseline

- Binds to LAN by default. First run forces the admin account to be created before anything else is reachable.
- Public routes (no session): `/api/health`, `/api/auth/*`, share links (`/api/public/shares/{token}`, `/s/{token}`), the automation webhook `POST /api/automation/webhook/{token}` (the trigger's random token is the credential) and `/api/mcp` with the `ATHENA_MCP_TOKEN` bearer (acts as the admin; a session cookie works too). `/dav/` has its own sign-in. Everything else needs a session.
- Session cookies are `HttpOnly` and `SameSite=Strict`, with CSRF tokens on mutating requests and login rate limiting.
- The terminal, package installs and the assistant's shell are the most powerful features. They're admin-only and every use is written to the audit log. The terminal (Settings → System) and the assistant's shell (Settings → AI, off by default) can be turned off; package installs have no off switch yet.
- Remote access tunnels (§4.8) put the UI on the internet: off by default, admin-only, with their tokens encrypted at rest.
- The rclone rcd and container sockets are never exposed beyond localhost.
- Secrets: AI provider keys, integration tokens and tunnel tokens are encrypted at rest (Fernet) with a key file `<data-dir>/secret.key` (0600), not the OS keyring, which headless Linux hosts usually lack (M7, see §4.5). The rclone config is a 0600 file in a 0700 folder, with passwords obscured by rclone (reversible, not encryption). See §11.
