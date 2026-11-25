#!/usr/bin/env node
// Generates every agent's native config from one source: MCP servers from .mcp.json, the
// guard lists from scripts/agent-guard.mjs, and the subagents, commands and area rules below.
//
//   node scripts/agents-sync.mjs           write the generated files (see GENERATED below)
//   node scripts/agents-sync.mjs --check   exit 1 if any is out of date or orphaned (for CI)
//   node scripts/agents-sync.mjs --hermes  configure Hermes (user level, ~/.hermes/config.yaml,
//                                          through its CLI): trust the repo's skills, register
//                                          missing MCP servers, and merge in the guard hook,
//                                          command denies, worktree skills dir and /next-style
//                                          aliases
//   node scripts/agents-sync.mjs --hermes-print
//                                          only print the mcp_servers block for ~/.hermes/config.yaml
//
// Hermes Agent has no project-level config, so --hermes changes the user's file through the
// official CLI: it adds what's missing and never removes the user's own entries.
//
// Token budget: OpenCode and Hermes put MCP tool definitions in every request (Claude Code
// loads them on demand). Playwright alone is ~21k characters, so OpenCode only gives it to
// a `ui-verify` subagent, and Hermes leaves out tools Athena never uses. The same subagent
// is written for Claude Code (which needs no tool scoping) so it can run on a cheaper model.

import { readFileSync, writeFileSync, existsSync, mkdirSync, readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { DENIED_COMMANDS, PROTECTED_FILES, SECRET_DIRS, SECRET_GLOBS } from "./agent-guard.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
// The base checkout, even when this runs in a linked worktree (user-level config points there).
const mainRoot = (() => {
  const r = spawnSync("git", ["rev-parse", "--path-format=absolute", "--git-common-dir"], { cwd: root, encoding: "utf8" });
  return r.status === 0 ? dirname(r.stdout.trim()) : root;
})();
const args = new Set(process.argv.slice(2));

const servers = JSON.parse(readFileSync(join(root, ".mcp.json"), "utf8")).mcpServers ?? {};

// Tools each server has that no Athena workflow uses (Hermes `tools.exclude`).
const UNUSED_TOOLS = {
  playwright: ["browser_drag", "browser_drop", "browser_find", "browser_run_code_unsafe"],
  "next-devtools": ["browser_eval"], // the playwright server covers it
};

// Servers OpenCode hides from the main agent and gives only to one subagent.
const OPENCODE_SUBAGENT_ONLY = {
  playwright: {
    agent: "ui-verify",
    description:
      "Verifies an Athena UI or API change in a real browser (release build, Playwright). Use after changing apps/web or an API the UI calls.",
    claudeModel: "sonnet", // many small, repetitive browser steps; an alias, so always valid
    ompModel: "@smol", // oh-my-pi's cheap-model role (falls back to the default model)
    skill: "athena-ui-verify",
    task: "Report what you verified, what you couldn't and why, and any bugs you found.",
  },
};
// Secret files no agent may read, files only release-please writes, and shell commands
// no agent may run: the lists live in scripts/agent-guard.mjs (which is also the hook that
// enforces them where an agent has no native rule). Claude Code: `Read`/`Edit`/`Bash` deny
// rules merged into .claude/settings.json; OpenCode: `read`/`edit`/`shell` deny rules (its
// `*` also matches `/`); oh-my-pi: bash patterns plus the extension; Hermes: --hermes.
const claudeGuardDenies = [
  ...SECRET_GLOBS.map((g) => `Read(**/${g})`),
  ...SECRET_DIRS.map((d) => `Read(./${d}/**)`),
  ...PROTECTED_FILES.map((f) => `Edit(**/${f})`),
  ...DENIED_COMMANDS.map((c) => `Bash(${c})`),
];
const anyDir = (g) => (g.startsWith("*") ? [g] : [g, `*/${g}`]);
const openCodeGuardRules = [
  ...SECRET_GLOBS.flatMap(anyDir).map((r) => ({ action: "read", resource: r, effect: "deny" })),
  ...SECRET_DIRS.flatMap((d) => [`${d}/*`, `*/${d}/*`]).map((r) => ({ action: "read", resource: r, effect: "deny" })),
  ...PROTECTED_FILES.flatMap(anyDir).map((r) => ({ action: "edit", resource: r, effect: "deny" })),
  ...DENIED_COMMANDS.map((c) => ({ action: "shell", resource: c, effect: "deny" })),
];

// OpenCode names MCP tools <server>_<tool>, with unsupported characters turned into _.
const openCodeToolGlob = (server) => `${server.replace(/[^A-Za-z0-9_]/g, "_")}_*`;

// OpenCode 2.x config shape: { mcp: { servers: { <name>: {...} } } }
function toOpenCode(s) {
  if (s.url) {
    return { type: "remote", url: s.url, ...(s.headers && { headers: s.headers }) };
  }
  return {
    type: "local",
    command: [s.command, ...(s.args ?? [])],
    ...(s.env && { environment: s.env }),
  };
}

// Subagents: the MCP-scoped ones above plus SUBAGENTS, written for Claude Code
// (.claude/agents/), OpenCode (opencode.json agents) and oh-my-pi
// (.omp/agents/; `omp: false` leaves a subagent out there, so omp's bundled one of that
// name is used instead).
// Claude Code and OpenCode also have a built-in explorer (Explore / explore) for
// read-only searches, so there's no custom one; give it a cheap model per machine.
const SUBAGENTS = {
  reviewer: {
    description:
      "Reviews a diff against Athena's rules (AGENTS.md, the app rules, gotchas) and reports bugs and rule breaks without editing. Use before opening a PR, or when asked to review.",
    claudeModel: "sonnet", // chosen by the maintainer to save usage (was "inherit")
    claudeTools: "Read, Grep, Glob, Bash",
    omp: false, // oh-my-pi uses its bundled `reviewer` (read-only, reviews the diff)
    readOnly: true,
    skill: "athena-review",
    task: "Never edit files. Report findings ordered by severity, each with file:line, why it's wrong and a suggested fix.",
  },
};
// Shared slash commands: thin aliases for project skills, so the procedure lives in one
// place. Claude Code gets .claude/commands/<name>.md, OpenCode a `commands` entry; Hermes
// runs the skills themselves (/athena-next).
const COMMANDS = {
  next: { skill: "athena-next", description: "Read STATUS and propose the next concrete step" },
  "check-prs": { skill: "athena-check-prs", description: "Check open PRs: CI, CodeQL, merges; fix failures" },
  ship: { skill: "athena-ship", description: "Commit, open the PR with auto-merge (never waits for CI)" },
  handoff: { skill: "athena-handoff", description: "Update STATUS, HISTORY and gotchas before ending the session" },
  "review-diff": { skill: "athena-review", description: "Review the current diff against the project rules", agent: "reviewer" },
  orchestrate: { skill: "athena-orchestrate", description: "Take an issue through worker, checks and review (stops before the PR)" },
};
for (const c of Object.values(COMMANDS)) {
  if (!existsSync(join(root, ".agents", "skills", c.skill, "SKILL.md"))) throw new Error(`COMMANDS: skill ${c.skill} doesn't exist`);
}
// A subagent's prompt. Claude Code (`skills:`) and oh-my-pi (`autoload-skills:`) preload the
// skill into the subagent; OpenCode has no such field, so its prompt points at the file.
const subagentPrompt = (a, preloaded) =>
  `Follow the ${a.skill} skill (${preloaded ? "loaded into your context" : `.agents/skills/${a.skill}/SKILL.md`}) exactly. ${a.task}`;
const commandPrompt = (c) =>
  `Use the ${c.skill} skill (.agents/skills/${c.skill}/SKILL.md) and follow it.`;

function yamlValue(v) {
  return JSON.stringify(v); // JSON scalars, arrays and objects are valid YAML flow syntax
}

function toHermesYaml() {
  const lines = ["mcp_servers:"];
  for (const [name, s] of Object.entries(servers)) {
    lines.push(`  ${name}:`);
    if (s.url) {
      lines.push(`    url: ${yamlValue(s.url)}`);
      if (s.headers) lines.push(`    headers: ${yamlValue(s.headers)}`);
    } else {
      lines.push(`    command: ${yamlValue(s.command)}`);
      lines.push(`    args: ${yamlValue(s.args ?? [])}`);
      if (s.env) lines.push(`    env: ${yamlValue(s.env)}`);
    }
    if (UNUSED_TOOLS[name]) lines.push(`    tools: ${yamlValue({ exclude: UNUSED_TOOLS[name] })}`);
  }
  return lines.join("\n");
}

if (args.has("--hermes-print")) {
  console.log("# Merge into ~/.hermes/config.yaml, then run /reload-mcp in Hermes.");
  console.log("# Also run `hermes skills trust` in this repo so .agents/skills loads.");
  console.log(toHermesYaml());
  process.exit(0);
}

if (args.has("--hermes")) {
  const shell = process.platform === "win32"; // hermes is a .cmd/.exe shim on Windows
  // `hermes mcp add` asks "Enable all N tools? [Y/n/select]" and cancels (exit 0) on EOF,
  // so answer "Y" on stdin and verify with `hermes mcp list` afterwards.
  const hermes = (...a) => spawnSync("hermes", a, { cwd: root, encoding: "utf8", shell, input: "Y\n" });
  // Escape every regex metacharacter (including backslash) in the server name.
  const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const isListed = (name) =>
    new RegExp(`^\\s*${escapeRegExp(name)}\\s`, "m").test(hermes("mcp", "list").stdout ?? "");

  if (hermes("--version").status !== 0) {
    console.error("hermes CLI not found on PATH. Install Hermes Agent, or use --hermes-print.");
    process.exit(1);
  }

  const trust = hermes("skills", "trust", root);
  console.log(trust.status === 0 ? "hermes: trusted project skills (.agents/skills)" : trust.stderr);

  let failed = false;
  // `hermes config set` parses JSON lists and objects; setting an unchanged value is a no-op.
  const setKey = (name, key, value) => {
    const r = hermes("config", "set", `mcp_servers.${name}.${key}`, JSON.stringify(value));
    if (r.status !== 0) {
      failed = true;
      console.error(`hermes: failed to set ${name}.${key}:\n${r.stdout}${r.stderr}`);
    }
  };
  const syncKeys = (name, s) => {
    if (!s.url) setKey(name, "args", s.args ?? []);
    if (s.headers) setKey(name, "headers", s.headers);
    if (UNUSED_TOOLS[name]) setKey(name, "tools", { exclude: UNUSED_TOOLS[name] });
  };
  for (const [name, s] of Object.entries(servers)) {
    if (isListed(name)) {
      syncKeys(name, s);
      console.log(`hermes: MCP server "${name}" already configured, args and tool filter synced`);
      continue;
    }
    const cmd = s.url
      ? ["mcp", "add", name, "--url", s.url]
      : [
          "mcp", "add", name, "--command", s.command,
          ...(s.env ? ["--env", ...Object.entries(s.env).map(([k, v]) => `${k}=${v}`)] : []),
          "--args", ...(s.args ?? []),
        ];
    const r = hermes(...cmd);
    if (r.status === 0 && isListed(name)) {
      syncKeys(name, s);
      console.log(`hermes: added MCP server "${name}"`);
    }
    else {
      failed = true;
      console.error(`hermes: failed to add "${name}":\n${r.stdout}${r.stderr}`);
    }
  }
  // Everything below is merged into what the user already has; nothing of theirs is removed.
  const get = (key) => {
    const r = hermes("config", "get", key);
    const text = r.status === 0 ? r.stdout.trim() : "";
    return ["", "null", "None", "{}", "[]", "''"].includes(text) ? "" : text;
  };
  // A YAML block list of plain strings, or null when it's anything else (then we don't touch it).
  const getList = (key) => {
    const lines = get(key).split("\n").filter((l) => l.trim());
    const items = lines.map((l) => {
      const item = l.match(/^\s*-\s+(.*?)\s*$/)?.[1];
      if (item && /^(['"]).*\1$/.test(item)) return item; // quoted string
      return item && !/^[{[]|:(\s|$)|\s#/.test(item) ? item : undefined; // not a mapping, flow or comment
    });
    if (items.some((i) => i === undefined)) return null;
    return items.map((i) => (i.startsWith("'") ? i.slice(1, -1).replaceAll("''", "'") : i.startsWith('"') ? JSON.parse(i) : i));
  };
  const set = (key, value, what) => {
    const r = hermes("config", "set", key, JSON.stringify(value));
    if (r.status === 0) console.log(`hermes: ${what}`);
    else {
      failed = true;
      console.error(`hermes: failed to set ${key}:\n${r.stdout}${r.stderr}`);
    }
  };
  const mergeList = (key, items, what) => {
    const have = getList(key);
    if (!have) {
      console.log(`hermes: ${key} isn't a plain list; add these to it in ~/.hermes/config.yaml by hand:\n${items.map((i) => `  - ${JSON.stringify(i)}`).join("\n")}`);
      return;
    }
    const missing = items.filter((i) => !have.includes(i));
    if (missing.length) set(key, [...have, ...missing], what);
  };
  // Worktrees (`hermes -w`, .worktrees/<name>) are their own project root, which isn't
  // trusted, so they'd get no project skills: the base checkout's skills are read from there.
  mergeList("skills.external_dirs", [join(mainRoot, ".agents", "skills")], "project skills available in worktrees (skills.external_dirs)");
  mergeList("approvals.deny", DENIED_COMMANDS, "denied pushes to main and force pushes (approvals.deny)");
  // The file-tool guard (scripts/agent-guard.mjs): secrets, release files, base checkout.
  const guard = `node ${JSON.stringify(join(mainRoot, "scripts", "agent-guard.mjs"))} hermes`;
  const hooks = get("hooks.pre_tool_call");
  if (!existsSync(join(mainRoot, "scripts", "agent-guard.mjs"))) {
    console.log("hermes: guard hook skipped, the base checkout has no scripts/agent-guard.mjs yet (re-run after it reaches main)");
  } else if (!hooks) {
    set("hooks.pre_tool_call", [{ matcher: "write_file|patch|read_file", command: guard, timeout: 10 }], "guard hook added (hooks.pre_tool_call; approve it once when Hermes asks)");
  } else if (!hooks.includes("agent-guard.mjs")) {
    console.log(`hermes: you have your own pre_tool_call hooks; add this one to hooks.pre_tool_call in ~/.hermes/config.yaml by hand:\n  - matcher: "write_file|patch|read_file"\n    command: ${JSON.stringify(guard)}\n    timeout: 10`);
  }
  // The shared commands as aliases of their skills (/next runs /athena-next).
  for (const [name, c] of Object.entries(COMMANDS)) {
    if (!get(`quick_commands.${name}`)) set(`quick_commands.${name}`, { type: "alias", target: c.skill }, `/${name} runs /${c.skill} (quick_commands)`);
  }
  console.log("Restart Hermes or run /reload-mcp in a running session.");
  process.exit(failed ? 1 : 0);
}

const opencodePath = join(root, "opencode.json");
const existing = existsSync(opencodePath)
  ? JSON.parse(readFileSync(opencodePath, "utf8"))
  : { $schema: "https://opencode.ai/config.json" };

// The generated parts: deny rules for subagent-only servers and the guard rules (rules for
// anything else are kept, in order), the subagents and the commands.
const subagentOnly = Object.entries(OPENCODE_SUBAGENT_ONLY).filter(([n]) => servers[n]);
const generatedActions = new Set(Object.keys(OPENCODE_SUBAGENT_ONLY).map(openCodeToolGlob));
const isGuardRule = (r) => r.effect === "deny" && ["read", "edit", "shell"].includes(r.action);
const permissions = [
  ...(existing.permissions ?? []).filter((r) => !generatedActions.has(r.action) && !isGuardRule(r)),
  ...subagentOnly.map(([n]) => ({ action: openCodeToolGlob(n), resource: "*", effect: "deny" })),
  ...openCodeGuardRules, // last, so a broad allow earlier can't override them
];
const allSubagents = [
  ...subagentOnly.map(([n, a]) => ({
    name: a.agent, ...a, source: "OPENCODE_SUBAGENT_ONLY",
    // Agent rules are appended after the global ones, and the last match wins.
    openCodePermissions: [{ action: openCodeToolGlob(n), resource: "*", effect: "allow" }],
  })),
  ...Object.entries(SUBAGENTS).map(([name, a]) => ({
    name, ...a, source: "SUBAGENTS",
    openCodePermissions: a.readOnly ? [{ action: "edit", resource: "*", effect: "deny" }] : [],
  })),
];
for (const a of allSubagents) {
  if (!existsSync(join(root, ".agents", "skills", a.skill, "SKILL.md"))) throw new Error(`subagent ${a.name}: skill ${a.skill} doesn't exist`);
}

const agents = {};
for (const a of allSubagents) {
  agents[a.name] = {
    description: a.description,
    mode: "subagent",
    system: subagentPrompt(a, false),
    ...(a.openCodePermissions.length && { permissions: a.openCodePermissions }),
  };
}
const commands = {};
for (const [name, c] of Object.entries(COMMANDS)) {
  commands[name] = {
    description: c.description,
    template: `${commandPrompt(c)} $ARGUMENTS`,
    ...(c.agent && { agent: c.agent, subagent: true }),
  };
}

// OpenCode settings that do natively what AGENTS.md asks: STATUS in every session
// (`instructions` load after AGENTS.md), no session sharing (a public link to the
// transcript), and no file watching of build output. Worktrees use OpenCode's default
// location (its data dir), so there's no `worktree` block.
const { worktree: _defaultWorktrees, ...kept } = existing;
const next = {
  ...kept,
  instructions: ["docs/STATUS.md"],
  share: "disabled",
  watcher: { ignore: ["**/node_modules/**", "**/.next/**", "**/.venv/**", "**/.turbo/**", "apps/web/out/**", ".dev-data/**", ".playwright-mcp/**", ".claude/worktrees/**", ".worktrees/**"] },
  mcp: {
    ...existing.mcp,
    servers: Object.fromEntries(Object.entries(servers).map(([n, s]) => [n, toOpenCode(s)])),
  },
  ...(permissions.length && { permissions }),
  ...(Object.keys(agents).length && { agents }),
  commands,
};
const out = JSON.stringify(next, null, 2) + "\n";

const generatedNote = (source) => `<!-- Generated by scripts/agents-sync.mjs from ${source}. Don't edit by hand. -->`;
const claudeAgents = Object.fromEntries(
  allSubagents.map((a) => [
    join(".claude", "agents", `${a.name}.md`),
    [
      "---",
      `name: ${a.name}`,
      `description: ${JSON.stringify(a.description)}`,
      `model: ${a.claudeModel}`,
      ...(a.claudeTools ? [`tools: ${a.claudeTools}`] : []),
      "skills:",
      `  - ${a.skill}`,
      "---",
      "",
      generatedNote(a.source),
      "",
      subagentPrompt(a, true),
      "",
    ].join("\n"),
  ]),
);
// Commands are short aliases for skills (the skills are also /athena-<name> by themselves).
// A command with an agent runs forked in that subagent (`context: fork`).
const claudeCommands = Object.fromEntries(
  Object.entries(COMMANDS).map(([name, c]) => [
    join(".claude", "commands", `${name}.md`),
    [
      "---",
      `description: ${JSON.stringify(c.description)}`,
      ...(c.agent ? ["context: fork", `agent: ${c.agent}`] : []),
      "---",
      "",
      generatedNote("COMMANDS"),
      "",
      commandPrompt(c),
      "",
      "$ARGUMENTS",
      "",
    ].join("\n"),
  ]),
);
// oh-my-pi skips .claude/agents (different frontmatter) and reads only .omp/agents/*.md.
// No model means the session's model; omp gives MCP tools to every agent, so the
// playwright scoping above doesn't apply there. It reads .claude/commands by itself.
const ompAgents = Object.fromEntries(
  allSubagents.filter((a) => a.omp !== false).map((a) => [
    join(".omp", "agents", `${a.name}.md`),
    [
      "---",
      `name: ${a.name}`,
      `description: ${JSON.stringify(a.description)}`,
      ...(a.ompModel ? [`model: ${JSON.stringify(a.ompModel)}`] : []),
      ...(a.ompTools ? ["tools:", ...a.ompTools.map((t) => `  - ${t}`)] : []),
      `autoload-skills: ${a.skill}`,
      "---",
      "",
      generatedNote(a.source),
      "",
      subagentPrompt(a, true),
      "",
    ].join("\n"),
  ]),
);
// .omp/AGENTS.md imports STATUS so it's in every omp session. A native .omp/AGENTS.md
// shadows the root AGENTS.md at the same depth, hence the import of that too.
const ompContext = [
  "<!-- Generated by scripts/agents-sync.mjs. Don't edit by hand. -->",
  "",
  "@../AGENTS.md",
  "",
  "@../docs/STATUS.md",
  "",
].join("\n");
// oh-my-pi project settings (.omp/config.yml) that do natively what AGENTS.md asks for:
// every session in its own worktree (Git workflow step 2), Git Guard (no stash/reset/checkout
// that discards work in the base checkout), the denied commands, and secret redaction before
// anything reaches the model. Per-path rules (secrets, release files, base checkout) are in
// the extension: omp's approval settings are per tool, not per path.
const ompConfig = [
  "# Generated by scripts/agents-sync.mjs. Don't edit by hand.",
  "worktree:",
  "  onStart: create # each session starts in a new linked worktree; rename its branch to <type>/<topic>",
  "secrets:",
  "  enabled: true",
  "bash:",
  "  gitGuard: true",
  "  patterns:",
  ...DENIED_COMMANDS.flatMap((m) => [`    - match: ${JSON.stringify(m)}`, "      approval: deny"]),
  "",
].join("\n");
const ompExtension = `// Generated by scripts/agents-sync.mjs. Don't edit by hand.
// oh-my-pi loads every file in .omp/extensions/ by itself. The rules (secret reads, release
// files, edits in the base checkout) are in scripts/agent-guard.mjs, shared with the
// Claude Code and Hermes hooks.
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
// @ts-ignore: a plain .mjs module, resolved by omp's Bun runtime
import { verdict } from "../../scripts/agent-guard.mjs";

export default function athena(pi: ExtensionAPI) {
  pi.setLabel("Athena");
  pi.on("tool_call", async (event, ctx) => {
    const cwd = (ctx as { cwd?: string } | undefined)?.cwd ?? process.cwd();
    const reason = verdict(event.toolName, event.input, cwd);
    if (reason) return { block: true, reason };
  });
}
`;
// Gotchas that load by themselves when an agent touches matching files: Claude Code rules
// (`paths:`) and oh-my-pi rules (`globs:` + `description:`, listed in its rulebook). Other
// agents follow the AGENTS.md router.
const AREA_RULES = {
  server: ["apps/server/**"],
  web: ["apps/web/**", "packages/ui/**"],
  assistant: ["apps/server/src/athena/assistant/**", "apps/web/components/assistant/**"],
  rclone: ["apps/server/src/athena/cloud/**", "apps/web/components/cloud/**"],
  installers: ["scripts/install.sh", "scripts/install.ps1", "apps/server/src/athena/service/**", ".github/workflows/e2e.yml"],
  "git-ci": [".github/**", ".githooks/**", "scripts/pre-*.sh"],
};
const areaRules = {};
for (const [area, globs] of Object.entries(AREA_RULES)) {
  const gotchas = `docs/agents/gotchas/${area}.md`;
  if (!existsSync(join(root, gotchas))) throw new Error(`AREA_RULES: ${gotchas} doesn't exist`);
  const body = (header) => [header, "", `<!-- Generated by scripts/agents-sync.mjs (AREA_RULES). Don't edit by hand. -->`, "", `Before changing these files, read \`${gotchas}\`: traps that already cost earlier agents time in this area.`, ""].join("\n");
  const list = (key) => [`${key}:`, ...globs.map((g) => `  - ${JSON.stringify(g)}`)];
  areaRules[join(".claude", "rules", `${area}.md`)] = body(["---", ...list("paths"), "---"].join("\n"));
  areaRules[join(".omp", "rules", `${area}.md`)] = body(["---", `description: ${JSON.stringify(`Athena ${area} gotchas: read before changing ${globs.join(", ")}`)}`, ...list("globs"), "---"].join("\n"));
}

// Claude Code project settings: the guard deny rules and the guard hook are managed here.
const claudeSettingsPath = join(root, ".claude", "settings.json");
const claudeSettings = JSON.parse(readFileSync(claudeSettingsPath, "utf8"));
const isGuardDeny = (d) => claudeGuardDenies.includes(d);
const otherDenies = (claudeSettings.permissions?.deny ?? []).filter((d) => !isGuardDeny(d));
const GUARD_HOOK = { matcher: "Read|Grep|Glob|Edit|Write|NotebookEdit|MultiEdit", hooks: [{ type: "command", command: 'node "$CLAUDE_PROJECT_DIR/scripts/agent-guard.mjs" claude' }] };
const otherPreToolUse = (claudeSettings.hooks?.PreToolUse ?? []).filter((h) => !JSON.stringify(h).includes("agent-guard.mjs"));
const claudeSettingsOut = JSON.stringify(
  {
    $schema: "https://json.schemastore.org/claude-code-settings.json",
    ...claudeSettings,
    permissions: { ...claudeSettings.permissions, deny: [...otherDenies, ...claudeGuardDenies] },
    hooks: { ...claudeSettings.hooks, PreToolUse: [...otherPreToolUse, GUARD_HOOK] },
  },
  null,
  2,
) + "\n";

// GENERATED: every file this script owns (fully, or the parts described above).
const outputs = {
  [join(".claude", "settings.json")]: claudeSettingsOut,
  "opencode.json": out,
  ...claudeAgents,
  ...claudeCommands,
  ...ompAgents,
  [join(".omp", "AGENTS.md")]: ompContext,
  [join(".omp", "config.yml")]: ompConfig,
  [join(".omp", "extensions", "athena.ts")]: ompExtension,
  ...areaRules,
};
// Folders whose every file is generated: anything else there is left over from a rename.
const OWNED_DIRS = [join(".claude", "agents"), join(".claude", "commands"), join(".claude", "rules"), join(".omp", "agents"), join(".omp", "rules"), join(".omp", "extensions")];
const orphans = OWNED_DIRS.flatMap((d) => (existsSync(join(root, d)) ? readdirSync(join(root, d)).map((f) => join(d, f)) : [])).filter((f) => !(f in outputs));

if (args.has("--check")) {
  // The guard's and the orchestrator's own rules are checked here too, so CI's sync step covers them.
  for (const script of ["agent-guard.mjs", "orchestrate.mjs"]) {
    const selfTest = spawnSync(process.execPath, [join(root, "scripts", script), "--self-test"], { encoding: "utf8" });
    if (selfTest.status !== 0) {
      console.error(selfTest.stdout + selfTest.stderr);
      process.exit(1);
    }
  }
  const stale = Object.entries(outputs).filter(([file, text]) => {
    const path = join(root, file);
    return !existsSync(path) || readFileSync(path, "utf8") !== text;
  });
  if (stale.length || orphans.length) {
    if (stale.length) console.error(`Out of date: ${stale.map(([f]) => f).join(", ")}. Run: node scripts/agents-sync.mjs`);
    if (orphans.length) console.error(`Not generated any more (delete them): ${orphans.join(", ")}`);
    process.exit(1);
  }
  console.log(`${Object.keys(outputs).length} generated agent files are in sync`);
} else {
  for (const [file, text] of Object.entries(outputs)) {
    mkdirSync(dirname(join(root, file)), { recursive: true });
    writeFileSync(join(root, file), text);
  }
  console.log(`synced ${Object.keys(servers).length} MCP server(s) from .mcp.json to ${Object.keys(outputs).length} files`);
  if (orphans.length) console.log(`Not generated any more, delete them: ${orphans.join(", ")}`);
}
