# Gotchas: Server (Python)

- `athena openapi` must not create the real data dir. It builds the app against a temp dir, and a test enforces this.
- SQLite runs in WAL mode. A test that reads `athena.db` directly misses rows still in `athena.db-wal`, so query through SQLAlchemy.
- `ruff --fix` can delete an import it thinks is unused when the name is shadowed. Use an aliased import.
- Mutable class attributes trip RUF012. Use tuples or `ClassVar`.
- The capability status type is `Status` (`athena/platform/`), not `CapabilityStatus`. <!-- docs-check: ignore -->
- Open SSE streams never end on their own. uvicorn's `timeout_graceful_shutdown` (5 s, `SHUTDOWN_GRACE_SECONDS` in `cli.py`) is what lets the service stop with a dashboard open. Keep it.
- Every compose command needs `env=store.env(name)`, not only deploy. Stop, restart and remove once failed for apps using `${ATHENA_APP_DATA}`.
- Compose YAML is YAML 1.2: `yes` is a string, not `true`. The CasaOS importer parses it the same way (one of 182 apps broke on this).
- Terminal: don't use `pty.fork()` or ptyprocess in the multi-threaded server; they can deadlock (Python 3.12+ warns). Use the stdlib pty with `Popen(start_new_session=True)` and the `TIOCSCTTY` shim in `athena/terminal/pty.py`.
- `require_user` can't protect WebSockets. The terminal checks the cookie itself and takes the CSRF token in the first message (see the top of `api/terminal.py`).
- wsgidav: a DELETE on a collection whose `delete()` refuses falls back to deleting every member one by one. That emptied a whole location. Refuse such requests in `handle_delete` / `handle_copy` / `handle_move` before wsgidav gets there, and test it.
- Tests that need a CLI to be _absent_ must really hide it from PATH. A test passed on every machine with `docker` and only failed on macOS CI, which has none. Run such tests with the tool removed from PATH.
- The release wheel must include the catalog (`athena/catalog_builtin`) and the web export. Once it shipped without the catalog, and the store was empty. `build-wheel.sh` now fails if either is missing.
