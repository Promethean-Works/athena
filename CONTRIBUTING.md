# Contributing to Athena

Thanks for helping out! This guide covers how changes get into Athena. Set up your machine with [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md), read [docs/design/README.md](docs/design/README.md) for the architecture and [docs/STATUS.md](docs/STATUS.md) for what's being worked on.

## Workflow

`main` is protected. Nobody pushes to it directly, maintainers included. Every change goes through a branch and a pull request.

1. **Branch from an up-to-date `main`, in its own worktree** (agents must; humans are encouraged to):
   ```bash
   git fetch origin
   git worktree add ../athena-install-form -b feat/app-store-install-form origin/main
   cd ../athena-install-form
   ```
   `scripts/new-worktree.sh <type>/<topic>` does the same (creates `../athena-<topic>` from `origin/main`). Branch names are `<type>/<short-description>`, using the same types as commits (below).
2. **Commit** in small, focused steps. Individual commit messages are free-form, because the PR is squashed.
3. **Check before pushing.** Run `scripts/check.sh` (the same checks as CI). Turn on the git hooks once per clone with `git config core.hooksPath .githooks` (required for agents): pre-commit refuses commits on `main` or in the base checkout, and pre-push runs the parts of `scripts/check.sh` the push touches.
   - Skip once: `git commit --no-verify` or `ATHENA_ALLOW_MAIN_COMMIT=1 git commit …` (emergencies only), and `git push --no-verify` or `ATHENA_SKIP_CHECKS=1 git push`.
4. **Open a pull request** against `main`. Use the template and fill in the testing section.
5. **CI must pass**, and all review conversations must be resolved.
6. **Squash-merge.** The PR title becomes the commit on `main`, and the branch is deleted automatically.

## PR titles: Conventional Commits

PR titles are checked by CI and drive versioning and the changelog:

```
<type>(<optional scope>): <description>
```

| Type | Use for | Version bump |
|---|---|---|
| `feat` | A new user-facing feature | minor |
| `fix` | A bug fix | patch |
| `perf` | A performance improvement | patch |
| `docs` | Documentation only | none |
| `refactor` | Code change that doesn't fix a bug or add a feature | none |
| `test` | Tests only | none |
| `build` | Build system or dependencies | none |
| `ci` | CI configuration | none |
| `chore` | Anything else | none |
| `revert` | Reverts a previous change | patch |

Common scopes: `web`, `ui`, `server`, `containers`, `packages`, `store`, `files`, `cloud`, `terminal`, `assistant`, `install`, `agents`.

Add `!` after the type (`feat!: …`) or a `BREAKING CHANGE:` footer for breaking changes.

## Releases

[release-please](https://github.com/googleapis/release-please) keeps a release PR open that collects merged changes. Merging that PR tags a version, publishes a GitHub release with the changelog, and attaches the install scripts and packages.

## Cross-platform rules

Athena runs on Linux, macOS and Windows. Any change that touches the host (containers, package managers, files, terminal, services) must:

- go through a platform provider and capability (see the `athena-platform-feature` skill in `.agents/skills/`);
- be tested on every OS it claims to support, either in CI or manually. List the OSes in the PR;
- use open-source dependencies only, recorded in [docs/design/licenses.md](docs/design/licenses.md).

### Testing a real install on another OS

- **CI:** the `E2E` workflow installs a wheel built from your branch with the real installers on Ubuntu, macOS and Windows, then drives the UI. It runs by itself on PRs that touch the installers or the service code. To run it on any branch: `gh workflow run e2e.yml --ref <branch>`.
- **Linux on a Mac or Linux machine**, in a [Lima](https://lima-vm.io) VM with systemd:

  ```bash
  limactl start --name athena-ubuntu --tty=false template://ubuntu-24.04   # or template://fedora
  scripts/build-wheel.sh                                                 # dist/athena_server-*.whl
  limactl shell athena-ubuntu -- sudo bash "$PWD/scripts/install.sh" --wheel "$PWD"/dist/athena_server-*.whl
  # Lima forwards the VM's :8420 to localhost:8420 (stop any local Athena on 8420 first).
  uv run --with playwright==1.65.2 playwright install chromium               # once
  uv run scripts/e2e/smoke.py --url http://localhost:8420 --out e2e-out --expect containers
  limactl shell athena-ubuntu -- sudo bash "$PWD/scripts/install.sh" --uninstall --purge
  limactl delete -f athena-ubuntu
  ```

- **Windows:** a Windows 11 VM (UTM or Parallels on a Mac) with OpenSSH Server turned on. Copy the wheel over and run `install.ps1 -Wheel <path>`. Docker in WSL2 needs nested virtualization, so on Apple Silicon test it on a real x64 PC.

## AI coding agents

AI-assisted contributions are welcome. Agents must follow [AGENTS.md](AGENTS.md), which covers the same workflow plus the shared skills, MCP servers and handoff notes in `docs/STATUS.md`.

## Code of conduct

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
