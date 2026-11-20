# 5. Frontend

## 5.1 Monorepo bootstrap

```bash
pnpm dlx shadcn@latest init --preset b0 --template next   # choose the monorepo option
```

This produces `apps/web` and `packages/ui`. Then:

- `apps/web/next.config.ts` → `output: "export"`, `images.unoptimized: true`
- add `packages/api-client` (generated)
- Turborepo tasks: `dev`, `build`, `lint`, `typecheck`, `gen:api`

## 5.2 App shell from the `dashboard-01` block

The sidebar, header and app layout come from the shadcn `dashboard-01` block, added to the web app:

```bash
pnpm dlx shadcn@latest add dashboard-01 -c apps/web
```

The CLI rewrites the block's Tabler icons to whatever icon library the preset uses. What happens to each file the block adds:

| Block file | What Athena does with it |
|---|---|
| `components/app-sidebar.tsx` | **Keep.** Replace the demo `data` object with nav built from the capability manifest. Missing features don't render. Put the Athena logo and name in the header |
| `components/nav-main.tsx` | **Keep.** Primary nav from `components/nav.ts`: Dashboard, Apps, Store, Packages, Automation, Files, SMB shares, Cloud, Containers, Terminal, Assistant, each gated by its capability. Swap the "Quick Create" button for "Add app" (store / custom) |
| `components/nav-secondary.tsx` | **Keep.** Settings, plus a link to help/docs |
| `components/nav-user.tsx` | **Keep.** Bind it to the logged-in user, with Account and Log out |
| `components/site-header.tsx` | **Keep.** Breadcrumb/page title, ⌘K command palette trigger, runtime status badge, assistant toggle |
| `components/nav-documents.tsx` | **Delete.** It's the block's demo document list |
| `app/dashboard/page.tsx` | **Delete.** Athena's own dashboard is `app/(app)/page.tsx` |
| `app/dashboard/data.json` | **Delete.** Demo data |
| `components/section-cards.tsx`, `chart-area-interactive.tsx`, `data-table.tsx` | **Delete.** They're demo dashboard content. Athena builds its own stats cards, charts and tables from shadcn `card`, `chart` and `table`, wired to the API |

Layout: `app/(app)/layout.tsx` holds `SidebarProvider` + `AppSidebar` (variant `inset`) + `SidebarInset` + `SiteHeader`. Every authenticated route lives under that layout. `/setup` and `/login` sit outside it.

Packages the block pulls in that Athena doesn't need, such as `@dnd-kit/*` (only the demo table's row drag uses it), are removed after the add.

## 5.3 Components: shadcn first, create only what's missing

| Need | Source |
|---|---|
| App shell, nav | `dashboard-01` block (see 5.2), plus shadcn `command` for the ⌘K palette |
| Stats | shadcn `card`, `chart` (Recharts), `progress`, `badge`, `skeleton` |
| Lists | shadcn `table` + TanStack Table (the shadcn *data-table* pattern), `empty`, `item`, `pagination` |
| Forms | shadcn `field`, `input`, `select`, `combobox`, `switch`, `textarea`, `input-group`, `radio-group` |
| Overlays | shadcn `dialog`, `sheet`, `alert-dialog`, `popover`, `tooltip`, `sonner` |
| Layout | shadcn `tabs`, `resizable`, `scroll-area`, `separator`, `accordion` |
| AI chat | **AI Elements** registry (shadcn-compatible, Apache-2.0): `conversation`, `message`, `prompt-input`, `tool`, `confirmation`, `reasoning` |
| Terminal | **Create:** `<Terminal>` wrapping xterm.js, themed from CSS vars |
| Code/compose editor | **Create:** `<CodeEditor>` wrapping CodeMirror 6 (YAML lang, lint) |
| File browser | **Create:** `<FileBrowser>` built from table, breadcrumb, context-menu, dropzone |
| App store card / app tile | **Create:** composed from card, badge, button |
| Log viewer | **Create:** virtualized `<LogStream>` (ANSI → spans) |
| Job progress | **Create:** `<JobToast>` on top of sonner + progress |

The rule: run `pnpm dlx shadcn@latest search` (and the AI Elements registry) before writing anything. Created components go into `packages/ui/src/components/athena/` and use only theme tokens.

## 5.4 Runtime appearance settings

shadcn presets are applied at *init/build time* by the CLI. Athena needs them switchable *at runtime* from Settings, so they're turned into data attributes and CSS variables:

| Setting | Runtime mechanism |
|---|---|
| Light/dark/system | `next-themes` (`class` attribute) |
| Base color | `[data-base="neutral|stone|zinc|mauve|olive|…"]` blocks that set `--background`, `--foreground`, `--muted`, `--border`… |
| Theme (accent) | `[data-theme="…"]` blocks that set `--primary`, `--ring`, `--sidebar-primary`… |
| Chart color | `[data-chart="…"]` blocks that set `--chart-1…5` |
| Body / heading font | All curated fonts loaded with `next/font` as CSS variables, then `[data-font="inter"]` → `--font-sans`, `[data-font-heading="…"]` → `--font-heading` |
| Radius | `[data-radius]` → `--radius` |
| Style (mira, luma, …) | **Spike needed.** See below |

- **Generated CSS (M4).** `scripts/gen-theme-css.mjs` (`pnpm gen:theme`) asks the registry's `/init` endpoint (what the shadcn CLI uses) for every base color, theme, chart color and radius, and writes `packages/ui/src/styles/themes.css` plus `themes.json` (the options and swatches the Settings page offers). Both are committed, so builds don't need the network; rerun after upgrading shadcn. Nothing is hand-copied.
  - The registry's model, found by probing: a theme is a colored accent (17) or the base color's own name ("match base", valid only with that base); explicit chart colors work the same way, and `neutral` charts means "follow the theme" (sent as no `chartColor`). `gray` is in the preset lists but the registry refuses it, so it's skipped.
  - Base blocks carry every variable; theme blocks carry what each theme actually sets, worked out per mode on two bases (most set primary, secondary, sidebar-primary and the charts; rose also sets the dark sidebar); chart blocks come last and override. The script verifies every colored theme on a third base, plus an explicit chart, against the registry and fails if they don't compose.
  - Selectors are `:root[data-base=…]` and `:root.dark[data-base=…]` (and the same for theme, chart, radius), which beat the `:root`/`.dark` defaults in `globals.css` without `!important`.
- **Fonts (M4).** All 26 preset fonts are self-hosted with `next/font` (`apps/web/lib/fonts.ts`) as `--font-<id>`; only Inter and Geist Mono are preloaded, so another font's files load the first time a page uses it. `[data-font]` sets `--font-sans`, `[data-font-heading]` sets `--app-font-heading`, and `globals.css` maps Tailwind's `font-heading` to it (Tailwind inlines `@theme inline` values, so the utility has to read a runtime variable). A `satisfies` check fails the build if shadcn adds a font.
- **Persistence (M4).** Saved per user (`users.appearance`, JSON; `GET/PUT /api/settings/appearance`). The server only checks the id shape; the UI normalizes unknown ids to the defaults. An inline script in `<head>` (`APPEARANCE_SCRIPT`) copies the browser's last-known settings onto `<html>` before first paint (verified: the attributes are set when `<body>` starts parsing); signed in, the account's settings are fetched and win. Changes apply instantly and are saved 400 ms after the last one. Dark/light/system stays with `next-themes`.
- **Preset codes (M4).** `shadcn/preset` (`encodePreset`/`decodePreset`, pure and browser-safe) runs in the browser. Export keeps b0's style, icons and menus; import applies colors, fonts and radius and reports what it skipped (another style, icon library, menu colors, or an option the registry doesn't serve).
- **Style (decided: one style in the MVP).** Styles change component class names and spacing, not just variables, so the MVP ships the style from preset `b0` only. The Style field in Settings shows the current style as read-only, with a "coming later" note. Post-MVP option: generate a `packages/ui` build per style and swap them by attribute-scoped CSS.

## 5.5 Routes

```
/setup                    first-run wizard (admin account, then optional AI provider)
/login
/                         dashboard
/apps                     installed apps
/apps/view?name=…         details · logs · shell · compose · settings
/apps/new                 custom app (compose / docker run import)
/store                    catalog browse/search
/store/view?catalog=…&id=…    app page + install (with variant picker)
/store/catalogs           remote catalogs
/packages                 tabs per detected manager
/automation               triggers, job runs, webhook and MCP addresses
/files                    file manager (locations + cloud remotes)
/files/shares             share links (WebDAV is in Settings → System)
/files/smb                SMB shares (Linux with Samba)
/s/<token>                a share link's public page (the /s/ export, served for any token)
/cloud                    rclone remotes + sync jobs
/containers               every container on the runtime
/terminal                 host terminal
/assistant                full-page chat (also available as a sheet everywhere)
/settings/{appearance,account,ai,system}
```

Static export doesn't allow dynamic segments without `generateStaticParams`. The workaround is query params (`/apps/view?name=…`) or a catch-all with client routing. **Decision: use query params for detail pages.**

**Feedback** has no page: "Send feedback" in the sidebar's bottom group opens a dialog (bug, change, feature), and each store app page has "Report a problem". Both open a filled-in issue on the forge in a new tab (`components/feedback/`, spec `docs/specs/feedback.md`).
