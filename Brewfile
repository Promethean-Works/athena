# Everything to work on Athena on macOS (and Linuxbrew): `brew bundle` or scripts/bootstrap.sh.
# Required to build and run
brew "git"
brew "node"
brew "pnpm"
brew "uv"          # also installs the Python 3.13 the server needs, on first `uv sync`
brew "gh"
# Checks that scripts/check.sh runs (a missing one is skipped, or fails under --strict)
brew "gitleaks"
brew "shellcheck"
brew "actionlint"
# Security tooling (/security-audit, scripts/cve-scan.sh)
brew "trivy"
brew "semgrep"
# Containers for apps and container features (optional): Colima is a free Docker engine for macOS
brew "docker"
brew "docker-compose"
brew "colima" if OS.mac?
# Coding agent helper (optional; agents-setup.mjs hooks it in)
brew "rtk"
