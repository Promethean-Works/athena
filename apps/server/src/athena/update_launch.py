"""Start the self-update helper so it outlives the server (docs/specs/self-update.md).

The helper stops the service, so whatever starts it must not be part of what gets stopped:

- Linux: `systemctl stop` kills the whole cgroup, even a child with its own session. The helper
  runs as a transient unit (`systemd-run`), which belongs to systemd, not to `athena.service`.
- macOS: `launchctl bootout` signals the agent's process group. A child in a new session
  leaves it (checked on a real Mac against a throwaway agent: the child survived bootout).
- Windows: the logon task runs `pythonw.exe` with no console and possibly invalid standard
  handles, and its job object may kill children on `/End`. The helper is a one-shot scheduled
  task, which belongs to the Task Scheduler. If the task can't be created, a detached process
  with all three standard handles on DEVNULL and no inherited handles is the fallback.

Everything is a pure argv builder plus a small `launch` that takes the runner and spawner as
arguments, so each OS's commands are tested from any OS.
"""

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

UPDATE_UNIT = "athena-update"
WINDOWS_UPDATE_TASK = "AthenaUpdate"
# Variables a transient unit doesn't inherit from the server but uv needs to find its cache
# (the pre-flight filled it, and the swap runs `--offline`).
PASS_THROUGH = ("HOME", "PATH", "XDG_CACHE_HOME", "XDG_DATA_HOME", "UV_CACHE_DIR", "LANG")
# schtasks limits the /TR command line to 261 characters.
WINDOWS_TR_MAX = 261


class LaunchError(RuntimeError):
    """The helper couldn't be started (nothing was stopped)."""


@dataclass(frozen=True)
class Launched:
    how: str
    """"systemd-run", "session", "scheduled task" or "detached process"."""


Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]
Spawner = Callable[..., object]


def _platform(platform: str | None) -> str:
    plat = platform or sys.platform
    if plat.startswith("linux"):
        return "linux"
    return "darwin" if plat == "darwin" else "win32"


def systemd_run_argv(argv: list[str], env: Mapping[str, str]) -> list[str]:
    """`systemd-run` for the helper: its own unit, collected when it ends, even if it failed."""
    setenv = [f"--setenv={k}={env[k]}" for k in sorted(env) if k in PASS_THROUGH or k[:3] == "UV_"]
    return ["systemd-run", "--unit", UPDATE_UNIT, "--collect", "--quiet", *setenv, *argv]


def windows_task_command(argv: list[str]) -> str:
    return " ".join(f'"{a}"' for a in argv)


def windows_task_steps(argv: list[str]) -> list[list[str]]:
    """Create the one-shot task and run it. `/ST` is required for `ONCE`; the time is never
    waited for because the task is run by hand right away."""
    command = windows_task_command(argv)
    if len(command) > WINDOWS_TR_MAX:
        raise LaunchError(
            f"The update command is {len(command)} characters; schtasks allows {WINDOWS_TR_MAX}"
        )
    return [
        [
            "schtasks",
            "/Create",
            "/TN",
            WINDOWS_UPDATE_TASK,
            "/TR",
            command,
            "/SC",
            "ONCE",
            "/ST",
            "00:00",
            "/RL",
            "LIMITED",
            "/F",
        ],
        ["schtasks", "/Run", "/TN", WINDOWS_UPDATE_TASK],
    ]


def cleanup_steps(platform: str | None = None) -> list[dict[str, object]]:
    """What the helper runs when it ends (Windows deletes its one-shot task)."""
    if _platform(platform) != "win32":
        return []
    return [
        {
            "argv": ["schtasks", "/Delete", "/TN", WINDOWS_UPDATE_TASK, "/F"],
            "ignore_errors": True,
        }
    ]


def run_quietly(argv: list[str]) -> "subprocess.CompletedProcess[str]":
    """Run a short command. All three handles are explicit: under `pythonw.exe` the inherited
    ones can be invalid (docs/agents/gotchas/windows.md)."""
    return subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def popen_detached(argv: list[str], env: Mapping[str, str], *, windows: bool) -> None:
    """A process in its own session (POSIX) or detached from the console and job's handles."""
    options: dict[str, object] = {
        "env": dict(env),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if windows:
        options["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    else:
        options["start_new_session"] = True
    subprocess.Popen(argv, **options)  # type: ignore[call-overload]


def _failed(argv: list[str], done: "subprocess.CompletedProcess[str]") -> str:
    tail = (done.stdout or "").strip().splitlines()[-3:]
    return f"{Path(argv[0]).name} exited {done.returncode}: " + " ".join(tail)


def launch(
    argv: list[str],
    env: Mapping[str, str] | None = None,
    *,
    platform: str | None = None,
    runner: Runner = run_quietly,
    spawner: Spawner | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> Launched:
    """Start `argv` (the helper) detached from this process tree. Raises `LaunchError`."""
    env = dict(os.environ if env is None else env)
    plat = _platform(platform)
    spawn = spawner or (lambda a, e, windows: popen_detached(a, e, windows=windows))
    try:
        if plat == "linux":
            if which("systemd-run"):
                command = systemd_run_argv(argv, env)
                done = runner(command)
                if done.returncode != 0:
                    raise LaunchError(f"Can't start the update: {_failed(command, done)}")
                return Launched("systemd-run")
            spawn(argv, env, False)  # not under systemd, so no cgroup to escape
            return Launched("session")
        if plat == "darwin":
            spawn(argv, env, False)
            return Launched("session")
        error = ""
        try:
            for step in windows_task_steps(argv):
                done = runner(step)
                if done.returncode != 0:
                    error = _failed(step, done)
                    break
            else:
                return Launched("scheduled task")
        except LaunchError as exc:
            error = str(exc)
        spawn(argv, env, True)
        return Launched(f"detached process ({error})")
    except OSError as exc:
        raise LaunchError(f"Can't start the update: {exc}") from exc
