<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

# Athena web app (`apps/web`)

Rules for working on the UI. The repo-wide rules, Git workflow and handoff are in the root `AGENTS.md`; read that first. Gotchas: `docs/agents/gotchas/web.md` (read before changing UI code) and `docs/agents/gotchas/browser.md` (for browser checks). For step-by-step changes (page, sidebar entry, API calls), use the `athena-recipes` skill. Before calling UI work done, use `athena-ui-verify`.

## Stack and commands

Next.js 16 with a static export (`output: "export"`, `trailingSlash: true`), React 19, shadcn/ui on Base UI (`base-nova` style, preset `b0`, lucide icons). FastAPI serves the export in production, so no Node is needed at runtime.

| Task | Command (from the repo root) |
|---|---|
| Lint, types, build | `pnpm lint && pnpm typecheck && pnpm build` |
| Dev server | `pnpm dev` (Next on :3000; `/api` is proxied to `http://localhost:8420` only in `next dev`) |
| Regenerate the API client | `pnpm gen:api` |
| Add a shadcn component | `pnpm dlx shadcn@latest add <name> -c apps/web` (check that the files land in `packages/ui`) |
| Everything CI checks | `scripts/check.sh web` |

## Layout

| Path | What it holds |
|---|---|
| `app/(app)/` | Signed-in pages, inside `AuthProvider` then `CapabilitiesProvider` (`layout.tsx`). Each `page.tsx` is a few lines that render a view from `components/` |
| `app/(auth)/` | `/setup` and `/login` |
| `components/<area>/` | Views and pieces per area: `apps`, `assistant`, `automation`, `cloud`, `containers`, `dashboard`, `files`, `packages`, `settings`, `share` (the public `/s/` page), `store`, `terminal` |
| `components/nav.ts` | Sidebar entries; add one only when its page exists |
| `components/job-dialog.tsx`, `log-view.tsx` | Job progress and live logs |
| `hooks/` | `use-api.ts` (load on mount), `use-event-stream.ts` (SSE) |
| `lib/` | `appearance.ts` (runtime theming, `APPEARANCE_SCRIPT`), `fonts.ts`, `format.ts`, `clipboard.ts` |
| `packages/ui/src/components/` (repo root) | shadcn components, plus Athena-made ones in `athena/` (`code-editor.tsx`, `terminal.tsx`) |

## Conventions

- **Data:**
  - All data loads in the browser through `@workspace/api-client` (`api.GET`, `api.POST`, `errorMessage`). The client adds the CSRF header and redirects to `/login/` on 401.
  - There are no server actions and no API routes.
  - Never hand-write request types; derive missing shapes from `Schemas`.
- **Routing:**
  - There are no dynamic routes (static export).
  - Detail pages read query params with `useSearchParams()`, e.g. `/apps/view/?name=x`.
- **Capabilities and auth:**
  - Use `useAuth()` and `useCapability(id)`, and give nav items a `capability`.
  - A missing capability renders `Empty` with its `detail`, never a broken page.
  - Pages that need containers wrap their content in `<RequireContainers>`.
- **Feedback:**
  - Notifications use `toast.add({ type, title, description })` from `@workspace/ui/components/toast` (Base UI), not sonner.
  - Errors show next to the field or in a toast, never silently.
  - Refresh lists after every action.
- **Live output:** `useEventStream(url)` for SSE, `<LogView>`, and `<JobDialog job>` for anything that returns a job.
- **Components:**
  - Use shadcn first: search the registries (shadcn MCP / `shadcn search`, or the skill) before building anything. For chat UI that includes shadcn's chat components and the AI Elements patterns at ui.shadcn.com/docs/ai-elements, which are copied in and need no Vercel AI SDK. Only create a component when nothing fits.
  - The app shell comes from the `dashboard-01` block, without its demo data, demo page or demo content components.
  - Base UI isn't Radix: it uses the `render` prop instead of `asChild`, and `Select` and `ToggleGroup` have different APIs. Check the `shadcn` skill.
  - Code editing uses `CodeEditor` from `@workspace/ui/components/athena/code-editor`; terminals use `<Terminal>` from `@workspace/ui/components/athena/terminal`, with `TerminalSession`, `ShellSheet` and `useTerminalAccess` in `components/terminal/`. The share dialogs are `components/files/share-*.tsx`, and the WebDAV switch is `components/settings/webdav-card.tsx`.
  - Chat UI is shadcn's own (`message`, `bubble`, `message-scroller`, `trace`, `code-block`) following the AI Elements patterns, without the Vercel AI SDK. Replies stream from `useChatStream` (`components/assistant/use-chat-stream.ts`, fetch + SSE reader); models are picked with `ModelPicker` (`components/assistant/model-picker.tsx`). `AssistantChat` (`components/assistant/assistant-view.tsx`) is the chat itself, used by the `/assistant` page (chat id in `?c=`) and by `AssistantSheet` in the site header (chat id in state, `compact`).
  - Files work on a `Source` (`{ location }` or `{ remote }`, in `components/files/file-utils.ts`): use `downloadUrl(source, …)`, `folderHref(source, …)` and `FolderPicker` (`components/files/folder-picker.tsx`), which already handle cloud remotes. Get remotes from `useRemotes()` (`components/cloud/use-remotes.ts`), which is empty when rclone isn't ready.
- **Design quality** (the `frontend-design` skill, `.agents/skills/frontend-design/`):
  - Before building or reshaping UI, read the skill, ground the design in the product's subject matter and audience, write a one-paragraph visual direction, pick a compact token system (color, type, layout, principles) from the existing theme tokens and fonts (a feature adds no colors or tokens of its own; see Theming), and review the result against that direction rather than against generic AI defaults (warm-cream/terracotta palette, acid accents, all-caps labels, tracked-out eyebrows, identical rounded cards with soft shadows, `→` on buttons).
  - shadcn primitives first (see Components) and semantic theme tokens over hardcoded colors (see Theming).
  - One active decorative element at most. Respect reduced motion, keep keyboard focus visible, and check the responsive breakpoints 1440 / 768 / 390.
- **Theming:**
  - Use theme tokens only (`bg-card`, `text-muted-foreground`): no raw colors and no `dark:` overrides.
  - Base color, theme, chart color, fonts and radius switch at runtime through data attributes on `<html>` (`lib/appearance.ts`).
  - `packages/ui/src/styles/themes.css` and `themes.json` are generated from the shadcn registry by `pnpm gen:theme` (`scripts/gen-theme-css.mjs`); never edit them by hand, and rerun after upgrading shadcn. Fonts are in `lib/fonts.ts`.
  - The shadcn style is fixed to preset `b0` for the MVP.
- **Next 16:**
  - Read `node_modules/next/dist/docs/` (see the block above) before writing Next code.
  - Each `next/font` loader call must be its own module-level `const` with literal options.
  - Keep `skipTrailingSlashRedirect` in the dev config.
