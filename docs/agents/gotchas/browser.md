# Gotchas: Browser verification (`athena-ui-verify`)

- Base UI checkboxes and switches render a hidden `<input>`. A click on it "works" but sends the wrong value, and only `browser_network_requests` showed that. Click the visible control and re-snapshot.
- Take a fresh snapshot after a dialog closes or the layout shifts. Stale refs click the wrong thing, and clicking while a page is still loading misses.
- A rebuilt web export is served without restarting the server. Server or catalog changes need a restart.
- Fake anything that would change the host: a stub `brew`/`colima` first on the server's `PATH` (reads can pass through to the real tool), or `HOME` pointed at an empty folder so a runtime looks stopped. For files, point `HOME` at a scratch folder so the default Home location isn't the real one.
- Anonymous Docker Hub pulls are rate-limited (429). Image-checking loops used up the quota for hours. Prefer ghcr.io or codeberg.org images in tests, and don't loop `docker manifest inspect`.
- Keep the developer's personal data out of fixtures and screenshots. For example, a fixture once used a real installed-cask list and was replaced with neutral entries.
- Playwright MCP can crash at launch on macOS (`SIGTRAP`, `bootstrap_check_in … MachPortRendezvousServer: unknown error code (124)`), even outside the sandbox. It was transient: the same call worked a few minutes later. Retry before giving up, and drive the API with a script meanwhile.
- `browser_file_upload` only accepts files under the repo (`.playwright-mcp/` is git-ignored). Copy test files there instead of using the scratchpad, and delete them afterwards.
- A text input with a `<datalist>` shows up as a `combobox` in snapshots, not a textbox: type into it, don't wait for a listbox.
- What the sandbox can't do: `mount_webdav` (Finder mounts), `.claude/settings.json` edits, and turning on Claude's PR monitor. Say so and leave them to the maintainer; don't work around the guard.
- Colima only shares `$HOME` (and `/tmp/colima`) with its VM. An app whose compose file bind-mounts a file from a data dir under macOS `/var/folders/...` or `/private/tmp` gets an empty *directory* created at the source, and the app crash-loops (SearXNG: `settings.yml is a directory`). Put the data dir, and `athena.catalog.smoke --out`, under `$HOME` when testing catalog apps with `files/`.
