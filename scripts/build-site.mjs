#!/usr/bin/env node
// Builds the documentation pages of the website (site/docs/*.html) from the user guide
// (docs/user-guide/*.md). Plain Node, no dependencies; the markdown it understands is the
// subset the guide uses (headings, paragraphs, lists, tables, code blocks, quotes, links,
// images, bold, inline code). Also copies the guide's screenshots to site/assets/.
//
//   node scripts/build-site.mjs           write the pages
//   node scripts/build-site.mjs --check   fail if the written pages are out of date
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..")
const SRC = join(ROOT, "docs/user-guide")
const OUT = join(ROOT, "site/docs")
const GH = "https://github.com/Promethean-Works/athena/blob/main/docs"
const CHECK = process.argv.includes("--check")

// Order and grouping of the sidebar. The key is the markdown file name without .md.
const NAV = [
  ["Get started", [["README", "Introduction"], ["getting-started", "Getting started"]]],
  ["Using Athena", [
    ["dashboard", "Dashboard"], ["apps-and-store", "Apps and the store"], ["packages", "Packages"],
    ["files-and-sharing", "Files and sharing"], ["cloud-storage", "Cloud storage"],
    ["containers-and-terminal", "Containers and terminal"], ["assistant", "AI assistant"],
    ["automation", "Automation"], ["backups", "Backups"],
    ["remote-access-and-https", "Remote access and HTTPS"], ["settings", "Settings"],
  ]],
  ["Reference", [["command-line", "Command line"], ["troubleshooting", "Troubleshooting"], ["comparison", "Comparison"]]],
]
const FLAT = NAV.flatMap(([, items]) => items)
const outName = (key) => (key === "README" ? "index.html" : `${key}.html`)

const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;")
const slug = (s) => s.toLowerCase().replace(/`/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")

function href(url) {
  if (/^https?:|^#|^mailto:/.test(url)) return url
  const [path, hash = ""] = url.split("#")
  const h = hash ? `#${hash}` : ""
  if (path.startsWith("../")) return `${GH}/${path.slice(3)}${h}`
  const m = path.match(/^([\w-]+)\.md$/)
  return m ? outName(m[1]) + h : url
}

function inline(text) {
  const stash = []
  const keep = (html) => `\u0000${stash.push(html) - 1}\u0000`
  let s = text.replace(/`([^`]+)`/g, (_, c) => keep(`<code>${esc(c)}</code>`))
  s = s.replace(/<(https?:\/\/[^>\s]+)>/g, (_, u) => keep(`<a href="${esc(u)}">${esc(u)}</a>`))
  s = esc(s)
  s = s.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, src) => `<img src="${src.replace(/^images\//, "../assets/")}" alt="${alt}" loading="lazy">`)
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, t, u) => `<a href="${esc(href(u.replace(/&amp;/g, "&")))}">${t}</a>`)
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => stash[+i])
}

function render(md) {
  const lines = md.replace(/\r/g, "").split("\n")
  const html = []
  const toc = []
  let title = ""
  const isBlockStart = (l) => /^(#{1,4} |```|> |[-*] |\d+\. |\|)/.test(l)
  for (let i = 0; i < lines.length; ) {
    const l = lines[i]
    if (!l.trim()) { i++; continue }
    let m
    if (l.startsWith("```")) {
      const lang = l.slice(3).trim()
      const code = []
      for (i++; i < lines.length && !lines[i].startsWith("```"); i++) code.push(lines[i])
      i++
      html.push(`<pre><code${lang ? ` class="lang-${esc(lang)}"` : ""}>${esc(code.join("\n"))}</code></pre>`)
    } else if ((m = l.match(/^(#{1,4}) (.+)/))) {
      const level = m[1].length
      const id = slug(m[2])
      if (level === 1) { title = m[2].replace(/`/g, ""); html.push(`<h1>${inline(m[2])}</h1>`) }
      else {
        if (level <= 3) toc.push({ level, id, text: m[2].replace(/`/g, "") })
        html.push(`<h${level} id="${id}"><a class="anchor" href="#${id}">${inline(m[2])}</a></h${level}>`)
      }
      i++
    } else if (l.startsWith("|") && /^\|[\s:|-]+\|?\s*$/.test(lines[i + 1] ?? "")) {
      const cells = (row) => row.trim().replace(/^\||\|$/g, "").split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, "|"))
      const head = cells(l)
      const rows = []
      for (i += 2; i < lines.length && lines[i].startsWith("|"); i++) rows.push(cells(lines[i]))
      html.push(`<div class="table-wrap"><table><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c, j) => (j === 0 ? `<th scope="row">${inline(c)}</th>` : `<td>${inline(c)}</td>`)).join("")}</tr>`).join("")}</tbody></table></div>`)
    } else if (l.startsWith("> ")) {
      const q = []
      for (; i < lines.length && lines[i].startsWith(">"); i++) q.push(lines[i].replace(/^>\s?/, ""))
      html.push(`<blockquote><p>${inline(q.join(" "))}</p></blockquote>`)
    } else if (/^([-*]|\d+\.) /.test(l)) {
      const ordered = /^\d+\./.test(l)
      const items = []
      for (; i < lines.length && /^([-*]|\d+\.) /.test(lines[i]); i++) {
        let item = lines[i].replace(/^([-*]|\d+\.) /, "")
        while (lines[i + 1] && /^\s+\S/.test(lines[i + 1]) && !/^\s*([-*]|\d+\.) /.test(lines[i + 1])) item += " " + lines[++i].trim()
        items.push(item)
      }
      const tag = ordered ? "ol" : "ul"
      html.push(`<${tag}>${items.map((it) => `<li>${inline(it)}</li>`).join("")}</${tag}>`)
    } else {
      const p = []
      for (; i < lines.length && lines[i].trim() && (p.length === 0 || !isBlockStart(lines[i])); i++) p.push(lines[i].trim())
      const body = p.join(" ")
      html.push(/^!\[[^\]]*\]\([^)]+\)$/.test(body) ? `<figure>${inline(body)}</figure>` : `<p>${inline(body)}</p>`)
    }
  }
  return { html: html.join("\n"), toc, title }
}

function page(key, label) {
  const src = readFileSync(join(SRC, `${key}.md`), "utf8")
  const { html, toc, title } = render(src)
  const idx = FLAT.findIndex(([k]) => k === key)
  const prev = FLAT[idx - 1]
  const next = FLAT[idx + 1]
  const side = NAV.map(([group, items]) => `<div class="grp"><h4>${group}</h4>${items.map(([k, t]) => `<a href="${outName(k)}"${k === key ? ' class="on" aria-current="page"' : ""}>${esc(t)}</a>`).join("")}</div>`).join("")
  const onThis = toc.length ? `<aside class="toc"><h4>On this page</h4>${toc.map((t) => `<a class="l${t.level}" href="#${t.id}">${esc(t.text)}</a>`).join("")}</aside>` : "<aside class=\"toc\"></aside>"
  const pn = `<nav class="pn">${prev ? `<a href="${outName(prev[0])}"><span>Previous</span>${esc(prev[1])}</a>` : "<span></span>"}${next ? `<a class="r" href="${outName(next[0])}"><span>Next</span>${esc(next[1])}</a>` : "<span></span>"}</nav>`
  return `<!doctype html>
<!-- Generated by scripts/build-site.mjs from docs/user-guide/${key}.md. Edit the markdown, not this file. -->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title || label)} · Athena docs</title>
<meta name="description" content="Athena documentation: ${esc(label)}.">
<link rel="icon" href="../favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="../style.css">
<link rel="stylesheet" href="docs.css">
</head>
<body>
<header class="nav"><div class="wrap wide">
  <a class="brand" href="../index.html"><img src="../favicon.svg" alt="" width="28" height="28">Athena</a>
  <a class="l" href="index.html">Docs</a>
  <a class="l" href="comparison.html">Comparison</a>
  <a class="l" href="../index.html#install">Install</a>
  <a class="btn sm star" href="https://github.com/Promethean-Works/athena" data-star><svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg><span>Star on GitHub</span><b class="count" hidden></b></a>
</div></header>
<div class="wrap wide docs-layout">
  <details class="side" id="side" open><summary>Menu</summary><nav>${side}</nav></details>
  <main class="doc"><article>
${html}
</article>
${pn}
<p class="edit"><a href="https://github.com/Promethean-Works/athena/edit/main/docs/user-guide/${key}.md">Edit this page on GitHub</a></p>
</main>
  ${onThis}
</div>
<script>if (matchMedia("(max-width:900px)").matches) document.getElementById("side").open = false</script>
<script src="../copy.js" defer></script>
<script src="../star.js" defer></script>
</body>
</html>
`
}

let stale = 0
mkdirSync(OUT, { recursive: true })
for (const [key, label] of FLAT) {
  if (!existsSync(join(SRC, `${key}.md`))) throw new Error(`missing docs/user-guide/${key}.md`)
  const file = join(OUT, outName(key))
  const html = page(key, label)
  if (CHECK) { if (!existsSync(file) || readFileSync(file, "utf8") !== html) { console.error(`out of date: ${file}`); stale++ } }
  else writeFileSync(file, html)
}
const known = new Set(FLAT.map(([k]) => k))
for (const f of readdirSync(SRC)) if (f.endsWith(".md") && !known.has(f.slice(0, -3))) throw new Error(`${f} is not in NAV in scripts/build-site.mjs`)
if (!CHECK) {
  mkdirSync(join(ROOT, "site/assets"), { recursive: true })
  for (const f of readdirSync(join(SRC, "images"))) copyFileSync(join(SRC, "images", f), join(ROOT, "site/assets", f))
}
if (stale) { console.error("run: node scripts/build-site.mjs"); process.exit(1) }
console.log(CHECK ? "site docs are up to date" : `wrote ${FLAT.length} pages to site/docs/`)
