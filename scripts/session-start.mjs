#!/usr/bin/env node
// Claude Code SessionStart hook (.claude/settings.json): whatever this prints is added to
// the session's context. It puts docs/STATUS.md there (AGENTS.md step 1, without a tool
// call) and reports missing machine setup (scripts/agents-setup.mjs --check --quiet).
// Always exits 0: a hook failure must never block a session.
import { spawnSync } from "node:child_process"
import { readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const root = join(dirname(fileURLToPath(import.meta.url)), "..")
try {
  const status = readFileSync(join(root, "docs", "STATUS.md"), "utf8")
  console.log("docs/STATUS.md, loaded at session start (no need to read it again):\n")
  console.log(status)
} catch {}
const setup = spawnSync(process.execPath, [join(root, "scripts", "agents-setup.mjs"), "--check", "--quiet"], { encoding: "utf8" })
if (setup.stdout?.trim()) console.log(setup.stdout.trim())
process.exit(0)
