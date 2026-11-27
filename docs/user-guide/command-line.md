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

## Setup wizard

`athena onboard` walks through the same steps as the first-run screen in the browser: the admin account (only if there is none), language, container runtime, file folders and the address and port Athena listens on. It writes straight to the data folder, so it works with Athena stopped, and you can run it again whenever the machine changes.

```bash
athena onboard                         # asks for each step
athena onboard --yes --port 8421       # no questions: keep what is set, apply the flags
athena onboard --runtime kiri          # install a container runtime (asks your password for sudo on Linux)
athena onboard --location Media=/srv/media --language pt-BR
athena onboard --reset                 # open the setup wizard in the browser again
```

Creating the account without a prompt needs `--yes --password-stdin`. The AI assistant is set up in the browser (Settings → AI). Network changes apply after Athena restarts.
