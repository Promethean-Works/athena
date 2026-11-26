#!/usr/bin/env node
// Every language in apps/web/locales must have exactly English's keys and {{placeholders}}
// (docs/specs/i18n.md). Plural forms (key_one, key_other, ...) count as one key.
import { readdirSync, readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "apps/web/locales")
const PLURAL = /_(zero|one|two|few|many|other)$/

function flatten(obj, prefix = "", out = new Map()) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix + k
    if (v && typeof v === "object") flatten(v, key + ".", out)
    else {
      const base = key.replace(PLURAL, "")
      const found = new Set(String(v).match(/\{\{\s*[\w.]+\s*\}\}/g)?.map((p) => p.replace(/\s/g, "")))
      const prev = out.get(base) ?? new Set()
      for (const p of found) prev.add(p)
      out.set(base, prev)
    }
  }
  return out
}

const load = (lang, file) => flatten(JSON.parse(readFileSync(join(root, lang, file), "utf8")))
const files = (lang) => readdirSync(join(root, lang)).filter((f) => f.endsWith(".json")).sort()
const problems = []
const english = files("en")

for (const lang of readdirSync(root, { withFileTypes: true }).filter((d) => d.isDirectory() && d.name !== "en").map((d) => d.name)) {
  const have = files(lang)
  for (const f of english.filter((f) => !have.includes(f))) problems.push(`${lang}/${f}: file missing`)
  for (const f of have.filter((f) => !english.includes(f))) problems.push(`${lang}/${f}: not in en`)
  for (const f of english.filter((f) => have.includes(f))) {
    const en = load("en", f)
    const other = load(lang, f)
    for (const [key, ph] of en) {
      const got = other.get(key)
      if (!got) problems.push(`${lang}/${f}: missing key ${key}`)
      else if ([...ph].sort().join() !== [...got].sort().join())
        problems.push(`${lang}/${f}: ${key} placeholders differ (en: ${[...ph].join(" ") || "none"}; ${lang}: ${[...got].join(" ") || "none"})`)
    }
    for (const key of other.keys()) if (!en.has(key)) problems.push(`${lang}/${f}: extra key ${key}`)
  }
}

if (problems.length) {
  console.error(problems.join("\n"))
  console.error(`\ni18n check failed: ${problems.length} problem(s)`)
  process.exit(1)
}
console.log(`i18n check: ${english.length} namespaces match across languages`)
