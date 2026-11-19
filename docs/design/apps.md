# 4.1 Apps and the app store

**App definition format.** A standard `compose.yaml` plus an `x-athena` extension, so any compose file works as a custom app with zero metadata. The full format (every field, rules, checks) is in `catalog/README.md`; in short:

```yaml
x-athena:
  title: Jellyfin
  description: Stream your movies, shows and music to any device.
  category: media
  icon: https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/svg/jellyfin.svg
  web_port: WEB_PORT          # env key (or a number) that "Open" links to
  env:                        # the install form; answers go to .env
    - key: WEB_PORT
      label: Web port
      type: port              # text, password, port, path, number, boolean, select (needs options)
      default: "8096"
    - key: TZ
      label: Timezone
      default: "@timezone"    # tokens: @timezone @uid @gid @app_data[/sub]
      advanced: true
services:
  jellyfin:
    image: jellyfin/jellyfin:10.10
    ports: ["${WEB_PORT}:8096"]
    volumes:
      - ${ATHENA_APP_DATA}/config:/config
```

- **Catalogs** are Git repos or HTTP URLs that contain `apps/<id>/compose.yaml`. Athena ships one built-in catalog, `catalog/` in this repo, with about 200 apps, and users can add more. An app folder can also hold variants (`compose.<slug>.yaml`, e.g. FreshRSS with PostgreSQL), offered as a picker on the install page.
- **CasaOS compatibility.** An importer maps CasaOS `x-casaos` metadata to `x-athena`, so a CasaOS-style store archive can be added as a catalog. The CasaOS AppStore (Apache-2.0) apps are now part of the built-in catalog (#120), so the one-click CasaOS catalog was removed (#121). Umbrel's store is **not** included because its license is non-commercial.
- **Install flow:** render the form from `env`, resolve the default tokens and generated secrets, write `.env` (0600) next to `<data>/apps/<id>/compose.yaml`, then run `compose up -d` as a job and record the app in SQLite.
- **Custom apps:**
  - *Paste or upload compose* → validated, then edited in a CodeMirror editor before deploy.
  - *Import `docker run …`* → a Python parser (shlex plus a flag map, the same idea as `composerize`) turns it into compose that the user reviews.
- **Path portability.** `${ATHENA_APP_DATA}` is the app's own folder under the data dir, which resolves per OS: `/var/lib/athena` on Linux, `~/Library/Application Support/Athena` on macOS (inside Colima's shared mount) and `%LOCALAPPDATA%\Athena` on Windows.
