# 4.2 Terminal

- Backend: a WebSocket at `/api/terminal/ws?target=host|container:<id>`. On POSIX it uses the stdlib pty, and on Windows it uses `pywinpty` (ConPTY) running PowerShell 7, or Windows PowerShell when 7 isn't installed. A container shell runs `docker exec -it` through the same CLI as the rest of Athena, so Docker in WSL works too.
- Frontend: `xterm.js` with the fit and web-links addons, themed from the active CSS variables.
- Admin only, and it can be turned off globally in settings.

**As built (M5):**
- `athena/terminal/pty.py` (`PtySession`) gives one async interface over both OSes.
  - A reader thread feeds a bounded queue, so a slow browser stalls the program instead of filling memory.
  - Writes run in a thread.
  - Closing hangs up the whole session (SIGHUP to the process group, then SIGKILL).
  - POSIX doesn't use `pty.fork()` or ptyprocess. Forking the multi-threaded server and running Python in the child can deadlock it. `subprocess.Popen(start_new_session=True)` forks and execs in C, and a two-line shim (`TIOCSCTTY`, then `execvp`) makes the pty the controlling terminal, so Ctrl+C and job control work. A missing program exits 127.
- `athena/terminal/shells.py` chooses what to run:
  - On the host, the service user's login shell (`-l`); `/bin/sh` if it's missing or `nologin`.
  - In a container, bash if the image has it, otherwise sh, with `TERM=xterm-256color`.
- The protocol:
  - After connecting, the browser sends `{"type":"auth","csrf","cols","rows"}` with the session's CSRF token. Browsers can't set headers on a WebSocket, and a cross-site page can't read the token.
  - The server sends `{"type":"ready"}`, then output as binary frames.
  - The browser sends `{"type":"input"}` and `{"type":"resize"}` text frames.
  - When the program exits, the server sends `{"type":"exit","code"}` and closes with 1000.
- Close codes, shown to the user with their reason:
  - 4401: no session, or signed out.
  - 4403: bad CSRF token, or not an admin.
  - 4404: bad target.
  - 4409: turned off, unsupported, or the runtime isn't ready.
  - 4429: more than 10 open terminals.
  - 4500: the program couldn't start.
- Session checks while a terminal is open:
  - Signing out, or the session expiring, closes it within 60 s.
  - Turning the terminal off (`PUT /api/settings/system`) closes every open terminal at once.
- Audit: `terminal.open` and `terminal.close` (exit code or reason, duration), with target `host` or `container:<ref>`; `settings.terminal` on/off.
- UI:
  - `/terminal` (nav item gated by `terminal.host`) with a status badge and New session.
  - A **Shell** action on running containers, both on the Containers page and in app detail, opening a sheet.
  - Settings → System holds the switch.
  - `<Terminal>` in `packages/ui/.../athena/terminal.tsx` themes xterm.js from the CSS variables (converted to rgba through a canvas so oklch works) and re-themes when `<html>` attributes change. The ANSI hues are two fixed palettes, chosen by background lightness. Links in output (OSC 8 and plain URLs) open only if they're http(s), in a new tab with no opener; program output is untrusted, and xterm's default OSC 8 handler would also follow `javascript:`.
