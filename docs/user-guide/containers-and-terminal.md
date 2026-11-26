# Containers and terminal

## Containers

**Containers** lists every container on the runtime, whether Athena installed it or not: status, image and ports. You can start, stop, restart and read logs. Be careful with containers you didn't create through Athena; they may belong to something else.

## Terminal

**Terminal** opens a shell in the browser, on the host or inside a container. It's admin only, and every use is written to the audit log.

- On Linux and macOS it runs your service user's login shell. On Windows it runs PowerShell.
- In a container it uses bash if the image has it, otherwise sh.
- Up to 10 terminals can be open at once.

The terminal is a powerful feature: whoever has an admin account can run commands on the server. You can switch it off in **Settings → System**.
