# Athena design

Athena is a self-hosted home server control panel in the spirit of CasaOS, that runs on **Linux, macOS and Windows**. It manages containers (Docker/Compose), host package managers, files, shares and cloud storage, and includes an AI assistant that can drive all of it.

Hard rules that shape every decision below:

1. **Cross-platform.** Every feature goes through a platform provider. Nothing in the API or UI assumes Linux.
2. **Show only what exists.** The backend detects what the host has and publishes a *capability manifest*. The UI renders navigation, pages and actions from that manifest. If `apt` isn't on the box, the user never sees an apt option.
3. **Open-source dependencies only.** No Docker Desktop, no macFUSE, no proprietary SDKs. Licenses are listed in [§9](licenses.md).

## Sections

One file per section; read only the ones your task touches. Section numbers (`§4.5`) are kept, so older references still resolve through this table.

| § | File | What |
|---|---|---|
| 1 | [scope.md](scope.md) | MVP scope |
| 2 | [architecture.md](architecture.md) | Architecture |
| 3 | [platform.md](platform.md) | Platform layer and capability manifest |
| 4.1 | [apps.md](apps.md) | Apps and the app store |
| 4.2 | [terminal.md](terminal.md) | Terminal |
| 4.3 | [files.md](files.md) | Files and sharing |
| 4.4 | [cloud.md](cloud.md) | Cloud storage |
| 4.5 | [assistant.md](assistant.md) | AI assistant |
| 4.6 | [dashboard.md](dashboard.md) | Dashboard |
| 4.7 | [automation.md](automation.md) | Automation and the MCP server (M8) |
| 4.8 | [tunnels.md](tunnels.md) | Remote access (tunnels) |
| 5 | [frontend.md](frontend.md) | Frontend |
| 6 | [backend.md](backend.md) | Backend layout and API |
| 7 | [security.md](security.md) | Security baseline, HTTPS |
| 8 | [distribution.md](distribution.md) | Distribution (MVP) |
| 9 | [licenses.md](licenses.md) | Dependency / license inventory |
| 10 | [milestones.md](milestones.md) | Milestones |
| 11 | [decisions.md](decisions.md) | Decisions log |
| 12 | [open-questions.md](open-questions.md) | Open questions |

When a design changes, update its section and add a row to [decisions.md](decisions.md).
