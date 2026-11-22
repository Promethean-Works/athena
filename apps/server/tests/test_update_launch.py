"""Starting the update helper so it outlives the server, per OS (argv built on any host)."""

import subprocess
from typing import Any

import pytest

from athena import update_launch
from athena.update_launch import LaunchError, launch

HELPER = ["/py/python", "-I", "/data/updates/run/update_helper.py"]


class Calls:
    def __init__(self, failing: tuple[str, ...] = ()) -> None:
        self.ran: list[list[str]] = []
        self.spawned: list[tuple[list[str], dict[str, str], bool]] = []
        self.failing = failing

    def runner(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        self.ran.append(argv)
        code = 1 if any(word in argv for word in self.failing) else 0
        return subprocess.CompletedProcess(argv, code, stdout="boom\n" if code else "")

    def spawner(self, argv: list[str], env: dict[str, str], windows: bool) -> None:
        self.spawned.append((argv, env, windows))


def go(platform: str, calls: Calls, which: str | None = "/usr/bin/systemd-run", **env: str):
    return launch(
        HELPER,
        env or {"PATH": "/bin"},
        platform=platform,
        runner=calls.runner,
        spawner=calls.spawner,
        which=lambda name: which,
    )


def test_linux_runs_the_helper_as_a_transient_unit() -> None:
    calls = Calls()
    done = go("linux", calls, HOME="/root", PATH="/bin", SECRET="x", UV_TOOL_DIR="/t")
    assert done.how == "systemd-run"
    assert calls.spawned == []
    argv = calls.ran[0]
    assert argv[:6] == ["systemd-run", "--unit", "athena-update", "--collect", "--quiet", argv[5]]
    assert argv[-3:] == HELPER
    setenv = [a for a in argv if a.startswith("--setenv=")]
    # What uv needs to find its cache, and nothing else from the server's environment.
    assert setenv == ["--setenv=HOME=/root", "--setenv=PATH=/bin", "--setenv=UV_TOOL_DIR=/t"]


def test_linux_without_systemd_run_starts_a_new_session() -> None:
    calls = Calls()
    assert go("linux", calls, which=None).how == "session"
    assert calls.ran == [] and calls.spawned[0][0] == HELPER and calls.spawned[0][2] is False


def test_a_failing_systemd_run_is_reported_and_nothing_else_is_tried() -> None:
    calls = Calls(failing=("systemd-run",))
    with pytest.raises(LaunchError, match="boom"):
        go("linux", calls)
    assert calls.spawned == []


def test_macos_starts_a_new_session() -> None:
    calls = Calls()
    assert go("darwin", calls).how == "session"
    assert calls.ran == [] and calls.spawned[0][0] == HELPER


def test_windows_creates_and_runs_a_one_shot_task() -> None:
    calls = Calls()
    assert go("win32", calls).how == "scheduled task"
    create, run = calls.ran
    assert create[:4] == ["schtasks", "/Create", "/TN", "AthenaUpdate"]
    assert create[create.index("/SC") + 1] == "ONCE" and "/ST" in create
    assert create[create.index("/RL") + 1] == "LIMITED" and "/F" in create
    command = create[create.index("/TR") + 1]
    assert command == '"/py/python" "-I" "/data/updates/run/update_helper.py"'
    assert "-m athena serve" not in command  # WINDOWS_STOP_SERVER must not match the helper
    assert run == ["schtasks", "/Run", "/TN", "AthenaUpdate"]
    assert calls.spawned == []


def test_windows_falls_back_to_a_detached_process_when_the_task_fails() -> None:
    calls = Calls(failing=("/Run",))
    done = go("win32", calls)
    assert done.how.startswith("detached process") and "boom" in done.how
    assert calls.spawned[0][0] == HELPER and calls.spawned[0][2] is True


def test_windows_task_command_line_limit_falls_back_too() -> None:
    long = ["C:/" + "x" * 300 + "/python.exe", "-I", "h.py"]
    calls = Calls()
    done = launch(long, {}, platform="win32", runner=calls.runner, spawner=calls.spawner)
    assert done.how.startswith("detached process") and "schtasks allows" in done.how
    assert calls.ran == []


def test_only_windows_has_cleanup() -> None:
    assert update_launch.cleanup_steps("linux") == []
    assert update_launch.cleanup_steps("darwin") == []
    (step,) = update_launch.cleanup_steps("win32")
    assert step["argv"] == ["schtasks", "/Delete", "/TN", "AthenaUpdate", "/F"]
    assert step["ignore_errors"] is True


def test_popen_detached_uses_all_devnull_handles_and_no_inherited_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: seen.append(kw))
    update_launch.popen_detached(["x"], {"A": "1"}, windows=False)
    update_launch.popen_detached(["x"], {"A": "1"}, windows=True)
    posix, windows = seen
    for options in seen:
        assert options["stdin"] is options["stdout"] is options["stderr"] is subprocess.DEVNULL
        assert options["close_fds"] is True and options["env"] == {"A": "1"}
    assert posix["start_new_session"] is True and "creationflags" not in posix
    assert "start_new_session" not in windows
    detached = getattr(subprocess, "DETACHED_PROCESS", 0)
    assert windows["creationflags"] & detached == detached
