# Gotchas: Installers and E2E

- Hosted runners can't run Colima's VM (macOS) or WSL2 (Windows), so containers are only checked end to end on Linux in CI.
- For a full Linux check locally on a Mac, use a Lima VM (`limactl start template://ubuntu`, or `template://fedora` for dnf). Docker containers don't run systemd, so they can't test the service.
- Installers take `--wheel <path>` / `-Wheel <path>` so E2E tests the commit, not the last release.
- Recording pacman fixtures under amd64 emulation on Apple Silicon needs `--disable-sandbox` (for recording only).
