"""What the terminal runs: the host's shell, or a shell inside a container."""

import contextlib
import os
import shutil
import sys
from pathlib import Path

from athena.containers.runtime import Runtime

# bash when the image has it, sh otherwise. Passed as one argument, so no host shell.
CONTAINER_SHELL = "if command -v bash >/dev/null 2>&1; then exec bash; else exec sh; fi"


def host_shell() -> list[str]:
    """The service user's login shell on POSIX; PowerShell 7 or Windows PowerShell."""
    if sys.platform == "win32":
        exe = shutil.which("pwsh.exe") or shutil.which("powershell.exe") or "powershell.exe"
        return [exe, "-NoLogo"]
    shell = ""
    try:
        import pwd

        shell = pwd.getpwuid(os.getuid()).pw_shell
    except (ImportError, KeyError):
        shell = os.environ.get("SHELL", "")
    if not shell or not os.access(shell, os.X_OK) or shell.endswith(("/nologin", "/false")):
        shell = "/bin/sh"
    return [shell, "-l"]


def command_argv(command: str) -> list[str]:
    """Runs one command line with the host's shell (the assistant's `run_command`): the
    login shell with -c on POSIX, so PATH matches the terminal; PowerShell on Windows."""
    if sys.platform == "win32":
        exe = host_shell()[0]
        return [exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command]
    return [host_shell()[0], "-l", "-c", command]


def command_env() -> dict[str, str]:
    """No colors and no pagers: the output goes to a model, not a terminal."""
    env = dict(os.environ)
    env.update({"TERM": "dumb", "NO_COLOR": "1", "PAGER": "cat", "SYSTEMD_PAGER": ""})
    if sys.platform != "win32":
        env.setdefault("LANG", "C.UTF-8")
    return env


CASE_INSENSITIVE = sys.platform == "win32"
"""PowerShell cmdlets and Windows executables ignore case."""


def default_commands() -> list[str]:
    """The assistant shell's starting allowlist: mostly commands that look, not change."""
    if sys.platform == "win32":
        return [
            "Get-ChildItem", "Get-Content", "Get-Process", "Get-Service", "Get-Volume",
            "Get-NetIPAddress", "Get-ComputerInfo", "Select-String", "Select-Object",
            "Sort-Object", "Measure-Object", "ipconfig", "ping", "whoami", "docker", "wsl",
        ]  # fmt: skip
    return [
        "cat", "df", "du", "free", "uptime", "uname", "whoami", "id", "ps", "ls", "head",
        "tail", "grep", "wc", "sort", "find", "stat", "ip", "ss", "ping", "journalctl",
        "systemctl", "docker", "podman",
    ]  # fmt: skip


def kill_tree(pid: int) -> None:
    """Kills a command started with `start_new_session=True` and everything it started."""
    import signal
    import subprocess

    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, check=False)
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, signal.SIGKILL)


def container_shell(runtime: Runtime, ref: str) -> list[str]:
    """`docker exec -it` through the same CLI the rest of Athena uses (WSL included)."""
    return runtime.command(
        "exec", "-it", "-e", "TERM=xterm-256color", ref, "sh", "-c", CONTAINER_SHELL
    )


def shell_env() -> dict[str, str]:
    env = dict(os.environ)
    env["TERM"] = "xterm-256color"
    env["COLORTERM"] = "truecolor"
    if sys.platform != "win32":
        env.setdefault("LANG", "C.UTF-8")
    return env


def home() -> Path:
    try:
        return Path.home()
    except RuntimeError:
        return Path.cwd()
