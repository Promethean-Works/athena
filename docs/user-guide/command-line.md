# Command line

The `athena` command (`athena --help`). Most commands take `--data-dir` to point at a different data folder.

| Command | What it does |
|---|---|
| `serve` | run the server in the foreground |
| `start`, `stop` | start or stop the server in the background |
| `service install\|uninstall\|status` | register Athena to start automatically, or remove it |
| `doctor` | check the host and the server, and print what's wrong |
| `admin reset-password` | set a new password for an account |
| `config path\|show\|check\|reset` | find, check or reset `athena.json` |
| `https status\|off` | show HTTPS settings, or turn HTTPS off |
| `restore` | restore Athena from a backup |
| `openapi` | print or write the API schema |

Run `athena doctor` first when something doesn't work.
