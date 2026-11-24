#!/usr/bin/env node
// One guard for every agent's file tools, so the rules live in one place:
//   - secret files (keys, .env, the dev data dir) are never read;
//   - CHANGELOG.md and version.txt are never edited (release-please owns them);
//   - nothing is edited in the base checkout (AGENTS.md → Git workflow: it stays on a
//     clean main; every task works in its own worktree).
//
// Each agent calls it its own native way:
//   Claude Code   PreToolUse hook (.claude/settings.json):  node scripts/agent-guard.mjs claude
//   Hermes Agent  pre_tool_call shell hook (~/.hermes/config.yaml, set up by agents-setup.mjs):
//                 node <base checkout>/scripts/agent-guard.mjs hermes
//   oh-my-pi      .omp/extensions/athena.ts imports verdict() from this file
// Both hooks pass a JSON event on stdin ({tool_name, tool_input, cwd}); the answer goes to
// stdout in that agent's format. Any error lets the call through, and both hooks are set to
// fail open: the guard must never break a session (each agent's deny rules, the pre-commit
// hook and GitHub's branch protection still apply).
//
// Edit in the base checkout on purpose (the maintainer, by hand): ATHENA_ALLOW_BASE_EDIT=1.
//   node scripts/agent-guard.mjs --self-test     checks the path rules (CI runs it)
import { execFileSync } from "node:child_process"
import { existsSync, readFileSync } from "node:fs"
import { basename, dirname, isAbsolute, resolve } from "node:path"
import { fileURLToPath } from "node:url"

// Also used by scripts/agents-sync.mjs for each agent's native deny rules.
export const SECRET_GLOBS = [".env", ".env.*", "secret.key", ".credentials*", "*.pem", "id_rsa*", "id_ed25519*"]
export const SECRET_DIRS = [".dev-data"]
export const PROTECTED_FILES = ["CHANGELOG.md", "version.txt"]
// Shell commands no agent may run (glob patterns, `*` = anything). main is protected on
// GitHub too; these stop the attempt before it reaches the remote.
export const DENIED_COMMANDS = [
  "git push * main",
  "git push * HEAD:main",
  "git push * +main",
  "git push * :main",
  "git push --force*",
  "git push * --force*",
  "git push -f*",
  "git push * -f*",
]

const READ_TOOLS = new Set(["Read", "read_file", "read", "grep", "glob", "find", "search_files"])
const EDIT_TOOLS = new Set(["Edit", "Write", "NotebookEdit", "MultiEdit", "write_file", "patch", "edit", "write", "ast_edit"])

const globToRegExp = (g) => new RegExp("^" + g.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".") + "$")
const secretNames = SECRET_GLOBS.map(globToRegExp)

export function isSecret(path) {
  if (typeof path !== "string" || /^[a-z][a-z0-9+.-]*:\/\//i.test(path)) return false // URLs, internal URIs
  const parts = path.replace(/:\d[\d,+-]*$/, "").split(/[\\/]+/).filter(Boolean)
  return parts.some((p) => SECRET_DIRS.includes(p)) || secretNames.some((r) => r.test(parts.at(-1) ?? ""))
}

// Paths named in a V4A/apply_patch style patch (Hermes `patch` mode=patch, omp's `edit`).
export function patchPaths(text) {
  if (typeof text !== "string") return []
  return [...text.matchAll(/^\*\*\* (?:(?:Edit|Update|Add|Delete) File|Move to): (.+?)(?: all)?\s*$/gm)].map((m) => m[1])
}

// Every path a tool call touches, whatever the agent calls the field.
export function toolPaths(input) {
  if (!input || typeof input !== "object") return []
  const paths = [input.file_path, input.notebook_path, input.path, ...(Array.isArray(input.paths) ? input.paths : [])]
  for (const key of ["patch", "input"]) paths.push(...patchPaths(input[key]))
  return paths.filter((p) => typeof p === "string" && p)
}

// Without GIT_* variables: inside a git hook (pre-push runs --self-test) GIT_DIR would
// point every lookup at the hook's repository instead of the path's.
const gitEnv = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith("GIT_")))
const git = (cwd, ...args) => execFileSync("git", args, { cwd, env: gitEnv, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim()
const HERE = dirname(fileURLToPath(import.meta.url))
let ownCommonDir
const commonDir = (dir) => git(dir, "rev-parse", "--path-format=absolute", "--git-common-dir")

// "base" = the checkout that owns .git (not a linked worktree) of this repository;
// "worktree" = a linked worktree of it; null = another repository or no repository.
export function checkoutKind(file) {
  let dir = dirname(file)
  while (!existsSync(dir) && dirname(dir) !== dir) dir = dirname(dir)
  try {
    ownCommonDir ??= commonDir(HERE)
    if (commonDir(dir) !== ownCommonDir) return null
    return git(dir, "rev-parse", "--path-format=absolute", "--git-dir") === ownCommonDir ? "base" : "worktree"
  } catch {
    return null
  }
}

// Why the call must be refused, or null to let it through.
export function verdict(tool, input, cwd = process.cwd()) {
  const paths = toolPaths(input).map((p) => (isAbsolute(p) ? p : resolve(cwd, p.replace(/^~(?=$|[\\/])/, process.env.HOME ?? process.env.USERPROFILE ?? "~"))))
  if (READ_TOOLS.has(tool)) {
    const secret = paths.find(isSecret)
    return secret ? `Athena: ${secret} is a secret file (keys, .env, .dev-data); agents may not read it.` : null
  }
  if (!EDIT_TOOLS.has(tool)) return null
  for (const p of paths) {
    const kind = checkoutKind(p)
    if (!kind) continue
    if (PROTECTED_FILES.includes(basename(p))) return `Athena: ${basename(p)} is written by release-please only; don't edit it.`
    if (kind === "base" && process.env.ATHENA_ALLOW_BASE_EDIT !== "1") {
      return `Athena: ${p} is in the base checkout, which stays on a clean main. Work in your own worktree (AGENTS.md → Git workflow), e.g. scripts/new-worktree.sh <type>/<topic>.`
    }
  }
  return null
}

function selfTest() {
  const cases = [
    [isSecret("apps/server/.env"), true],
    [isSecret("/x/.dev-data/athena.db"), true],
    [isSecret("a/b/id_ed25519.pub"), true],
    [isSecret(".env.example"), true],
    [isSecret("apps/server/settings.py"), false],
    [isSecret("https://example.com/.env"), false],
    [patchPaths("*** Begin Patch\n*** Update File: a/b.py\n@@\n*** Add File: c.md\n*** End Patch").join(","), "a/b.py,c.md"],
    [toolPaths({ file_path: "x" }).join(), "x"],
    [toolPaths({ paths: ["a", "b"] }).join(), "a,b"],
    [verdict("Read", { file_path: "/tmp/.env" }) !== null, true],
    [verdict("Edit", { file_path: "/tmp/not-a-repo/CHANGELOG.md" }), null],
    [verdict("Edit", { file_path: resolve(HERE, "..", "CHANGELOG.md") }) !== null, true],
    [verdict("Bash", { command: "ls" }), null],
  ]
  const failed = cases.filter(([got, want]) => got !== want)
  for (const [got, want] of failed) console.error(`agent-guard self-test: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`)
  console.log(failed.length ? "" : `agent-guard: ${cases.length} self-test cases pass`)
  process.exit(failed.length ? 1 : 0)
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const mode = process.argv[2]
  if (mode === "--self-test") selfTest()
  try {
    const event = JSON.parse(readFileSync(0, "utf8") || "{}")
    const reason = verdict(event.tool_name, event.tool_input, event.cwd)
    if (reason && mode === "claude") {
      console.log(JSON.stringify({ hookSpecificOutput: { hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: reason } }))
    } else if (reason && mode === "hermes") {
      console.log(JSON.stringify({ decision: "block", reason }))
    }
  } catch {}
  process.exit(0)
}
