# Spec: catalog extras (app files, optional services, Docker host access)

**Status:** Draft · **Milestone:** store/catalog (no milestone yet) · **Design:** `docs/design/` store section, `catalog/README.md`

## Goal

Let a store app ship what bigger self-hosted platforms need beyond one `compose.yaml`: config files, services the admin can switch on at install time, and the host details a container needs to start sibling containers. First consumer: AgenticOS, whose browser and code sandbox are left out of the store app today. Also fixes SearXNG, whose `settings.yml` the user now edits by hand to turn on JSON for AI tools.

For admins who install an app and want the whole thing without writing files or Compose profiles by hand.

## Non-goals

- A RAM or CPU warning on the install page (a separate, smaller change: `min_memory_gb` in `x-athena`, read with `psutil`, which `monitor.py` already uses).
- SSO fields, HTTPS or Traefik variants for apps.
- Per-user editing of the shipped files from the UI (users edit the file on disk, as today).
- Sandboxing the Docker socket. Apps that mount it get a clear warning; they are not made safe.
- Changing CasaOS-imported catalogs.

## Platforms

- **Files and profiles:** pure Compose; identical on Linux, macOS and Windows.
- **Docker socket and same-path workspaces:**
  - Linux: socket at `/var/run/docker.sock`; the Docker group ID comes from `stat` on it.
  - macOS (Docker Desktop, Colima, OrbStack): socket is reachable at the same path; group ID is `0`; a same-path workspace works because the app data folder is shared into the VM.
  - Windows: host paths (`C:\…`) can't be mounted at the same path inside a Linux container. Profiles that need a same-path workspace carry `requires: [same-path-mounts]`; the install form disables them with the reason when the host can't do it.
- Capability: a new `docker-socket` check in the manifest (socket exists and is usable); profiles that mount it declare `requires: [docker-socket]`. The store page shows "Needs Docker access" instead of hiding the app.

## Design

### 1. App files

- **Layout:** `catalog/apps/<id>/files/**` (any depth, text or binary, 256 KB per file, 2 MB per app). Referenced from the compose file with a relative path, `./files/squid.conf`, because Athena writes `compose.yaml` into the app folder and Compose resolves relative paths from the compose file. The same file also works with plain `docker compose`.
- **Install:** the install route copies the files next to the written `compose.yaml` (`<app dir>/files/`). Files are **seeded**: written only if missing, so edits survive restarts and updates. A changed shipped file shows as a note on the app's update screen; it isn't overwritten. (Question 1.)
- **Server:** `CatalogApp`/`CatalogAppVariant` get `files: dict[str, bytes]`, loaded by `catalog/loader.py` (path traversal and symlinks refused, limits enforced, `files/` shared by all variants); `api/store.py` passes them to `deploy_new_app`. `catalog/remote.py` `build()` copies `files/` too, so third-party catalogs can use it. The built-in wheel already bundles `catalog/`.
- **Templating:** none. Shipped files are literal. Anything that varies per install goes through environment variables.
- **First consumers:** SearXNG ships `files/settings.yml` (`use_default_settings`, `json` enabled, a generated-at-first-start secret via `SEARXNG_SECRET`); its note about editing the file goes away. AgenticOS ships `files/squid.conf`.

### 2. Optional services (profiles)

- **Metadata:** `x-athena.profiles` lists switches:

  ```yaml
  x-athena:
    profiles:
      - id: browser
        label: Browser for agents
        description: A real browser agents can drive. Adds about 1 GB of RAM.
        default: false
        requires: []          # capability ids; unmet ones disable the switch
        platforms: [linux/amd64, linux/arm64]   # optional, when narrower than the app
  ```

  The compose file keeps the upstream `profiles: [browser]` on the matching services, so it stays close to the project's own file.
- **Install form:** one checkbox per profile under the fields, with its description and a disabled state plus reason when `requires` or `platforms` aren't met. The chosen ids are written to `.env` as `COMPOSE_PROFILES=browser,sandbox`, which Docker Compose reads on its own, so `docker compose up` by hand behaves the same.
- **Later changes:** toggling a profile on an installed app re-writes `COMPOSE_PROFILES` and redeploys (same path as editing the app's environment today).
- **Platforms:** `image_platforms` computes the app's `platforms` from the default (no-profile) services; each profile's own images are checked against its `platforms` (or the app's). The store hides a profile the host CPU can't run.
- **Smoke test:** `smoke --profiles` starts each app with all its profiles on (and `--variants`-style naming `athena-test-<id>-<profile>`); the weekly workflow runs it.
- **Why not variants:** variants copy the whole file per combination (AgenticOS would need 2^n copies) and can't be combined; profiles are what the upstream project already uses.

### 3. Docker host access

- **New default tokens** in `catalog/loader.py` `resolve_default`: `@docker_gid` (group that owns the Docker socket, `0` where there is no such group) and `@docker_socket` (the socket path the runtime uses: `/var/run/docker.sock`, or the Colima/OrbStack/Podman path the runtime provider reports). Apps use them in a `type: text, advanced: true` field, as `@uid` is used today.
- **Same-path workspace:** apps mount `${ATHENA_APP_DATA}/workspaces:${ATHENA_APP_DATA}/workspaces`. `ATHENA_APP_DATA` is already an absolute host path; the spec just documents the pattern in `catalog/README.md`.
- **Warning:** the loader detects a bind mount of a Docker socket (in the default services or any profile) and sets `grants_docker_access` on the app. The store page and install form show "This app can control every container on this server" with the profile name when it's profile-only. Portainer, Arcane and Dozzle get the badge for free; their copy-pasted `notes` lines can go.
- **First consumer:** AgenticOS profiles `browser` (browser, egress proxy), `sandbox` (`sandboxd`, `requires: [docker-socket, same-path-mounts]`), `objectstore` (MinIO) and `artifacts` (headless Chromium).

### Common

- **Server:** loader, model, `api/store.py` (install + a `GET /api/store/...` field for `profiles`, `files` count and `grants_docker_access`), capability manifest entry, audit entry on install already exists; add the chosen profiles to it. Run `pnpm gen:api`.
- **Web:** install form checkboxes, the warning banner, the disabled-with-reason state. shadcn `Checkbox` and `Alert`; no new dependency.
- **Assistant / MCP:** the install tool already takes the form values; add `profiles`. Installing an app that grants Docker access, or a profile that does, needs approval.
- **Security:** files are read from the built-in catalog or a catalog the admin added; remote archives get the same traversal checks as today plus the size limits. The socket warning is informational; nothing is blocked. Secrets still never appear in shipped files; the loader rejects files that look like they contain a literal secret (same gitleaks rule CI already runs).
- **Dependencies:** none.

## Parts

One PR for the whole feature (maintainer preference); commits follow these parts, and the PR says which are done.

1. **App files:** loader, model, install, `remote.build`, tests; SearXNG consumes it. Verified by unit tests, a real SearXNG install returning JSON.
2. **Profiles:** metadata, `COMPOSE_PROFILES` in `.env`, install form, platform and smoke support, docs in `catalog/README.md`; AgenticOS gets `browser`, `objectstore` and `artifacts` (these need part 1 for the Squid file only). Verified in the browser with `athena-ui-verify`.
3. **Docker host access:** `docker-socket` capability, `@docker_gid` and `@docker_socket`, the warning, AgenticOS `sandbox` profile. Verified on Linux (Lima), macOS (Colima) and a Windows disabled-state check.

## Acceptance checks

- Unit tests: files loaded and copied; traversal, symlink and size limits refused; a second install never overwrites an edited seed file; `.env` carries `COMPOSE_PROFILES`; unmet `requires` rejects the profile with a 422; socket detection.
- `ATHENA_DOCKER_TESTS=1 pytest tests/test_catalog.py -k compose` runs `docker compose config` with every profile on.
- Smoke with profiles on a machine with 8 GB or more (Colima's 2 GB default kills AgenticOS; see the PR for the catalog batch).
- Browser: install SearXNG and request `/search?q=test&format=json`; install AgenticOS with the browser profile and see its containers; the warning and disabled states render at phone width and in dark mode.
- Failure cases: a profile whose image doesn't exist for the host CPU; Docker socket missing; a catalog archive with a `files/../x` entry.

## Open questions

1. **Seed or managed files?** Recommendation: seed (written once). Managed files would silently overwrite user edits on update; the update screen mentions changed shipped files instead.
2. **Inline `configs: content:` instead of a `files/` folder?** Recommendation: the folder. Inline content needs Compose 2.23 or newer (Podman's compose and older Docker packages lack it), can't hold binary files, and makes long configs hard to read in YAML.
3. **Does the runtime layer honour `COMPOSE_PROFILES` in `.env`?** Needs a check of the runtime providers (Docker, Podman) before part 2; recommendation: pass `--profile` flags explicitly from the stored value if either ignores the variable.
4. **Windows: allow the sandbox profile under WSL2?** Recommendation: not in this feature; disabled with a reason until the Windows container runtime reports a Linux-path workspace.
5. **Should profile toggles be allowed after install?** Recommendation: yes (part 2); it's what admins will want after trying the browser.
