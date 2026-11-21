# Gotchas: Installers and E2E

- Hosted runners can't run Colima's VM (macOS) or WSL2 (Windows), so containers are only checked end to end on Linux in CI.
- For a full Linux check locally on a Mac, use a Lima VM (`limactl start template://ubuntu`, or `template://fedora` for dnf). Docker containers don't run systemd, so they can't test the service.
- Installers take `--wheel <path>` / `-Wheel <path>` so E2E tests the commit, not the last release.
- Recording pacman fixtures under amd64 emulation on Apple Silicon needs `--disable-sandbox` (for recording only).
- There's no `athena service restart`. `athena service install --data-dir <dir> --port <port>` restarts the service on every OS (systemd `restart`, launchd `bootout` + `bootstrap`, Windows stops the interpreter and `/Run`s the task), so the E2E workflow uses it. Pass the same data dir and port the installer used.
- macOS: `launchctl bootout` returns before the agent is gone, and a `bootstrap` right after fails with "Bootstrap failed: 5: Input/output error". Every reinstall over a running agent (upgrades, restarts) hit it, and only the E2E HTTPS step exposed it. `_launchd_bootout` (`service/platforms.py`) waits until `launchctl print` no longer finds the agent.
