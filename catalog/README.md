# Athena built-in catalog

Apps offered in Athena's store (about 200). Each app is a folder with a `compose.yaml`, plus optional variant files (see [Variants](#variants)):

```
apps/<id>/compose.yaml
apps/<id>/compose.<slug>.yaml   # optional variants
```

`<id>` is lowercase letters, digits and dashes. The file is a normal Docker Compose file with an `x-athena` block describing the app and its install form:

```yaml
x-athena:
  title: Jellyfin
  description: Stream your movies, shows and music to any device.
  category: media        # media, files, productivity, development, home, network,
                         # security, monitoring, downloads, utilities
  icon: https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/svg/jellyfin.svg
  homepage: https://jellyfin.org
  web_port: WEB_PORT     # env key (or a number) that the "Open" button uses
  notes: >-              # optional, shown on the store page
    First-run instructions.
  tagline: Your own streaming service for movies, shows and music.  # card subtitle
  tags: [Movies, TV, Music]      # up to 6 small chips on the card
  license: GPL-2.0               # shown on the app page
  popular: true                  # featured in the store's front-page carousel
  features:                      # up to 8 bullets, "What you get" on the app page
    - Stream to TVs, phones, browsers and DLNA devices
    - Hardware transcoding when the host supports it
  screenshots:                   # up to 6 http(s) URLs; the first is the card cover
    - https://example.com/screenshot.png
  env:                   # one form field per entry; answers are written to .env
    - key: WEB_PORT
      label: Web port
      type: port         # text, password, port, path, number, boolean, select
      default: "8096"
      description: Port the web UI listens on on this server.  # optional help text under the field
    - key: DB_TYPE
      label: Database
      type: select
      options: [sqlite, mysql]  # required for type: select (non-empty)
      default: sqlite
    - key: MEDIA_PATH
      label: Media folder
      type: path
      default: "@app_data/media"
    - key: TZ
      label: Timezone
      default: "@timezone"
      advanced: true     # collapsed under "Advanced" in the form
    - key: DB_PASSWORD
      label: Database password
      type: password
      generate: secret   # random value when left empty
    - key: SMTP_HOST
      label: Mail server
      required: false    # default true: an empty value is refused unless generated

services:
  jellyfin:
    image: jellyfin/jellyfin:10.10
    ports: ["${WEB_PORT}:8096"]
    volumes:
      - ${ATHENA_APP_DATA}/config:/config
      - ${MEDIA_PATH}:/media:ro
```

### Variants

An app folder may hold several compose files: `compose.yaml` is the default variant and
each `compose.<slug>.yaml` sibling is another installable variant of the same app
(e.g. `compose.postgres.yaml`). Every variant file is a complete x-athena compose doc
with its own `env` form fields; the store lists them as a variant picker on the app's
install page, and the chosen variant's compose file is deployed. App-level metadata
(title, category, icon, …) comes from `compose.yaml`. The picker's name is
`x-athena.variant.label` in the variant file (`variant: {label: PostgreSQL}`), or the
slug title-cased when it's missing.

## Rules

- **Standard interpolation only.** Reference form values as `${KEY}`. Every `${…}` must be a declared `env` key or `ATHENA_APP_DATA`, which is the app's own data folder on the server. Athena writes the answers to `.env` next to `compose.yaml`, so the file works with plain `docker compose` too.
- **Default tokens:**
  - `@timezone` is the host's timezone.
  - `@uid` and `@gid` are the server user's IDs (1000 when Athena runs as root).
  - `@app_data` and `@app_data/<sub>` are paths inside the app's data folder.
- **Pin image tags** to a release, a major version, or an official channel (`stable`). Check that they exist for `linux/amd64` and `linux/arm64`.
- **Open-source apps only.** Use web ports that don't clash with other catalog apps, so several apps can run side by side.
- **Icons** come from [dashboard-icons](https://github.com/homarr-labs/dashboard-icons) (Apache-2.0).
- **Screenshots** should come from the project's own repository or documentation site (a raw GitHub URL is fine). Keep them under a few hundred KB, and check that the URL answers 200. The store falls back to the app icon when a screenshot can't load, so a missing or rotted URL is not fatal.
- **`tagline`, `tags`, `features`, `license` and `popular`** are optional but make the store page useful. `popular: true` puts the app in the front-page carousel (it autoplays), so use it for the handful of apps a home server actually starts with.

## Checks

`apps/server/tests/test_catalog.py` loads every app, checks its metadata and variables, and fills the form with defaults. When a container engine is available (`ATHENA_DOCKER_TESTS=1`, which is on in Linux CI), it also runs `docker compose config` on each app.

The catalog is bundled into the server wheel as `athena/catalog_builtin`.
