# Gotchas: Agent environment

- Agent tooling quirks (token budget, MCP tool costs, Hermes's skill scanner, agent files shipped by dependencies) are in `docs/agents/tooling.md`.
- The maintainer's shell is zsh. `echo =====` fails there (`=word` expands to a command path), and unquoted `$VAR` lists don't word-split. Quote or use arrays.
- Claude Code's safety check refuses `rm` with unguarded variables or globs (`rm -rf $S/*`). Use literal paths.
- Several agent sessions run at once, so every task gets its own worktree (`git worktree add ../athena-<topic> -b <branch> origin/main`) and the base checkout stays on `main`. Agents used to follow `git switch -c` in the base checkout from older docs; `scripts/pre-commit.sh` now rejects commits from the base checkout (git-dir equals git-common-dir) to enforce it.
- The machine can be offline (no DNS, even outside the sandbox). `uv run --offline --with <pkg>==<version>` uses uv's cache when the package was installed before.
- `pkill` and `ps` may fail in the sandbox ("Cannot get process list"). Find a server by its port with `lsof -nP -t -iTCP:<port> -sTCP:LISTEN` and `kill` that pid.
- VS Code: `.vscode/launch.json` (debug the server, pytest, Next with Chrome, or both as "Full stack") and `.vscode/tasks.json` (dev, build, release serve, tests, checks, codegen). Data goes to the git-ignored `.dev-data/`.
- Port 8420 may be the maintainer's own Athena. Use 8421 or another spare port.
- Act only on containers, apps and images named `athena-demo-*` / `athena-test-*`. The maintainer's own containers run on the same engine. Leave pulled images unless you know you pulled them, and say which ones are left.
- The pre-push hook runs the web checks when any file under `apps/web` changes, `apps/web/AGENTS.md` included. A docs-only push can then fail on a local web problem. Check that the diff is docs only (`git diff main --name-only`) before using `--no-verify`, and let CI decide.
