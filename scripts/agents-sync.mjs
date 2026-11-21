#!/usr/bin/env node
// Syncs MCP servers from .mcp.json (the single source of truth) to other agents.
//
//   node scripts/agents-sync.mjs           write the generated files (see GENERATED below):
//                                          the "mcp" block of opencode.json, Claude Code
//                                          and oh-my-pi subagents, Codex and Antigravity MCP
//                                          config, and the per-area rules for Claude Code and Copilot
//   node scripts/agents-sync.mjs --check   exit 1 if either is out of date (for CI)
//   node scripts/agents-sync.mjs --hermes  trust this repo's skills in Hermes and register
//                                          any missing MCP servers (via the hermes CLI)
//   node scripts/agents-sync.mjs --hermes-print
//                                          only print the mcp_servers block for ~/.hermes/config.yaml
//
// Hermes Agent only reads MCP servers from its user-level config (~/.hermes/config.yaml),
// so --hermes changes that file through the official CLI: it adds missing servers, then
// brings every server's args and tool filter in line with this repo (other keys, such as
// `enabled`, are left alone).
//
// Token budget: OpenCode and Hermes put MCP tool definitions in every request (Claude Code
// loads them on demand). Playwright alone is ~21k characters, so OpenCode only gives it to
// a `ui-verify` subagent, and Hermes leaves out tools Athena never uses. The same subagent
// is written for Claude Code (which needs no tool scoping) so it can run on a cheaper model.

import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
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
    system:
      "Follow the athena-ui-verify skill (.agents/skills/athena-ui-verify/SKILL.md) exactly. Report what you verified, what you couldn't and why, and any bugs you found.",
  },
};
// Files no agent may read: keys and the dev data dir (which holds secret.key and the
// encrypted provider keys). Claude Code: `Read(...)` deny rules merged into
// .claude/settings.json; OpenCode: `read` deny rules (its `*` also matches `/`).
const SECRET_GLOBS = [".env", ".env.*", "secret.key", ".credentials*", "*.pem", "id_rsa*", "id_ed25519*"];
const SECRET_DIRS = [".dev-data"];
const claudeSecretDenies = [
  ...SECRET_GLOBS.map((g) => `Read(**/${g})`),
  ...SECRET_DIRS.map((d) => `Read(./${d}/**)`),
];
const openCodeSecretRules = [
  ...SECRET_GLOBS.map((g) => ({ action: "read", resource: `*${g.startsWith("*") ? g.slice(1) : `/${g}`}`, effect: "deny" })),
  ...SECRET_GLOBS.map((g) => ({ action: "read", resource: g, effect: "deny" })),
  ...SECRET_DIRS.map((d) => ({ action: "read", resource: `${d}/*`, effect: "deny" })),
].filter((r, i, all) => all.findIndex((x) => x.resource === r.resource) === i);

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
  console.log("Restart Hermes or run /reload-mcp in a running session.");
  process.exit(failed ? 1 : 0);
}

const opencodePath = join(root, "opencode.json");
const existing = existsSync(opencodePath)
  ? JSON.parse(readFileSync(opencodePath, "utf8"))
  : { $schema: "https://opencode.ai/config.json" };

// The generated parts: deny rules for subagent-only servers (rules for anything else are
// kept, in order) and the subagents themselves.
const subagentOnly = Object.entries(OPENCODE_SUBAGENT_ONLY).filter(([n]) => servers[n]);
const generatedActions = new Set(Object.keys(OPENCODE_SUBAGENT_ONLY).map(openCodeToolGlob));
const isGeneratedRead = (r) => r.action === "read" && r.effect === "deny" && openCodeSecretRules.some((g) => g.resource === r.resource);
const permissions = [
  ...(existing.permissions ?? []).filter((r) => !generatedActions.has(r.action) && !isGeneratedRead(r)),
  ...subagentOnly.map(([n]) => ({ action: openCodeToolGlob(n), resource: "*", effect: "deny" })),
  ...openCodeSecretRules, // last, so a broad allow earlier can't override them
];
// Subagents: the MCP-scoped ones above plus SUBAGENTS, written for Claude Code
// (.claude/agents/), OpenCode (opencode.json agents), Codex (.codex/agents/) and oh-my-pi
// (.omp/agents/, which also replaces omp's bundled `reviewer`).
// Claude Code and OpenCode also have a built-in explorer (Explore / explore) for
// read-only searches, so there's no custom one; give it a cheap model per machine.
const SUBAGENTS = {
  reviewer: {
    description:
      "Reviews a diff against Athena's rules (AGENTS.md, the app rules, gotchas) and reports bugs and rule breaks without editing. Use before opening a PR, or when asked to review.",
    claudeModel: "inherit", // a review needs the strongest model in use
    claudeTools: "Read, Grep, Glob, Bash",
    ompTools: ["read", "find", "grep", "glob", "bash"], // no edit/write: read-only
    readOnly: true,
    system:
      "Follow the athena-review skill (.agents/skills/athena-review/SKILL.md) exactly. Never edit files. Report findings ordered by severity, each with file:line, why it's wrong and a suggested fix.",
  },
};
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

// Shared slash commands: thin aliases for project skills, so the procedure lives in one
// place. Claude Code gets .claude/commands/<name>.md, OpenCode a `commands` entry; Hermes,
// Codex, Antigravity and Copilot run the skills themselves (/athena-next, $athena-next…).
const COMMANDS = {
  next: { skill: "athena-next", description: "Read STATUS and propose the next concrete step" },
  "check-prs": { skill: "athena-check-prs", description: "Check open PRs: CI, CodeQL, merges; fix failures" },
  ship: { skill: "athena-ship", description: "Commit, open the PR with auto-merge, watch CI" },
  handoff: { skill: "athena-handoff", description: "Update STATUS, HISTORY and gotchas before ending the session" },
  "review-diff": { skill: "athena-review", description: "Review the current diff against the project rules", agent: "reviewer" },
};
for (const c of Object.values(COMMANDS)) {
  if (!existsSync(join(root, ".agents", "skills", c.skill, "SKILL.md"))) throw new Error(`COMMANDS: skill ${c.skill} doesn't exist`);
}
const commandPrompt = (c) =>
  `Use the ${c.skill} skill (.agents/skills/${c.skill}/SKILL.md) and follow it.`;

const agents = { ...existing.agents };
for (const a of allSubagents) {
  agents[a.name] = {
    description: a.description,
    mode: "subagent",
    system: a.system,
    ...(a.openCodePermissions.length && { permissions: a.openCodePermissions }),
  };
}
const commands = { ...existing.commands };
for (const [name, c] of Object.entries(COMMANDS)) {
  commands[name] = {
    description: c.description,
    template: `${commandPrompt(c)} $ARGUMENTS`,
    ...(c.agent && { agent: c.agent, subagent: true }),
  };
}

const next = {
  ...existing,
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
      "---",
      "",
      generatedNote(a.source),
      "",
      a.system,
      "",
    ].join("\n"),
  ]),
);
const claudeCommands = Object.fromEntries(
  Object.entries(COMMANDS).map(([name, c]) => [
    join(".claude", "commands", `${name}.md`),
    [
      "---",
      `description: ${JSON.stringify(c.description)}`,
      "---",
      "",
      generatedNote("COMMANDS"),
      "",
      c.agent ? `Run this in the ${c.agent} subagent. ${commandPrompt(c)}` : commandPrompt(c),
      "",
      "$ARGUMENTS",
      "",
    ].join("\n"),
  ]),
);
const codexAgents = Object.fromEntries(
  allSubagents.map((a) => [
    join(".codex", "agents", `${a.name}.toml`),
    [
      "# Generated by scripts/agents-sync.mjs. Don't edit by hand.",
      `name = ${JSON.stringify(a.name)}`,
      `description = ${JSON.stringify(a.description)}`,
      `developer_instructions = ${JSON.stringify(a.system)}`,
      "",
    ].join("\n"),
  ]),
);
// oh-my-pi skips .claude/agents (different frontmatter) and reads only .omp/agents/*.md.
// No model means the session's model; omp gives MCP tools to every agent, so the
// playwright scoping above doesn't apply there.
const ompAgents = Object.fromEntries(
  allSubagents.map((a) => [
    join(".omp", "agents", `${a.name}.md`),
    [
      "---",
      `name: ${a.name}`,
      `description: ${JSON.stringify(a.description)}`,
      ...(a.ompModel ? [`model: ${JSON.stringify(a.ompModel)}`] : []),
      ...(a.ompTools ? ["tools:", ...a.ompTools.map((t) => `  - ${t}`)] : []),
      "---",
      "",
      generatedNote(a.source),
      "",
      a.system,
      "",
    ].join("\n"),
  ]),
);
// oh-my-pi has no setting for path read denies or a start-up script, so a project
// extension blocks secret reads and .omp/AGENTS.md imports STATUS. (Playwright needs no
// scoping there: omp drops browser MCP servers in favour of its own browser.)
// A native .omp/AGENTS.md shadows the root AGENTS.md at the same depth, hence the import.
const ompContext = [
  "<!-- Generated by scripts/agents-sync.mjs. Don't edit by hand. -->",
  "",
  "@../AGENTS.md",
  "",
  "@../docs/STATUS.md",
  "",
].join("\n");
const ompExtension = `// Generated by scripts/agents-sync.mjs (SECRET_GLOBS, SECRET_DIRS).
// Don't edit by hand. oh-my-pi loads every file in .omp/extensions/ by itself.
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";

const SECRET_GLOBS: string[] = ${JSON.stringify(SECRET_GLOBS)};
const SECRET_DIRS: string[] = ${JSON.stringify(SECRET_DIRS)};

const globToRegExp = (g: string) =>
  new RegExp("^" + g.replace(/[.+^\${}()|[\\]\\\\]/g, "\\\\$&").replace(/\\*/g, ".*").replace(/\\?/g, ".") + "$");
const secretNames = SECRET_GLOBS.map(globToRegExp);

function isSecret(path: unknown): boolean {
  if (typeof path !== "string" || /^[a-z][a-z0-9+.-]*:\\/\\//i.test(path)) return false; // URLs, internal URIs
  const parts = path.replace(/:\\d[\\d,+-]*$/, "").split(/[\\\\/]+/).filter(Boolean);
  return parts.some((p) => SECRET_DIRS.includes(p)) || secretNames.some((r) => r.test(parts.at(-1) ?? ""));
}

export default function athena(pi: ExtensionAPI) {
  pi.setLabel("Athena");
  pi.on("tool_call", async (event) => {
    const input = event.input as { path?: unknown };
    if (["read", "grep", "glob", "find"].includes(event.toolName) && isSecret(input.path)) {
      return { block: true, reason: "Athena: secret files (keys, .env, .dev-data) are off limits to agents." };
    }
  });
}
`;
// Codex reads MCP servers from .codex/config.toml (only in trusted projects).
const toml = (v) => JSON.stringify(v); // JSON strings and arrays of strings are valid TOML
const codexToml = [
  "# Generated by scripts/agents-sync.mjs from .mcp.json. Don't edit by hand.",
  "# Codex loads this only when the project is trusted (see docs/agents/tooling.md).",
  ...Object.entries(servers).flatMap(([n, s]) => [
    "",
    `[mcp_servers.${toml(n)}]`,
    ...(s.url ? [`url = ${toml(s.url)}`] : [`command = ${toml(s.command)}`, `args = ${toml(s.args ?? [])}`]),
    ...(s.env ? [`env = { ${Object.entries(s.env).map(([k, v]) => `${toml(k)} = ${toml(v)}`).join(", ")} }`] : []),
  ]),
  "",
].join("\n");

// Antigravity (which replaced Gemini CLI) reads workspace MCP from .agents/mcp_config.json.
const antigravity = JSON.stringify(
  {
    mcpServers: Object.fromEntries(
      Object.entries(servers).map(([n, s]) => [
        n,
        s.url ? { serverUrl: s.url, ...(s.headers && { headers: s.headers }) } : { command: s.command, args: s.args ?? [], ...(s.env && { env: s.env }) },
      ]),
    ),
  },
  null,
  2,
) + "\n";

// Gotchas that load by themselves when an agent touches matching files: Claude Code rules
// (`paths:`) and Copilot instructions (`applyTo`). Other agents follow the AGENTS.md router.
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
  areaRules[join(".claude", "rules", `${area}.md`)] = body(["---", "paths:", ...globs.map((g) => `  - ${JSON.stringify(g)}`), "---"].join("\n"));
  areaRules[join(".github", "instructions", `${area}.instructions.md`)] = body(["---", `applyTo: ${JSON.stringify(globs.join(","))}`, "---"].join("\n"));
}

// Claude Code project settings: only the secret Read denies are managed here.
const claudeSettingsPath = join(root, ".claude", "settings.json");
const claudeSettings = JSON.parse(readFileSync(claudeSettingsPath, "utf8"));
const otherDenies = (claudeSettings.permissions?.deny ?? []).filter((d) => !claudeSecretDenies.includes(d));
claudeSettings.permissions = { ...claudeSettings.permissions, deny: [...otherDenies, ...claudeSecretDenies] };
const claudeSettingsOut = JSON.stringify(claudeSettings, null, 2) + "\n";

// GENERATED: every file this script owns (fully, or the parts described above).
const outputs = {
  [join(".claude", "settings.json")]: claudeSettingsOut,
  "opencode.json": out,
  ...claudeAgents,
  ...claudeCommands,
  ...codexAgents,
  ...ompAgents,
  [join(".omp", "AGENTS.md")]: ompContext,
  [join(".omp", "extensions", "athena.ts")]: ompExtension,
  [join(".codex", "config.toml")]: codexToml,
  [join(".agents", "mcp_config.json")]: antigravity,
  ...areaRules,
};

if (args.has("--check")) {
  const stale = Object.entries(outputs).filter(([file, text]) => {
    const path = join(root, file);
    return !existsSync(path) || readFileSync(path, "utf8") !== text;
  });
  if (stale.length) {
    console.error(`Out of date: ${stale.map(([f]) => f).join(", ")}. Run: node scripts/agents-sync.mjs`);
    process.exit(1);
  }
  console.log(`${Object.keys(outputs).length} generated agent files are in sync`);
} else {
  for (const [file, text] of Object.entries(outputs)) {
    mkdirSync(dirname(join(root, file)), { recursive: true });
    writeFileSync(join(root, file), text);
  }
  console.log(`synced ${Object.keys(servers).length} MCP server(s) from .mcp.json to ${Object.keys(outputs).join(", ")}`);
}
