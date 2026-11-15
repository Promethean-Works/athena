#!/usr/bin/env node
// Syncs MCP servers from .mcp.json (the single source of truth) to other agents.
//
//   node scripts/agents-sync.mjs           write the "mcp" block of opencode.json and the
//                                          Claude Code subagents in .claude/agents/
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
    system:
      "Follow the athena-ui-verify skill (.agents/skills/athena-ui-verify/SKILL.md) exactly. Report what you verified, what you couldn't and why, and any bugs you found.",
  },
};
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
const permissions = [
  ...(existing.permissions ?? []).filter((r) => !generatedActions.has(r.action)),
  ...subagentOnly.map(([n]) => ({ action: openCodeToolGlob(n), resource: "*", effect: "deny" })),
];
const agents = { ...existing.agents };
for (const [n, a] of subagentOnly) {
  agents[a.agent] = {
    description: a.description,
    mode: "subagent",
    system: a.system,
    // Agent rules are appended after the global ones, and the last match wins.
    permissions: [{ action: openCodeToolGlob(n), resource: "*", effect: "allow" }],
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
};
const out = JSON.stringify(next, null, 2) + "\n";

// Claude Code subagents: one Markdown file per subagent-only server.
const claudeAgents = Object.fromEntries(
  subagentOnly.map(([, a]) => [
    join(".claude", "agents", `${a.agent}.md`),
    [
      "---",
      `name: ${a.agent}`,
      `description: ${JSON.stringify(a.description)}`,
      `model: ${a.claudeModel}`,
      "---",
      "",
      "<!-- Generated by scripts/agents-sync.mjs from OPENCODE_SUBAGENT_ONLY. Don't edit by hand. -->",
      "",
      a.system,
      "",
    ].join("\n"),
  ]),
);
const outputs = { "opencode.json": out, ...claudeAgents };

if (args.has("--check")) {
  const stale = Object.entries(outputs).filter(([file, text]) => {
    const path = join(root, file);
    return !existsSync(path) || readFileSync(path, "utf8") !== text;
  });
  if (stale.length) {
    console.error(`Out of date: ${stale.map(([f]) => f).join(", ")}. Run: node scripts/agents-sync.mjs`);
    process.exit(1);
  }
  console.log("opencode.json and .claude/agents are in sync with .mcp.json");
} else {
  for (const [file, text] of Object.entries(outputs)) {
    mkdirSync(dirname(join(root, file)), { recursive: true });
    writeFileSync(join(root, file), text);
  }
  console.log(`synced ${Object.keys(servers).length} MCP server(s) from .mcp.json to ${Object.keys(outputs).join(", ")}`);
}
