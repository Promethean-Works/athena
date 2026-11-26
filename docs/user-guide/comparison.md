# Athena compared with other home server panels

Athena is one of several ways to run a home server from a dashboard. This page lines it up against four others, so you can pick the one that fits.

The comparison reflects each project's public documentation and repository on **26 November 2026**. These projects change, so check them before you decide. "Not confirmed" means we couldn't find a clear answer, not that the feature is missing.

| | Athena | CasaOS | Cosmos Server | Udon | umbrelOS |
|---|---|---|---|---|---|
| **Runs on** | Linux, macOS and Windows, as a program on your existing system | Linux, as a program on your existing system | Linux, as a program on your existing system | macOS only | Its own operating system (x86 and Raspberry Pi 5) |
| **App store** | About 190 apps, plus your own compose files and catalogs | About 150 apps | A market, plus compose files | A curated set | 300+ apps |
| **Backup and restore** | Yes, encrypted and scheduled, to disk or any cloud remote | No | Yes (Restic) | Not confirmed | Yes |
| **HTTPS** | Self-signed or Let's Encrypt, your own certificate, and tunnels | No | Yes, with a built-in reverse proxy | Through Tailscale | No |
| **Remote access without opening ports** | Cloudflare, Tailscale or ngrok | Not confirmed | Not confirmed | Tailscale | Not confirmed |
| **Two-factor sign-in** | Not yet | No | Yes | Not confirmed | Yes |
| **Several users** | Admin accounts only | No | Yes | No | Yes |
| **Disk management** | Not yet | No | Yes (MergerFS) | Drive health | Yes |
| **Alerts** | Not yet | No | Yes | Not confirmed | Not confirmed |
| **AI assistant** | Yes, asks before it acts, with local or cloud models | No | No | Yes | No |
| **MCP** | Server, and the assistant can use MCP tools | No | No | Yes | Server only |
| **Host package manager** | Yes (apt, dnf, Homebrew, winget and more) | No | No | Not confirmed | No |
| **Cron and webhook automation** | Yes | No | No | Not confirmed | No |
| **Audit log** | Yes | No | Not confirmed | Not confirmed | Not confirmed |
| **License** | Apache-2.0 | Apache-2.0 | Apache-2.0 with the Commons Clause | Proprietary, paid | Non-commercial |

## Where Athena fits

- **You run more than one kind of machine.** Athena is the only one here that runs on Linux, macOS and Windows, and it hides what a host can't do.
- **You want to talk to your server.** The assistant installs, edits and runs things for you, but shows an approval card first. Udon is the other product here with an assistant.
- **You want one tool for the host and the containers.** Athena manages host packages, files, cloud storage, automation and apps, all with an audit log.

## Where another one fits better

- **You want a dedicated appliance.** umbrelOS is its own operating system, with a large app store and a polished experience. If you're installing on a spare machine and nothing else, it's a good choice.
- **You need several users, 2FA or disk management today.** Cosmos Server has them, together with a built-in reverse proxy. Athena doesn't yet.
- **You only use a Mac and want a managed experience.** Udon is built for that.
- **You want something small on Linux.** CasaOS is lightweight and simple. Its core releases have slowed, with the last one, v0.4.15, in December 2024.

If we've got something wrong, please [open an issue](https://github.com/Promethean-Works/athena/issues) and we'll fix it.
