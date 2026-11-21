# athena-server

The Athena backend: a FastAPI app, packaged as `athena-server`, that serves the API and the built web UI.

## Development

```bash
uv sync
uv run athena serve --reload        # API on http://localhost:8420
uv run pytest
uv run ruff check && uv run ruff format --check
```

Run the web app at the same time with `pnpm dev` from the repo root. It proxies `/api` to this server.

## CLI

| Command | What it does |
|---|---|
| `athena serve [--host --port --data-dir --reload]` | Run the server. `--host`/`--port` override `server.host`/`server.port` in `<data-dir>/athena.json` |
| `athena openapi [--output FILE]` | Print or write the OpenAPI schema, which `packages/api-client` is generated from |
| `athena service install --data-dir DIR [--port N] [--dry-run]` | Register Athena to start automatically: systemd (Linux, root), launchd agent (macOS), Scheduled Task at logon (Windows). `--port` is saved as `server.port` in athena.json, not in the service |
| `athena config path\|show\|check\|reset SECTION [--data-dir DIR]` | Where athena.json is; the server settings and where each comes from (flag, env, file, default); check it like `serve` does; put one section back to its defaults |
| `athena https status\|off [--data-dir DIR]` | Show HTTPS settings, or turn HTTPS off for the next start |
| `athena service uninstall [--dry-run]` | Remove that registration |
| `athena service status` | Show whether the service is registered and running |
| `athena admin reset-password [--data-dir DIR] [--username NAME] [--password-stdin]` | Recover a forgotten password: prompts twice (or reads stdin), then signs that account out everywhere. Run it as the service's user (`sudo` on Linux) |

The install scripts in `scripts/` call `athena service install` after installing the wheel.
