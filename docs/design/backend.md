# 6. Backend layout and API

```
apps/server/
  pyproject.toml            # uv project; entry point `athena`
  src/athena/
    main.py                 # create_app(): routers, app.state, static mount, lifespan
                            # (detection, monitor, scheduler, MCP, models.dev refresh)
    cli.py, config.py       # the CLI; settings (platformdirs data dir, ATHENA_* env)
    jobs.py                 # in-memory job runner, SSE events, cancel
    audit.py, monitor.py, system_settings.py, crypto.py, logging_setup.py
    api/                    # one thin router per area
    auth/                   # argon2 passwords, sessions, CSRF (deps.py)
    db/                     # models.py (SQLModel), engine.py, migrations/ (Alembic)
    platform/               # probe.py, detect.py, capabilities.py, store.py
    containers/             # runtime.py (Docker-compatible CLI per runtime), service.py
    apps/                   # store.py (compose apps on disk), docker_run.py (converter)
    catalog/                # model.py (x-athena), loader.py, registry.py, remote.py, casaos.py
    packages/               # base.py, linux.py, apps.py (brew, flatpak, snap), windows.py
    terminal/               # pty.py (POSIX pty and ConPTY), shells.py
    files/                  # paths.py, locations.py, ops.py, shares.py, smb.py, webdav.py
    cloud/                  # rclone.py (sidecar), remotes.py, transfers.py
    assistant/              # kinds.py, models_dev.py, providers.py, chat.py, tools.py,
                            # actions.py, and the harness capabilities (§4.5)
    automation/             # service.py: triggers, job runs, scheduler
    mcp/                    # server.py (tools), auth.py (session or bearer)
    tunnel/                 # base.py, cloudflare.py, tailscale.py, ngrok.py
    service/                # athena service install per OS (platforms.py, plan.py)
  tests/                    # pytest; parsers pinned by recorded CLI fixtures
catalog/                    # built-in app catalog
```

API surface (from the routers; the generated `packages/api-client/openapi.json` is the exact list):

```
GET  /api/health
GET  /api/auth/status   POST /api/auth/{setup|login|logout|password}
GET  /api/system/info   GET /api/system/stats   GET /api/system/stats/stream (SSE)
GET  /api/system/capabilities   POST /api/system/capabilities/refresh
GET  /api/jobs/{id}   GET /api/jobs/{id}/events (SSE)   POST /api/jobs/{id}/cancel
POST /api/containers/runtime/start
GET  /api/containers   GET/DELETE /api/containers/{ref}   POST …/{ref}/{start|stop|restart}
GET  /api/containers/{ref}/logs   GET …/{ref}/logs/stream (SSE)
GET/POST /api/apps   GET/PUT/DELETE /api/apps/{name}   PUT …/{name}/env   POST …/{name}/{action}
POST /api/apps/convert (docker run → compose)   POST /api/apps/validate
GET  /api/store/categories   GET /api/store/apps   GET …/apps/{catalog}/{app_id}   POST …/install
GET/POST /api/store/catalogs   POST …/{id}/refresh   DELETE …/{id}
GET/PUT /api/settings/{appearance|system|ai}
GET  /api/packages   GET …/{manager}/{search|installed|upgradable}
POST /api/packages/{manager}/{install|uninstall|upgrade|refresh} (jobs)
WS   /api/terminal/ws?target=host|container:{ref}
GET/POST /api/files/locations   PUT/DELETE …/{id}
GET  /api/files/{list|download}   GET/PUT /api/files/text
POST /api/files/{folder|rename|delete|transfer}   POST/DELETE /api/files/upload
GET/POST /api/shares   PUT/DELETE /api/shares/{id}   GET/POST /api/shares/smb   DELETE …/smb/{id}
GET  /api/public/shares/{token}[/list|/download]   POST …/unlock   POST/DELETE …/upload
GET/PUT /api/webdav   POST /api/webdav/password   /dav/… (WebDAV)   /s/{token} (share page)
GET  /api/cloud/providers   GET/POST /api/cloud/remotes   GET/PUT/DELETE …/{name}   POST …/{name}/answer
GET  /api/cloud/files/{list|download}   POST …/files/{folder|rename|delete}   POST/DELETE …/files/upload
POST /api/cloud/transfer   POST /api/cloud/sync/preview   POST /api/cloud/sync
GET  /api/assistant/kinds   POST /api/assistant/kinds/refresh
GET/POST /api/assistant/providers   PUT/DELETE …/{id}   POST …/{id}/test   GET …/{id}/models
GET  /api/assistant/models   GET /api/assistant/integrations/kinds
GET/POST /api/assistant/integrations   PUT/DELETE …/{id}
GET/POST /api/assistant/conversations   GET/PATCH/DELETE …/{id}
POST …/conversations/{id}/messages (SSE)   POST …/{id}/approvals (SSE)   POST …/{id}/stop
GET/POST /api/automation/triggers   GET/PATCH/DELETE …/{id}   POST …/triggers/validate-action
GET  /api/automation/jobs   GET /api/automation/jobs/{run_id}
POST /api/automation/webhook/{token} (public)
GET  /api/tunnel/status   POST /api/tunnel/{start|stop|install}   PUT /api/tunnel/{config|service}
     /api/mcp (MCP streamable HTTP)
```
