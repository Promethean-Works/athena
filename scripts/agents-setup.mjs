#!/usr/bin/env node
// Sets up this machine's coding agents for Athena, or checks that they are.
//
// Everything in the repo (instructions, skills, MCP servers, subagents, rules) needs no
// setup: each agent reads it from the checkout. This script handles the rest, which
// lives in the user's home folder and is lost when an agent is reinstalled:
//   - the git hooks (repo-local, but not committed);
//   - RTK, which shortens shell output before the agent reads it, hooked into each agent;
//   - TokenEconomizer, which learns repo facts, prunes unused tools and guards loops;
//   - Hermes: trusting this repo's skills and registering the MCP servers;
//   - optionally (--with-models), the maintainer's model/provider choices from
//     .agents/user/ (never keys: those come from the environment or the agent's login).
//
//   node scripts/agents-setup.mjs              show what's missing and offer to fix it
//   node scripts/agents-setup.mjs --check      report only; exit 1 if something is missing
//   node scripts/agents-setup.mjs --check --quiet
//                                              print only what's missing, always exit 0
//                                              (Claude Code's SessionStart hook)
//   node scripts/agents-setup.mjs --dry-run    print the commands a fix would run
//   node scripts/agents-setup.mjs --yes        fix without asking (agents: ask the user first)
//   --with-models                              also apply .agents/user/*.models.json
//   --only <a,b>                               only these groups: repo, tools, claude,
//                                              opencode, hermes, omp
//
// Only agents whose CLI is on PATH are set up. Fixes are idempotent and merge into
// existing configs; nothing is overwritten.
import { execFileSync, spawnSync } from "node:child_process"
import { existsSync, lstatSync, mkdirSync, readFileSync, readlinkSync, realpathSync, symlinkSync, copyFileSync, writeFileSync } from "node:fs"
import { homedir } from "node:os"
import { delimiter, dirname, join, resolve } from "node:path"
import { createInterface } from "node:readline/promises"
import { fileURLToPath } from "node:url"

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..")
const HOME = homedir()
const WIN = process.platform === "win32"
const argv = process.argv.slice(2)
const flag = (f) => argv.includes(f)
const CHECK = flag("--check")
const QUIET = flag("--quiet")
const DRY = flag("--dry-run")
const YES = flag("--yes") || flag("-y")
const MODELS = flag("--with-models")
const ONLY = argv.includes("--only") ? new Set(argv[argv.indexOf("--only") + 1].split(",")) : null

// The main checkout (not a worktree): tools that trust a folder should trust this one.
const MAIN_ROOT = (() => {
  try {
    const common = execFileSync("git", ["rev-parse", "--path-format=absolute", "--git-common-dir"], { cwd: ROOT, encoding: "utf8" }).trim()
    return dirname(common)
  } catch {
    return ROOT
  }
})()

// --- helpers ------------------------------------------------------------------------

const which = (cmd) => {
  const exts = WIN ? (process.env.PATHEXT ?? ".EXE;.CMD;.BAT").split(";") : [""]
  for (const dir of (process.env.PATH ?? "").split(delimiter)) {
    for (const ext of exts) {
      const p = join(dir, cmd + ext)
      if (dir && existsSync(p)) return p
    }
  }
  return null
}
const run = (cmd, args, opts = {}) => spawnSync(cmd, args, { encoding: "utf8", shell: WIN, ...opts })
const readJson = (p) => {
  try {
    return JSON.parse(readFileSync(p, "utf8"))
  } catch {
    return null
  }
}
const writeJson = (p, data) => {
  mkdirSync(dirname(p), { recursive: true })
  writeFileSync(p, JSON.stringify(data, null, 2) + "\n")
}
const readText = (p) => (existsSync(p) ? readFileSync(p, "utf8") : "")
// Deep merge that never replaces an existing scalar and appends missing array items.
function merge(into, from) {
  for (const [k, v] of Object.entries(from)) {
    if (Array.isArray(v)) {
      into[k] = Array.isArray(into[k]) ? into[k] : []
      for (const item of v) if (!into[k].some((x) => JSON.stringify(x) === JSON.stringify(item))) into[k].push(item)
    } else if (v && typeof v === "object") {
      into[k] = into[k] && typeof into[k] === "object" ? into[k] : {}
      merge(into[k], v)
    } else if (!(k in into)) {
      into[k] = v
    }
  }
  return into
}
const linkOrCopy = (target, path) => {
  mkdirSync(dirname(path), { recursive: true })
  try {
    symlinkSync(target, path, WIN && lstatSync(target).isDirectory() ? "junction" : undefined)
  } catch (e) {
    if (!WIN || lstatSync(target).isDirectory()) throw e
    copyFileSync(target, path) // Windows without Developer Mode: a copy (re-run after updates)
  }
}
const exists = (p) => {
  try {
    lstatSync(p)
    return true
  } catch {
    return false
  }
}

// Python 3.10+ for TokenEconomizer. macOS's python3 is 3.9.
function findPython() {
  const candidates = [process.env.TE_PYTHON, readJson(join(HOME, ".claude/settings.json"))?.env?.TE_PYTHON]
  const uv = which("uv") && run("uv", ["python", "find", ">=3.10"])
  if (uv?.status === 0) candidates.push(uv.stdout.trim())
  for (const v of ["3.13", "3.12", "3.11", "3.10"]) candidates.push(which(`python${v}`))
  candidates.push(which("python3"), which("python"))
  for (const c of candidates.filter(Boolean)) {
    const r = run(c, ["-c", "import sys; print(sys.version_info >= (3, 10))"], { shell: false })
    if (r.status === 0 && r.stdout.trim() === "True") return c
  }
  return null
}

// Where TokenEconomizer is cloned: $TOKENECONOMIZER_DIR, an existing link, or a default.
function teDir() {
  if (process.env.TOKENECONOMIZER_DIR) return process.env.TOKENECONOMIZER_DIR
  for (const link of [join(HOME, ".config/opencode/plugins/tokeneconomizer.ts"), join(HOME, ".hermes/plugins/tokeneconomizer")]) {
    try {
      const real = realpathSync(link)
      return real.endsWith(".ts") ? resolve(dirname(real), "../..") : resolve(real, "../..")
    } catch {}
  }
  return join(HOME, ".local/share/TokenEconomizer")
}

// --- steps --------------------------------------------------------------------------
// Each step: { group, title, ok(): boolean, fix?: { show: string, run(): void } | null,
// manual?: string (what the person has to do), optional?: boolean (not counted as missing) }

const TE = teDir()
const claudeSettingsPath = join(HOME, ".claude/settings.json")
const claudeSettings = () => readJson(claudeSettingsPath) ?? {}
const hermesConfig = () => readText(join(HOME, ".hermes/config.yaml"))
// The `plugins:` block's `enabled:` list in ~/.hermes/config.yaml (no YAML parser needed).
const hermesPluginEnabled = (name) => {
  const block = hermesConfig().match(/^plugins:\n((?:[ \t]+.*\n|\n)*)/m)?.[1] ?? ""
  const enabled = block.match(/^ {2}enabled:\n((?: {4}- .*\n)*)/m)?.[1] ?? ""
  return enabled.split("\n").some((l) => l.trim() === `- ${name}`)
}
const mcpServers = Object.keys(readJson(join(ROOT, ".mcp.json"))?.mcpServers ?? {})
const rtkHook = readJson(join(ROOT, ".agents/user/claude.settings.json"))
const has = { claude: !!which("claude"), opencode: !!which("opencode"), hermes: !!which("hermes"), omp: !!which("omp") }
let python = null
const pythonOnce = () => (python ??= findPython() ?? "")

const steps = [
  {
    group: "repo",
    title: "git hooks (core.hooksPath = .githooks)",
    ok: () => run("git", ["config", "core.hooksPath"], { cwd: ROOT }).stdout.trim() === ".githooks",
    fix: { show: "git config core.hooksPath .githooks", run: () => run("git", ["config", "core.hooksPath", ".githooks"], { cwd: ROOT }) },
  },
  {
    group: "repo",
    title: ".claude/skills links to .agents/skills",
    ok: () => exists(join(ROOT, ".claude/skills")) && lstatSync(join(ROOT, ".claude/skills")).isSymbolicLink() && readlinkSync(join(ROOT, ".claude/skills")).replace(/\\/g, "/") === "../.agents/skills",
    manual: "On Windows: turn on Developer Mode, then `git config core.symlinks true` and check the repo out again.",
  },
  {
    group: "repo",
    title: "GitHub CLI signed in (gh auth status)",
    quietSkip: true, // may hit the network; not checked in the SessionStart hook
    ok: () => !!which("gh") && run("gh", ["auth", "status"]).status === 0,
    manual: "Install the GitHub CLI and run `gh auth login`.",
  },
  {
    group: "tools",
    title: "RTK on PATH",
    ok: () => !!which("rtk"),
    fix: which("brew")
      ? { show: "brew install rtk", run: () => run("brew", ["install", "rtk"], { stdio: "inherit" }) }
      : which("cargo")
        ? { show: "cargo install --git https://github.com/rtk-ai/rtk", run: () => run("cargo", ["install", "--git", "https://github.com/rtk-ai/rtk"], { stdio: "inherit" }) }
        : null,
    manual: "Install RTK: https://github.com/rtk-ai/rtk#installation",
  },
  {
    group: "tools",
    title: "gitleaks on PATH (secret scan in the pre-commit hook)",
    ok: () => !!which("gitleaks"),
    fix: which("brew") ? { show: "brew install gitleaks", run: () => run("brew", ["install", "gitleaks"], { stdio: "inherit" }) } : null,
    manual: "Install gitleaks: https://github.com/gitleaks/gitleaks#installing",
  },
  {
    group: "tools",
    title: "Python 3.10+ for TokenEconomizer",
    ok: () => !!pythonOnce(),
    fix: which("uv") ? { show: "uv python install 3.12", run: () => { run("uv", ["python", "install", "3.12"], { stdio: "inherit" }); python = null } } : null,
    manual: "Install Python 3.10 or newer (or uv).",
  },
  {
    group: "tools",
    title: `TokenEconomizer cloned (${TE})`,
    ok: () => existsSync(join(TE, "plugin")),
    fix: { show: `git clone https://github.com/microsoft/TokenEconomizer.git "${TE}"`, run: () => run("git", ["clone", "https://github.com/microsoft/TokenEconomizer.git", TE], { stdio: "inherit", shell: false }) },
  },

  // Claude Code
  {
    group: "claude",
    when: has.claude,
    title: "Claude Code: RTK hook in ~/.claude/settings.json",
    ok: () => JSON.stringify(claudeSettings().hooks ?? {}).includes("rtk hook claude"),
    fix: { show: `merge .agents/user/claude.settings.json into ${claudeSettingsPath}`, run: () => writeJson(claudeSettingsPath, merge(claudeSettings(), { hooks: rtkHook.hooks })) },
  },
  {
    group: "claude",
    when: has.claude,
    title: "Claude Code: TokenEconomizer plugin installed",
    ok: () => readText(join(HOME, ".claude/plugins/installed_plugins.json")).includes("tokeneconomizer@"),
    fix: {
      show: `claude plugin marketplace add "${TE}" && claude plugin install tokeneconomizer@tokeneconomizer`,
      run: () => {
        run("claude", ["plugin", "marketplace", "add", TE], { stdio: "inherit" })
        run("claude", ["plugin", "install", "tokeneconomizer@tokeneconomizer"], { stdio: "inherit" })
      },
    },
  },
  {
    group: "claude",
    when: has.claude,
    title: "Claude Code: TE_PYTHON points at Python 3.10+",
    ok: () => {
      const p = claudeSettings().env?.TE_PYTHON
      return !!p && existsSync(p)
    },
    fix: { show: "set env.TE_PYTHON in ~/.claude/settings.json to the Python 3.10+ found", run: () => pythonOnce() && writeJson(claudeSettingsPath, merge(claudeSettings(), { env: { TE_PYTHON: pythonOnce() } })) },
  },

  // OpenCode
  {
    group: "opencode",
    when: has.opencode,
    title: "OpenCode: RTK plugin (~/.config/opencode/plugins/rtk.ts)",
    ok: () => exists(join(HOME, ".config/opencode/plugins/rtk.ts")),
    fix: { show: "rtk init -g --opencode --hook-only --no-patch", run: () => run("rtk", ["init", "-g", "--opencode", "--hook-only", "--no-patch"], { stdio: "inherit" }) },
  },
  {
    group: "opencode",
    when: has.opencode,
    title: "OpenCode: TokenEconomizer plugin linked",
    ok: () => exists(join(HOME, ".config/opencode/plugins/tokeneconomizer.ts")),
    fix: { show: `link ${TE}/plugin/opencode/tokeneconomizer.ts into ~/.config/opencode/plugins/`, run: () => linkOrCopy(join(TE, "plugin/opencode/tokeneconomizer.ts"), join(HOME, ".config/opencode/plugins/tokeneconomizer.ts")) },
  },
  {
    group: "opencode",
    when: has.opencode && MODELS,
    title: "OpenCode: models from .agents/user/opencode.models.json",
    ok: () => {
      const want = readJson(join(ROOT, ".agents/user/opencode.models.json")) ?? {}
      const have = readJson(join(HOME, ".config/opencode/opencode.json")) ?? {}
      return Object.keys(want.provider ?? {}).every((p) => have.provider?.[p]) && (!want.model || !!have.model)
    },
    fix: {
      show: "merge .agents/user/opencode.models.json into ~/.config/opencode/opencode.json (existing values kept)",
      run: () => {
        const p = join(HOME, ".config/opencode/opencode.json")
        const { $comment, ...want } = readJson(join(ROOT, ".agents/user/opencode.models.json"))
        writeJson(p, merge(readJson(p) ?? { $schema: "https://opencode.ai/config.json" }, want))
      },
    },
  },

  // Hermes Agent
  {
    group: "hermes",
    when: has.hermes,
    title: `Hermes: repo skills trusted and MCP servers registered (${mcpServers.join(", ")})`,
    ok: () => {
      const c = hermesConfig()
      return c.includes(`- ${MAIN_ROOT}`) && mcpServers.every((n) => new RegExp(`^  ${n}:`, "m").test(c))
    },
    fix: { show: "node scripts/agents-sync.mjs --hermes", run: () => run(process.execPath, [join(ROOT, "scripts/agents-sync.mjs"), "--hermes"], { stdio: "inherit", cwd: MAIN_ROOT, shell: false }) },
  },
  {
    group: "hermes",
    when: has.hermes,
    title: "Hermes: RTK plugin (rtk-rewrite) installed and enabled",
    ok: () => exists(join(HOME, ".hermes/plugins/rtk-rewrite")) && hermesPluginEnabled("rtk-rewrite"),
    fix: {
      show: "rtk init --agent hermes --hook-only --no-patch && hermes plugins enable rtk-rewrite",
      run: () => {
        if (!exists(join(HOME, ".hermes/plugins/rtk-rewrite"))) run("rtk", ["init", "--agent", "hermes", "--hook-only", "--no-patch"], { stdio: "inherit" })
        run("hermes", ["plugins", "enable", "rtk-rewrite"], { stdio: "inherit" })
      },
    },
  },
  {
    group: "hermes",
    when: has.hermes,
    title: "Hermes: TokenEconomizer plugin linked and enabled",
    ok: () => exists(join(HOME, ".hermes/plugins/tokeneconomizer")) && hermesPluginEnabled("tokeneconomizer"),
    fix: {
      show: `link ${TE}/plugin/hermes to ~/.hermes/plugins/tokeneconomizer && hermes plugins enable tokeneconomizer`,
      run: () => {
        if (!exists(join(HOME, ".hermes/plugins/tokeneconomizer"))) linkOrCopy(join(TE, "plugin/hermes"), join(HOME, ".hermes/plugins/tokeneconomizer"))
        run("hermes", ["plugins", "enable", "tokeneconomizer"], { stdio: "inherit" })
      },
    },
  },
  {
    group: "hermes",
    when: has.hermes && MODELS,
    title: "Hermes: model from .agents/user/hermes.models.json",
    ok: () => {
      const want = readJson(join(ROOT, ".agents/user/hermes.models.json")) ?? {}
      return Object.entries(want).filter(([k]) => k !== "$comment").every(([k, v]) => hermesConfig().includes(`${k.split(".").at(-1)}: ${v}`))
    },
    fix: {
      show: "hermes config set <key> <value> for each entry of .agents/user/hermes.models.json",
      run: () => {
        for (const [k, v] of Object.entries(readJson(join(ROOT, ".agents/user/hermes.models.json")))) if (k !== "$comment") run("hermes", ["config", "set", k, String(v)], { stdio: "inherit" })
      },
    },
  },

  // oh-my-pi reads the repo's AGENTS.md, skills, commands and .mcp.json by itself.
  {
    group: "omp",
    when: has.omp,
    title: "oh-my-pi: RTK extension (~/.omp/agent/extensions/rtk.ts)",
    ok: () => exists(join(HOME, ".omp/agent/extensions/rtk.ts")),
    fix: { show: "rtk init -g --agent omp --hook-only --no-patch", run: () => run("rtk", ["init", "-g", "--agent", "omp", "--hook-only", "--no-patch"], { stdio: "inherit" }) },
  },
].filter((s) => s.when !== false && (!ONLY || ONLY.has(s.group)) && !(QUIET && s.quietSkip))

// --- run ----------------------------------------------------------------------------

const missing = []
for (const s of steps) {
  let ok = false
  try {
    ok = s.ok()
  } catch {}
  if (!ok) missing.push(s)
  if (!QUIET) console.log(`${ok ? "ok  " : s.optional ? "info" : "MISS"} [${s.group}] ${s.title}`)
}
const required = missing.filter((s) => !s.optional)

if (QUIET) {
  if (required.length) {
    console.log(`Athena agent setup: ${required.length} item(s) missing on this machine:`)
    for (const s of required) console.log(`  - ${s.title}`)
    console.log("Tell the maintainer and offer to run `node scripts/agents-setup.mjs --yes` (it installs tools and edits configs in the home folder, so ask first).")
  }
  process.exit(0)
}
if (!missing.length) {
  console.log("\nEverything is set up.")
  process.exit(0)
}
const fixable = missing.filter((s) => s.fix)
const manual = missing.filter((s) => !s.fix)
if (fixable.length) {
  console.log(`\n${CHECK || DRY ? "Would run" : "Fixes"}:`)
  for (const s of fixable) console.log(`  ${s.fix.show}`)
}
if (manual.length) {
  console.log("\nTo do by hand:")
  for (const s of manual) console.log(`  [${s.group}] ${s.manual ?? s.title}`)
}
if (CHECK || DRY) process.exit(required.length ? 1 : 0)
if (!fixable.length) process.exit(1)

if (!YES) {
  if (!process.stdin.isTTY) {
    console.error("\nNot a terminal: re-run with --yes to apply.")
    process.exit(1)
  }
  const rl = createInterface({ input: process.stdin, output: process.stdout })
  const answer = await rl.question(`\nApply ${fixable.length} fix(es)? [y/N] `)
  rl.close()
  if (!/^y/i.test(answer)) process.exit(1)
}
let failed = 0
for (const s of fixable) {
  console.log(`\n→ ${s.title}`)
  try {
    s.fix.run()
  } catch (e) {
    console.error(`  failed: ${e.message}`)
  }
  let ok = false
  try {
    ok = s.ok()
  } catch {}
  if (!ok) {
    failed++
    console.error(`  still missing: ${s.manual ?? "see the output above"}`)
  }
}
console.log(failed ? `\n${failed} fix(es) didn't take; see above.` : "\nDone. Restart your agents so they load new hooks and plugins (Hermes: /reload-mcp and restart).")
process.exit(failed || manual.some((s) => !s.optional) ? 1 : 0)
