# 9. Dependency / license inventory

| Component | License |
|---|---|
| Next.js, React, shadcn/ui, Radix/Base UI, Tailwind, Recharts, TanStack Table | MIT |
| shadcn chat components and AI Elements patterns (copied in) | MIT |
| cryptography (Fernet for AI keys) | Apache-2.0 / BSD-3-Clause |
| react-markdown, remark-gfm (assistant replies), @shadcn/react (Message Scroller) | MIT |
| qrcode.react (tunnel address QR code) | ISC |
| Provider SDKs pulled in by pydantic-ai-slim: openai, anthropic, google-genai (with google-auth, used for Vertex AI service-account credentials), groq, mistralai, cohere (the `cohere` extra, #149) | Apache-2.0 / MIT |
| cohere's dependencies: fastavro, filelock (MIT); tokenizers, huggingface-hub, hf-xet, types-requests (Apache-2.0); fsspec (BSD-3-Clause); tqdm | MIT / Apache-2.0 / BSD-3-Clause; tqdm is MPL-2.0 AND MIT |
| boto3 (Bedrock, via pydantic-ai-slim) | Apache-2.0 |
| xterm.js, CodeMirror 6, next-themes, openapi-typescript | MIT |
| typescript-eslint (ESLint parser and rules for `.ts`/`.tsx`) | MIT |
| shadcn CLI package (`shadcn/preset` used at runtime) | MIT |
| Preset fonts via `next/font/google` (Inter, Geist, Lora, Roboto and the other 22) | SIL OFL 1.1 / Apache-2.0 |
| Base UI (`@base-ui/react`), `cn`, Turborepo, openapi-fetch, lucide-react, sonner, zod | MIT / ISC |
| pydantic-settings, platformdirs, hatchling | MIT |
| SQLModel, SQLAlchemy, Alembic, argon2-cffi | MIT |
| python-on-whales, PyYAML | MIT |
| croniter | MIT |
| mcp (MCP client and server SDK) | MIT |
| fastmcp (Athena's MCP server, §4.7) | Apache-2.0 |
| exa-py (web research) | MIT |
| pgtask (durable execution) | MIT |
| psycopg (pgtask's Postgres driver; used only when durable execution is configured) | LGPL-3.0-only |
| CodeMirror 6, @uiw/react-codemirror | MIT |
| js-yaml (compose form ↔ YAML), embla-carousel-react, embla-carousel-autoplay (store carousel), tw-animate-css | MIT |
| @dnd-kit/core, @dnd-kit/sortable, @dnd-kit/utilities (dashboard card drag and drop) | MIT |
| class-variance-authority | Apache-2.0 |
| dashboard-icons (catalog icons, loaded by URL) | Apache-2.0 |
| httpx2 (provider HTTP at runtime, and the test client) | BSD-3-Clause |
| Playwright for Python (e2e smoke test only, not shipped) | Apache-2.0 |
| pytest-cov, coverage.py (test coverage only, not shipped) | MIT / Apache-2.0 |
| FastAPI, SQLModel, Pydantic, pydantic-ai, pydantic-ai-harness, uvicorn | MIT / BSD |
| json-repair (the harness's `repair-tool-arguments` extra) | MIT |
| stackone-defender (the harness's `prompt-injection-defender` extra; no dependencies, an 18 MB wheel with an unused bundled model) | Apache-2.0 |
| pydantic-monty, pydantic-monty-client, pydantic-monty-runtime (the harness's `dynamic-workflow` extra: the Monty Python sandbox; wheels for Linux, macOS and Windows) | MIT |
| Docker Engine (Moby), Docker CLI, Compose v2 | Apache-2.0 |
| python-on-whales, psutil, platformdirs, pywinpty (Windows only), send2trash | MIT / BSD / ISC |
| wsgidav (with defusedxml, Jinja2, json5) | MIT / PSF / BSD-3 / Apache-2.0 |
| a2wsgi | Apache-2.0 |
| Colima, Lima | MIT / Apache-2.0 |
| Podman | Apache-2.0 |
| rclone | MIT |
| restic (backups, downloaded at runtime, pinned version and SHA-256) | BSD-2-Clause |
| lego (ACME client, downloaded at runtime for Let's Encrypt, pinned version and SHA-256) | MIT |
| Kiri (container runtime, optional: installed on the admin's click from a pinned release and SHA-256, not bundled) | Apache-2.0 |
| Pebble (Let's Encrypt's test ACME server, CI only, not shipped) | MPL-2.0 |
| winget-cli, scoop, Chocolatey CLI | MIT / Unlicense / Apache-2.0 |
| i18next, react-i18next (web UI translations) | MIT |
| Homebrew | BSD-2 |
| CasaOS AppStore (catalog data) | Apache-2.0 |
| Agent skills in `.agents/skills/` (dev tooling, not shipped): `shadcn`, `pydantic`, `building-pydantic-ai-agents`, `pydantic-ai-harness` / `frontend-design` | MIT / Apache-2.0 |
| ~~Docker Desktop, macFUSE, Umbrel apps~~ | Excluded (proprietary / non-commercial) |
