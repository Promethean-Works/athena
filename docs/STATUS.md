# Athena status

_Shared handoff log for every coding agent. Update it at the end of each session (see AGENTS.md → Handoff)._

**Current milestone:** M7, the AI assistant (§4.5). Parts A (providers and chat, #37) and B (actions with approval) are done; part C (polish) follows.

## Done

Finished work is in `docs/HISTORY.md` (read it only when you need a feature's background). When you finish something, add a short bullet there with the PR number and take it out of In progress below.

## In progress

- Not yet verified for real: the Windows terminal (ConPTY plus PowerShell) beyond CI's pty tests, and the container shell through Docker in WSL.
- Not yet verified for real: the other Linux system managers' install/uninstall (dnf, pacman, zypper, apk; apt is done, see below) and every Windows manager (hand-written fixtures; CI runs choco/winget reads on Windows).
- E2E install testing (branch `ci/e2e-install`): the `E2E` workflow runs the real installers with a wheel built from the commit, on Ubuntu, macOS and Windows runners, then `scripts/e2e/smoke.py` (Playwright) and an uninstall check. New: `scripts/build-wheel.sh` (now also used by `release.yml`), and `--wheel` / `-Wheel` in the installers. Verified locally on 2026-11-14:
  - macOS: the smoke test against the wheel on :8421 passes.
  - Ubuntu 24.04 arm64 in a Lima VM: `sudo install.sh --wheel` installed Docker Engine (get.docker.com), uv, Python 3.13 and the systemd unit; the service ran as root; detection found docker-engine, apt, snap, terminal.host, files and webdav; the smoke test passed; apt install/uninstall of `sl` through the API worked (checked with dpkg); `--uninstall --purge` left no unit, data, `/opt/athena` or binary, and the port was closed.
  - First CI run: Ubuntu and macOS (launchd) passed everything. Windows Server 2025: `install.ps1 -Wheel`, the Scheduled Task, detection (docker-engine, winget, choco, conpty, files, webdav) and the whole smoke test passed, **including the ConPTY terminal in the browser**. The uninstall failed: `schtasks /End` only kills the venv launcher `pythonw.exe`, and its child (the real interpreter) kept the port and locked the install folder. Upgrades had the same bug. Fixed: install and uninstall now also stop `pythonw.exe -m athena serve` processes and wait for them. Confirmed on the re-run (917d140): all three OSes pass install, smoke, uninstall and the port-closed check. The `-Wheel` lint warning needed a `SuppressMessageAttribute`, because the rule doesn't see uses inside functions.

## Next

M7 part C, what's left: the assistant side sheet on every page, then the setup-wizard step.

M7 part D, the rest of pydantic-ai-harness (maintainer's request, design §4.5 Parts): next is stage 1, robustness (`repair_tool_arguments`, `detect_loops`, `tool_output_limits`, `compaction`, `prompt_injection_defender`); then agent features; extras with outside services; sandboxes and other workspaces; hosted integrations; durable execution and operations; the coding stack.

Later (cloud): mounts (FUSE; `rclone nfsmount` on macOS), scheduled or saved syncs, encrypting the rclone config with the OS keyring (§7), uploads to a remote without staging the whole file on the server first, Range requests for seeking in remote videos, and stopping an orphaned `rclone rcd` if Athena is killed (`SIGKILL` leaves it running).

Later (shares): a size limit for upload links, per-file audit of WebDAV changes, locks that survive a restart, WebDAV for more than one account.

Later (files): folder uploads (drag a folder), resumable uploads across page reloads, search, and SMB/NFS shares.

Later: switches for package installs and the assistant's shell in system settings (§7), next to the terminal's. Proxying the terminal WebSocket in `next dev` hasn't been checked; use the release build to work on it.

Later: a CI check that `themes.css` matches the registry (needs network; run `pnpm gen:theme` after shadcn upgrades for now), and switching shadcn styles at runtime (§5.4).

Later: auto-refreshing catalogs on a schedule, stripping missing host devices from imported apps, and Docker Hub login for pulls (rate limits).

Later: per-container stats, verifying temperatures on a real Linux host, importing existing compose projects not created by Athena, and Windows path translation for WSL bind mounts.

## Open questions

- None. (The first AI provider question was settled in M7: no default; Ollama is offered when detected.)

## Blockers

- The release PR needs a `RELEASE_PLEASE_TOKEN` repo secret (a fine-grained PAT with contents + pull-requests write on this repo). Without it, CI doesn't run on release-please PRs, and they can only be merged with admin bypass.
