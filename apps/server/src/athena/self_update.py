"""Self-update, CLI side: check, download, verify, pre-flight, then hand over to the helper.

`athena update` does steps 1-5 of docs/specs/self-update.md while the old version still
serves (so a failure costs nothing), writes `<data-dir>/updates/plan.json`, and runs
`update_helper.py` (a stdlib-only copy outside the tool venv) which stops the service,
installs the new wheel, starts it, checks `/api/health` and rolls back on any failure.

Everything per OS is a plan of argv lists built by `athena.service.platforms`; nothing here
branches on `sys.platform` except where the helper must outlive this process (Windows).
"""

import asyncio
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import tomllib
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import psutil

from athena import __version__, update_helper, update_launch
from athena import updates as updates_module
from athena.downloads import DownloadError, fetch_bytes, fetch_verified
from athena.service import build_start, build_stop
from athena.service.plan import Plan, Run
from athena.service.platforms import (
    SYSTEMD_UNIT,
    UnsupportedPlatformError,
    launchd_plist_path,
)
from athena.updates import Release, ReleaseError

log = logging.getLogger(__name__)

TOOL_NAME = "athena-server"
PYTHON = "3.13"
UPDATES_DIR = "updates"
STATE_FILE = "state.json"
PLAN_FILE = "plan.json"
LOCK_FILE = "lock"
LOG_NAME = "update.log"
MAX_SUMS_BYTES = 1024 * 1024
MAX_WHEEL_BYTES = 500 * 1024 * 1024
HEALTH_TIMEOUT = 90.0
PREFLIGHT_TIMEOUT = 600.0

EXIT_UPDATED = 0
EXIT_FAILED_BEFORE = 1
EXIT_ROLLED_BACK = update_helper.EXIT_ROLLED_BACK
EXIT_FAILED = update_helper.EXIT_FAILED

Say = Callable[[str], None]


class UpdateError(Exception):
    """A readable reason the update can't go ahead (nothing was stopped)."""


# ---------------------------------------------------------------- the install we run from


@dataclass(frozen=True)
class ToolEnv:
    venv: Path
    tool_dir: Path
    bin_dir: Path | None
    python_dir: Path | None

    @property
    def root(self) -> Path:
        return self.tool_dir.parent

    def env(self) -> dict[str, str]:
        env = {"UV_TOOL_DIR": str(self.tool_dir), "UV_NO_PROGRESS": "1"}
        if self.bin_dir is not None:
            env["UV_TOOL_BIN_DIR"] = str(self.bin_dir)
        if self.python_dir is not None:
            env["UV_PYTHON_INSTALL_DIR"] = str(self.python_dir)
        return env


def tool_env(prefix: Path | None = None) -> ToolEnv:
    """Where this Athena was installed by `uv tool install`, or `UpdateError` when it wasn't."""
    venv = Path(prefix if prefix is not None else sys.prefix)
    receipt = venv / "uv-receipt.toml"
    try:
        data = tomllib.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        raise UpdateError(
            "This Athena wasn't installed with the installer (uv tool), so it can't update "
            "itself. Upgrade it the way you installed it."
        ) from None
    tool = data.get("tool", {})
    names = [r.get("name") for r in tool.get("requirements", []) if isinstance(r, dict)]
    if TOOL_NAME not in names or venv.name != TOOL_NAME:
        raise UpdateError(f"{receipt} isn't the {TOOL_NAME} tool's receipt")
    bin_dir = None
    for entry in tool.get("entrypoints", []):
        install_path = entry.get("install-path") if isinstance(entry, dict) else None
        if isinstance(install_path, str):
            bin_dir = Path(install_path).parent
            break
    root = venv.parent.parent
    python_dir = root / "python"
    return ToolEnv(venv, venv.parent, bin_dir, python_dir if python_dir.is_dir() else None)


def find_uv(tools: ToolEnv, which: Callable[[str], str | None] = shutil.which) -> str | None:
    """`uv`, also where launchd's minimal PATH doesn't look."""
    found = which("uv")
    if found:
        return found
    exe = "uv.exe" if os.name == "nt" else "uv"
    home = Path.home()
    for folder in (
        tools.root / "bin",
        home / ".local" / "bin",
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
    ):
        candidate = folder / exe
        if candidate.is_file():
            return str(candidate)
    return None


def writable(path: Path) -> bool:
    return os.access(path, os.W_OK) if path.exists() else os.access(path.parent, os.W_OK)


def readiness(data_dir: Path, *, uv: str | None = None) -> tuple[str, str] | None:
    """Why this host can't update itself, as (`unsupported` | `needs_privilege`, reason), or
    None when it can. Never raises."""
    try:
        tools = tool_env()
    except UpdateError as exc:
        return "unsupported", str(exc)
    if (uv or find_uv(tools)) is None:
        return "unsupported", "uv wasn't found. Re-run the installer to update."
    if not writable(tools.tool_dir):
        return (
            "needs_privilege",
            f"{tools.tool_dir} isn't writable by this user (run it with sudo?)",
        )
    if not writable(data_dir):
        return "needs_privilege", f"{data_dir} isn't writable by this user (run it with sudo?)"
    if __version__ == "0.0.0":
        return "unsupported", "This is a source build, which has no release to go back to"
    return None


def not_ready_reason(data_dir: Path, *, uv: str | None = None) -> str | None:
    """Why this host can't update itself (None when it can). Never raises."""
    found = readiness(data_dir, uv=uv)
    return found[1] if found else None


def service_installed(platform: str | None = None) -> bool:
    plat = platform or sys.platform
    if plat.startswith("linux"):
        return SYSTEMD_UNIT.exists()
    if plat == "darwin":
        return launchd_plist_path().exists()
    try:
        return (
            subprocess.run(
                ["schtasks", "/Query", "/TN", "Athena"],
                capture_output=True,
                check=False,
                timeout=30,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


# ---------------------------------------------------------------- files and plans


@dataclass(frozen=True)
class Paths:
    data_dir: Path

    @property
    def updates(self) -> Path:
        return self.data_dir / UPDATES_DIR

    def version_dir(self, version: str) -> Path:
        return self.updates / version

    @property
    def previous(self) -> Path:
        return self.updates / "previous"

    def saved(self, version: str) -> Path:
        return self.updates / f"pre-{version}"

    @property
    def run(self) -> Path:
        return self.updates / "run"

    @property
    def plan(self) -> Path:
        return self.updates / PLAN_FILE

    @property
    def state(self) -> Path:
        return self.updates / STATE_FILE

    @property
    def lock(self) -> Path:
        return self.updates / LOCK_FILE

    @property
    def log(self) -> Path:
        return self.data_dir / "logs" / LOG_NAME


def steps_of(plan: Plan) -> list[dict[str, Any]]:
    return [
        {"argv": s.argv, "ignore_errors": s.ignore_errors} for s in plan.steps if isinstance(s, Run)
    ]


def uv_install(uv: str, wheel: Path) -> list[dict[str, Any]]:
    argv = [
        uv,
        "tool",
        "install",
        "--force",
        "--offline",
        "--quiet",
        "--python",
        PYTHON,
        str(wheel),
    ]
    return [{"argv": argv, "ignore_errors": False}]


def build_plan(
    *,
    paths: Paths,
    tools: ToolEnv,
    uv: str,
    release: Release,
    wheel_sha: str,
    previous: tuple[Path, str] | None,
    current: str,
    health_url: str | None,
    port: int | None,
    old_started_at: str | None,
    manage_service: bool,
    platform: str | None = None,
) -> dict[str, Any]:
    """What the helper runs. Pure: built the same on any OS (tested without one)."""
    wheel = paths.version_dir(release.version) / release.wheel_name
    stop = steps_of(build_stop(platform)) if manage_service else []
    # `service install` from the new venv rewrites the unit/plist/task for the new version
    # and restarts it (docs/agents/gotchas/installers.md).
    start = (
        [
            {
                "argv": [
                    str(tools.venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")),
                    "-m",
                    "athena",
                    "service",
                    "install",
                    "--data-dir",
                    str(paths.data_dir),
                ],
                "ignore_errors": False,
            }
        ]
        if manage_service
        else []
    )
    rollback: dict[str, Any] = {"restore": [], "wheel": None, "install": []}
    if previous is not None:
        saved = paths.saved(current)
        rollback = {
            "restore": [
                {"src": str(saved / name), "dst": str(paths.data_dir / name)}
                for name in ("athena.db", "athena.json", "secret.key")
            ],
            "wheel": {"path": str(previous[0]), "sha256": previous[1]},
            "install": uv_install(uv, previous[0]),
        }
    return {
        "from": current,
        "to": release.version,
        "data_dir": str(paths.data_dir),
        "updates_dir": str(paths.updates),
        "state_file": str(paths.state),
        "log_file": str(paths.log),
        "lock_file": str(paths.lock),
        "env": tools.env(),
        "health_url": health_url if manage_service else None,
        "health_timeout": HEALTH_TIMEOUT,
        "poll_interval": 1.0,
        "port": port if manage_service else None,
        "old_started_at": old_started_at,
        "wheel": {"path": str(wheel), "sha256": wheel_sha},
        "stop": stop,
        "install": uv_install(uv, wheel),
        "start": start,
        "fallback_start": steps_of(build_start(platform)) if manage_service else [],
        "rollback": rollback,
        "cleanup": update_launch.cleanup_steps(platform),
    }


def describe_plan(plan: dict[str, Any]) -> list[str]:
    def line(step: dict[str, Any]) -> str:
        return "  " + " ".join(f'"{a}"' if " " in a else a for a in step["argv"])

    lines = [f"Update {plan['from']} -> {plan['to']}", "Stop the service:"]
    lines += [line(s) for s in plan["stop"]] or ["  (no service is installed: nothing to stop)"]
    lines += ["Install:", *(line(s) for s in plan["install"]), "Start the service:"]
    lines += [line(s) for s in plan["start"]] or ["  (restart Athena yourself afterwards)"]
    if plan["health_url"]:
        lines.append(f"Health check: {plan['health_url']} answers {plan['to']} (within 90 s)")
    if plan["rollback"]["install"]:
        lines += ["If anything fails, roll back:", *(line(s) for s in plan["rollback"]["install"])]
    else:
        lines.append("No rollback (--no-rollback)")
    return lines


# ---------------------------------------------------------------- downloading


def parse_sums(text: str, name: str) -> str | None:
    """The hash of `name` in a SHA256SUMS file (`<hash>  <name>` or `<hash> *<name>`)."""
    for line in text.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].strip().lstrip("*") == name:
            digest = parts[0].lower()
            if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest):
                return digest
    return None


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


async def download_release(
    release: Release,
    folder: Path,
    check_url: str,
    say: Say,
    transport: Any = None,
) -> tuple[Path, str]:
    """Download the wheel and SHA256SUMS into `folder` and verify the wheel.

    A missing entry or a mismatch deletes the files and aborts ("refusing to install an
    unverified wheel", the installers' wording). Returns the wheel path and its hash.
    """

    def allowed(url: str) -> bool:
        return updates_module.host_allowed(url, check_url)

    async def note(text: str) -> None:
        say(text)

    shutil.rmtree(folder, ignore_errors=True)
    try:
        sums = await fetch_bytes(
            release.sums_url,
            max_bytes=MAX_SUMS_BYTES,
            allowed=allowed,
            transport=transport,
        )
        expected = parse_sums(sums.decode("utf-8", errors="replace"), release.wheel_name)
        if expected is None:
            raise DownloadError(
                f"{updates_module.SUMS_NAME} has no entry for {release.wheel_name}; "
                "refusing to install an unverified wheel"
            )
        wheel = await fetch_verified(
            release.wheel_url,
            expected,
            max_bytes=MAX_WHEEL_BYTES,
            allowed=allowed,
            log_line=note,
            transport=transport,
        )
    except DownloadError as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise UpdateError(str(exc)) from exc
    write_atomic(folder / updates_module.SUMS_NAME, sums)
    path = folder / release.wheel_name
    write_atomic(path, wheel)
    return path, expected


# ---------------------------------------------------------------- pre-flight and rollback files


def run_checked(argv: list[str], env: dict[str, str], what: str, timeout: float) -> str:
    try:
        done = subprocess.run(
            argv,
            env={**os.environ, **env},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise UpdateError(f"{what}: {exc}") from exc
    if done.returncode != 0:
        tail = (done.stdout + done.stderr).strip().splitlines()[-5:]
        raise UpdateError(f"{what} failed:\n  " + "\n  ".join(tail))
    return done.stdout


def preflight(uv: str, wheel: Path, version: str, data_dir: Path, tools: ToolEnv, say: Say) -> None:
    """Run the new wheel once. This also puts its dependencies in uv's cache, so the swap can
    run with `--offline` (no network failure in the dangerous window)."""
    base = [uv, "tool", "run", "--python", PYTHON, "--from", str(wheel), "athena"]
    out = run_checked(
        [*base, "--version"], tools.env(), "The new version doesn't start", PREFLIGHT_TIMEOUT
    )
    if out.strip() != f"athena {version}":
        raise UpdateError(f"The wheel reports {out.strip()!r}, expected 'athena {version}'")
    say(f"Pre-flight: {out.strip()} starts")
    run_checked(
        [*base, "config", "check", "--data-dir", str(data_dir)],
        tools.env(),
        "The new version rejects athena.json",
        PREFLIGHT_TIMEOUT,
    )


def save_for_rollback(paths: Paths, current: str) -> None:
    """The database (SQLite online backup), athena.json and secret.key, as they are now."""
    saved = paths.saved(current)
    shutil.rmtree(saved, ignore_errors=True)
    saved.mkdir(parents=True)
    db = paths.data_dir / "athena.db"
    if db.is_file():
        source = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            target = sqlite3.connect(saved / "athena.db")
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
    for name in ("athena.json", "secret.key"):
        if (paths.data_dir / name).is_file():
            shutil.copy2(paths.data_dir / name, saved / name)
    for path in (saved, *saved.iterdir()):
        if os.name != "nt":
            path.chmod(0o700 if path.is_dir() else 0o600)


TERMINAL_PHASES = ("done", "rolled_back", "failed", "aborted")
AUDIT_ACTIONS = {
    "done": "system.update.done",
    "rolled_back": "system.update.rolled_back",
    "failed": "system.update.failed",
}
AUDIT_WAIT_SECONDS = 300.0
AUDIT_POLL_SECONDS = 2.0
AUDIT_GRACE_SECONDS = 10.0


def read_state(paths: Paths) -> dict[str, Any] | None:
    """The helper's `state.json`, or None when there is none or it can't be read."""
    try:
        data = json.loads(paths.state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def audit_entry(state: dict[str, Any]) -> tuple[str, str] | None:
    """(action, detail) to audit for a finished update; None while it still runs, for
    one that stopped before the swap, or one that was already audited."""
    action = AUDIT_ACTIONS.get(str(state.get("phase")))
    if action is None or state.get("audited"):
        return None
    detail = f"{state.get('from')} -> {state.get('to')}"
    if state.get("error"):
        detail += f": {state['error']}"
    return action, detail[:500]


async def audit_outcome(
    paths: Paths,
    record: Callable[[str, str], None],
    *,
    wait: float = AUDIT_WAIT_SECONDS,
    poll: float = AUDIT_POLL_SECONDS,
) -> bool:
    """Audit how the last update ended, once. The helper that did the swap outlives the old
    server, so the server that comes up afterwards writes the entry. It may start a second
    before the helper writes the final phase, so wait for it while the helper still holds
    the lock. Returns whether an entry was written."""
    clock = asyncio.get_running_loop().time
    began = clock()
    while True:
        state = await asyncio.to_thread(read_state, paths)
        if state is None or state.get("audited"):
            return False
        entry = audit_entry(state)
        if entry is not None:
            record(*entry)
            state["audited"] = True
            await asyncio.to_thread(write_atomic, paths.state, json.dumps(state, indent=2).encode())
            return True
        if state.get("phase") in TERMINAL_PHASES:
            return False  # aborted before the swap: nothing to audit
        helper_gone = await asyncio.to_thread(lock_holder, paths) is None
        if clock() - began > (AUDIT_GRACE_SECONDS if helper_gone else wait):
            return False  # an interrupted update (the next start says so), or the wait ran out
        await asyncio.sleep(poll)


def lock_holder(paths: Paths) -> int | None:
    """The PID of a running update, ignoring a stale lock from a dead process."""
    try:
        pid = int(paths.lock.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if psutil.pid_exists(pid) else None


def health_of(url: str) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            data = json.loads(response.read(65536))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def server_address(data_dir: Path) -> tuple[str, int]:
    """Where the service listens: loopback or `server.host`, and `server.port`."""
    from athena.settings_file import SettingsFile, SettingsFileError

    try:
        server = SettingsFile(data_dir).read().server
    except (SettingsFileError, OSError) as exc:
        raise UpdateError(f"{data_dir / 'athena.json'} can't be read: {exc}") from exc
    host = server.host if server.host not in ("", "0.0.0.0", "::") else "127.0.0.1"
    return host, server.port


# ---------------------------------------------------------------- the flow


@dataclass
class Options:
    data_dir: Path
    version: str | None = None
    pre: bool = False
    allow_downgrade: bool = False
    no_rollback: bool = False
    yes: bool = False
    dry_run: bool = False
    check_url: str = ""


def is_current(release: Release, current: str) -> bool:
    return release.version == current


def is_newer_release(release: Release, current: str) -> bool:
    new, old = updates_module.version_key(release.version), updates_module.version_key(current)
    return new is not None and old is not None and new > old


def lookup(opts: Options, **kw: Any) -> Release:
    try:
        return updates_module.resolve(opts.check_url, opts.version, pre=opts.pre, **kw)
    except ReleaseError as exc:
        raise UpdateError(str(exc)) from exc


async def prepare(
    opts: Options, release: Release, say: Say, *, transport: Any = None, **resolve_kw: Any
) -> dict[str, Any]:
    """Steps 2-4 (and the plan). Raises `UpdateError`; nothing is stopped until it returns."""
    paths = Paths(opts.data_dir)
    tools = tool_env()
    uv = find_uv(tools)
    if uv is None:
        raise UpdateError("uv wasn't found. Re-run the installer to update.")
    if (pid := lock_holder(paths)) is not None:
        raise UpdateError(f"Another update is running (process {pid})")
    current = __version__
    if not opts.no_rollback and current == "0.0.0":
        raise UpdateError(
            "This is a source build with no release to go back to (use --no-rollback)"
        )
    # Every file written below lives in the data dir with its permissions.
    paths.updates.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        paths.updates.chmod(0o700)

    say(f"Downloading Athena {release.version}")
    wheel, sha = await download_release(
        release, paths.version_dir(release.version), opts.check_url, say, transport
    )
    await asyncio.to_thread(preflight, uv, wheel, release.version, opts.data_dir, tools, say)

    previous: tuple[Path, str] | None = None
    if not opts.no_rollback:
        say(
            f"Saving the current database and settings, and fetching Athena {current} to go back to"
        )
        try:
            old = await asyncio.to_thread(
                lookup, replace(opts, version=current, pre=False), **resolve_kw
            )
            old_wheel, old_sha = await download_release(
                old, paths.previous, opts.check_url, say, transport
            )
        except UpdateError as exc:
            raise UpdateError(
                f"No release of the current version {current} to go back to ({exc}); "
                "use --no-rollback to update without one"
            ) from exc
        await asyncio.to_thread(preflight, uv, old_wheel, old.version, opts.data_dir, tools, say)
        await asyncio.to_thread(save_for_rollback, paths, current)
        previous = (old_wheel, old_sha)

    manage = await asyncio.to_thread(service_installed)
    host, port = server_address(opts.data_dir)
    health_url = f"http://{host}:{port}/api/health"
    old_health = await asyncio.to_thread(health_of, health_url)
    return build_plan(
        paths=paths,
        tools=tools,
        uv=uv,
        release=release,
        wheel_sha=sha,
        previous=previous,
        current=current,
        health_url=health_url,
        port=port,
        old_started_at=old_health.get("started_at") if old_health else None,
        manage_service=manage,
    )


def helper_command(paths: Paths) -> list[str]:
    """Copy the helper out of the venv and build the command that runs it.

    It's started with `-I` by the base interpreter uv uses (`uv python find`), not the
    venv's python, which holds the venv open.
    """
    paths.run.mkdir(parents=True, exist_ok=True)
    helper = paths.run / "update_helper.py"
    shutil.copy2(update_helper.__file__, helper)
    return [str(helper)]


def base_python(uv: str, tools: ToolEnv) -> str:
    out = run_checked([uv, "python", "find", PYTHON], tools.env(), "uv can't find Python", 60)
    path = out.strip().splitlines()[-1] if out.strip() else ""
    if not path:
        raise UpdateError(f"uv found no Python {PYTHON}")
    return path


def helper_argv(
    plan: dict[str, Any], paths: Paths, tools: ToolEnv, uv: str, *, gui: bool
) -> list[str]:
    """Write the plan and build the helper's command. `gui` picks `pythonw.exe` on Windows (a
    scheduled task must not open a console window). No plan argument: the helper finds
    `plan.json` itself, which keeps the command short enough for `schtasks /TR`."""
    write_atomic(paths.plan, json.dumps(plan, indent=2).encode("utf-8"))
    if os.name != "nt":
        paths.plan.chmod(0o600)
    python = Path(base_python(uv, tools))
    if gui and os.name == "nt" and python.with_name("pythonw.exe").is_file():
        python = python.with_name("pythonw.exe")
    return [str(python), "-I", *helper_command(paths)]


def start_helper(plan: dict[str, Any], paths: Paths, tools: ToolEnv, uv: str) -> int | None:
    """Run the helper for the CLI. Foreground (its output and exit code) everywhere but
    Windows, where this process holds the venv open, so the helper is started detached and we
    exit."""
    argv = helper_argv(plan, paths, tools, uv, gui=False)
    env = {**os.environ, **tools.env()}
    if os.name == "nt":
        update_launch.popen_detached(argv, env, windows=True)
        return None
    return subprocess.run([*argv, str(paths.plan)], env=env, check=False).returncode


def start_detached(
    plan: dict[str, Any], paths: Paths, tools: ToolEnv, uv: str
) -> update_launch.Launched:
    """Start the helper from the server so that it outlives it (`update_launch`)."""
    argv = helper_argv(plan, paths, tools, uv, gui=True)
    try:
        launched = update_launch.launch(argv, {**os.environ, **tools.env()})
    except update_launch.LaunchError as exc:
        raise UpdateError(str(exc)) from exc
    log.info("update helper started: %s", launched.how)  # the E2E reads this from athena.log
    return launched


async def run_from_server(
    opts: Options,
    say: Say,
    handoff: Callable[[], None],
    *,
    transport: Any = None,
    **resolve_kw: Any,
) -> str:
    """The server's side of `POST /api/system/update` (steps 1-5, then the hand-over).

    Resolves, downloads, verifies and pre-flights while this server still serves, starts the
    helper detached and calls `handoff()`, which makes the server exit (the helper stops the
    service itself). Raises `UpdateError` before anything is stopped. Returns the new version.
    """
    release = await asyncio.to_thread(lookup, opts, **resolve_kw)
    if is_current(release, __version__):
        raise UpdateError(f"Athena {__version__} is the latest version")
    if not is_newer_release(release, __version__) and not opts.allow_downgrade:
        raise UpdateError(f"{release.version} isn't newer than {__version__}")
    plan = await prepare(opts, release, say, transport=transport, **resolve_kw)
    paths = Paths(opts.data_dir)
    uv = plan["install"][0]["argv"][0]
    launched = await asyncio.to_thread(start_detached, plan, paths, tool_env(), uv)
    say(f"The update continues without the server ({launched.how}); Athena restarts shortly")
    handoff()
    return release.version


def confirm(question: str, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        raise UpdateError("Not a terminal: pass --yes to update without asking")
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def check(opts: Options, say: Say) -> int:
    """`athena update --check`: current, latest and whether this host can update itself."""
    say(f"Current version: {__version__}")
    try:
        release = lookup(opts)
    except UpdateError as exc:
        say(f"Latest release: unknown ({exc})")
        return EXIT_FAILED_BEFORE
    newer = is_newer_release(release, __version__)
    say(f"Latest release: {release.version}" + (" (newer)" if newer else " (up to date)"))
    reason = not_ready_reason(opts.data_dir)
    say(
        "This host can update itself"
        if reason is None
        else f"This host can't update itself: {reason}"
    )
    return EXIT_UPDATED


def update(opts: Options, say: Say = print, *, transport: Any = None) -> int:  # type: ignore[assignment]
    """`athena update`. Returns the exit code: 0 updated or current, 1 failed before the
    swap, 2 rolled back, 3 failed and not running."""
    try:
        release = lookup(opts)
        current = __version__
        if is_current(release, current):
            say(f"Athena {current} is the latest version")
            return EXIT_UPDATED
        if not is_newer_release(release, current):
            if not opts.allow_downgrade:
                raise UpdateError(
                    f"{release.version} isn't newer than {current} "
                    "(--allow-downgrade installs it; migrations don't go back)"
                )
            say("Warning: downgrading. Database migrations don't go back.")
        if opts.dry_run:
            return _dry_run(opts, release, say)
        if not confirm(
            f"Update Athena {current} -> {release.version}? Apps keep running.", yes=opts.yes
        ):
            say("Cancelled")
            return EXIT_UPDATED
        plan = asyncio.run(prepare(opts, release, say, transport=transport))
    except UpdateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAILED_BEFORE
    paths = Paths(opts.data_dir)
    tools = tool_env()
    uv = plan["install"][0]["argv"][0]
    say("Switching versions: Athena stops for a moment")
    code = start_helper(plan, paths, tools, uv)
    if code is None:
        say(f"The update continues in the background. Follow it in {paths.log}")
        return EXIT_UPDATED
    if code == EXIT_UPDATED:
        if not plan["start"]:
            say("Updated. Athena isn't installed as a service here: restart it yourself.")
    elif code == update_helper.EXIT_ABORTED:
        print(f"Update aborted before Athena was stopped. See {paths.log}", file=sys.stderr)
    elif code == EXIT_ROLLED_BACK:
        print(
            f"Rolled back: Athena {__version__} is running again. See {paths.log}", file=sys.stderr
        )
    else:
        print(
            f"Athena isn't running. See {paths.log}; run the installer again to repair it.",
            file=sys.stderr,
        )
    return code


def _dry_run(opts: Options, release: Release, say: Say) -> int:
    paths = Paths(opts.data_dir)
    try:
        tools = tool_env()
    except UpdateError:
        tools = ToolEnv(Path("<tool venv>"), Path("<tool dir>"), None, None)
    uv = find_uv(tools) or "uv"
    host, port = server_address(opts.data_dir)
    previous = None if opts.no_rollback else (paths.previous / "<current wheel>", "<sha256>")
    try:
        manage = service_installed()
        plan = build_plan(
            paths=paths,
            tools=tools,
            uv=uv,
            release=release,
            wheel_sha="<sha256>",
            previous=previous,
            current=__version__,
            health_url=f"http://{host}:{port}/api/health",
            port=port,
            old_started_at=None,
            manage_service=manage,
        )
    except UnsupportedPlatformError as exc:
        raise UpdateError(str(exc)) from exc
    say("Dry run: nothing is downloaded or changed")
    say(f"Download {release.wheel_url} and check it against {release.sums_url}")
    for line in describe_plan(plan):
        say(line)
    return EXIT_UPDATED
