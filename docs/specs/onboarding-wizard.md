# Spec: onboarding wizard

**Status:** Approved (2026-11-27) · **Milestone:** M9 (first-run), after M8 · **Design:** `docs/design/platform.md` (container runtime per OS), `docs/design/frontend.md` (`/setup`)

## Goal

On first start the admin is walked through the minimal settings Athena needs to be useful: account, language, a working container runtime, file locations and network access, then the optional AI provider. The same wizard can be re-run later from Settings and from the terminal with `athena onboard`, for a changed machine or a reset setting. For admins of a fresh server on any of the three OSes.

## Non-goals

- Multi-user setup (one admin, see `docs/design/scope.md`).
- Docker Desktop and other closed-source runtimes. Open-source only (`docs/design/licenses.md`).
- Windows containers (Linux containers only).
- Replacing Settings pages: each step writes the same settings those pages edit.
- Installing a runtime without the admin's click (no silent installs).

## Today

`/setup` already has: choose (create account | restore from backup) → account → optional AI step (`AiSetupStep`, #M7 C). `GET /api/auth/status` says `setup_required` until the admin exists. There is no completion flag, no CLI wizard, and runtime install is documented as out of scope (`docs/design/scope.md`: "One-click runtime install on every OS"; `platform.md`: Windows "detect only"). **This spec changes that decision for the container runtime** (see Open questions 1).

## Platforms

Runtime choices per OS, each a provider in `containers/` behind the `containers` capability (detect → `ready | stopped | missing`, actions `start`/`install`). The wizard lists only what the host supports and marks what's detected.

| OS | Offered (install via the host package manager when there is one) |
|---|---|
| Linux | Docker Engine (`docker-ce`/distro `docker.io`), Podman, **Kiri** (`.deb`/`.rpm` from runkiri.com, Apache-2.0, Rust, runs on the kernel) |
| macOS | Colima (brew), Podman machine (brew), **Kiri** (`brew install --cask libracoder/kiri/kiri`), OrbStack is not offered (closed source) |
| Windows | Docker Engine in WSL2, Podman machine, Rancher Desktop (dockerd mode), **Kiri** (`.msi`, WSL2) |

Kiri speaks the Docker Engine API and creates a `kiri` Docker context; detection asks `kiri doctor --json` / `docker --context kiri version` and uses the context's endpoint, `kiri start` to start. "Other new Rust runtimes": the only cross-OS Docker-API one found is Kiri. youki and Pelagos are OCI/Linux-only low-level runtimes with no Docker API, so Athena's compose-based apps can't use them. Apple's `container` is Swift and has no Docker API. They are left out unless the maintainer names one (Open questions 2).

Capability ids stay `containers`; `provider` gains `kiri`. If nothing can be installed (no package manager, no privilege), the wizard shows the manual steps already in `platform.md`.

## Design

- **Server**
  - `onboarding` section in `athena.json` (`settings_file.py`): `completed_at`, `version` (wizard version, so a later release can offer new steps). Missing = not completed; existing installs that already have an admin count as completed (no migration needed: absent section + existing user = completed).
  - Routes (`api/onboarding.py`, admin, `operation_id`s `getOnboarding`, `completeOnboarding`, `resetOnboarding`): state = step list with per-step status (`done | todo | skipped | unsupported`), computed from real settings, not stored per step.
  - Language, locations and network steps reuse the existing settings routes (`/api/settings`, locations, system settings, HTTPS). No new storage.
  - Runtime step: `GET /api/containers/runtimes` (candidates for this host from the manifest and package managers), `POST /api/containers/runtimes/{id}/install` (a job through the package manager provider; needs privilege handling like other installs; audited `containers.runtime_install`), `start` exists already. A new provider class per runtime in `containers/providers.py`, pure parsers with fixtures.
  - Public `GET /api/auth/status` gains `onboarding_required` only for the signed-in admin; `setup_required` unchanged.
- **CLI** `athena onboard [--data-dir D] [--yes] [--language L] [--port N] [--bind ADDR] [--runtime ID] [--location NAME=PATH] [--no-install]`
  - Interactive prompts (stdlib or `typer`-style already used in `cli.py`; no new dependency) for the same steps; with the server stopped it writes `athena.json`/DB directly (like `config` and `admin reset-password`); if the server is running it warns and tells the admin to stop it or use the web wizard (calling the API from the CLI is out of scope).
  - Creates the admin if none exists (password prompt, not an argument), otherwise skips. Re-runnable: shows current value as the default. `--yes` takes defaults and flags only, never installs a runtime unless `--runtime` is given.
  - `athena onboard --reset` clears `onboarding.completed_at` so the web wizard opens again.
- **Web**
  - `/setup` becomes a stepper: account → language → container runtime → locations → network → AI (skippable) → done. Each step is skippable except the account; the dashboard shows an "Finish setup" card while steps are `todo`.
  - Settings → General gets "Run setup again" (opens `/onboarding/`, the same stepper without the account/restore step, behind the session).
  - Runtime step: radio list of candidates (detected first, recommended one marked), Install opens `<JobDialog>`, then Start, then re-detect; every state has an empty/error message. i18n keys in all locale files (see `docs/specs/i18n.md`).
- **Assistant / MCP:** none (installing a runtime is a host change; not exposed to the assistant in this spec).
- **Security:** wizard routes are admin-only; install commands use argument lists and a fixed allowlist of package ids/URLs per runtime (never a user-supplied one); downloaded `.deb/.rpm/.msi` are fetched over HTTPS from the pinned vendor URL and verified by the vendor's checksum/signature where published; network step refuses `0.0.0.0` without HTTPS or a warning acknowledgement.
- **Dependencies:** none new. Kiri (Apache-2.0) is recorded in `docs/design/licenses.md` as an optional runtime Athena installs but does not bundle.

## Parts

1. Backbone — `onboarding` settings section, routes, `athena onboard` for account/language/locations/network, `--reset`, tests. No runtime install yet.
2. Web stepper — `/setup` stepper, "Run setup again", dashboard card, i18n. Browser-verified (`athena-ui-verify`).
3. Runtimes — provider classes and fixtures, the install job per OS, Kiri, runtime step in web and CLI, design docs updated (`platform.md`, `scope.md`, `decisions.md`).
4. Real-host checks — Lima Linux VM and Windows E2E (`athena-host-test`).

Per the maintainer's rule, one PR for the whole feature unless they ask otherwise.

## Acceptance checks

- Server tests: state computed per step on fresh vs existing install; reset; CLI on a temp data dir (interactive via piped stdin, `--yes`, re-run keeps values); each runtime provider's detect/install plan against fixtures on fake Linux, macOS and Windows probes; routes need admin.
- Browser: fresh data dir through every step, skip paths, re-run from Settings, 390 px, dark mode, runtime install with a fake provider (never install on the host).
- Real hosts: Linux VM install of Docker Engine and Kiri; macOS Colima/Kiri; Windows E2E detection. Anything not run is listed as not verified.
- Failure cases: install job fails, no privilege, no package manager, runtime installs but won't start, port in use.

## Open questions

1. Reverse the "no runtime install" decision in `scope.md`/`platform.md`? — **Decided:** yes, on an explicit click in the wizard **and in Settings** (and `--runtime` on the CLI), never automatic.
2. Which "other new Rust runtimes" to include besides Kiri? — **Decided: check more.** Checked: FerroCrate (Rust, Docker API, alpha, Linux daemon, 1 star, unsigned) is detected and listed as "experimental" with manual steps only; Maclet (macOS, no Docker API), youki and Pelagos (OCI-only), Apple `container` (Swift) are left out.
3. Kiri is under six months old (13.9k stars, Apache-2.0): offer it as a normal option or mark it "new"? — recommendation: offer it, labelled "new", not the default; defaults stay Docker Engine / Colima / WSL Docker.
4. CLI with the server running — recommendation: require it stopped (direct writes), warn otherwise.
5. Install on Linux when Docker is not in distro repos — recommendation: use the distro package (`docker.io`/`docker`), not Docker's apt repo, to avoid adding third-party repos silently.
