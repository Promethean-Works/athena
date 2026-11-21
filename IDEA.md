Athena: a self-hosted home server control panel (CasaOS-style) for Linux, macOS and Windows, with an app store, files, terminal, automation and a built-in AI assistant. Agent rules live in AGENTS.md; current work in docs/STATUS.md.

- Ship the first release: finish the tunnel fixes (ngrok token, auto-start on boot, the `configure` detector action)
- Every store app installs and serves on amd64 and arm64 (catalog smoke `--all`)
- Raspberry Pi phase 1: cloudflared download, arch-aware store, 32-bit install check, arm64 CI
- Verify on real hosts what's only unit-tested: Windows terminal, non-apt package managers, real rclone remotes
- AI assistant stage 3: browser tool (blocked upstream) and durable-execution crash/resume
