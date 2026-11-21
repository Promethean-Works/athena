"""The `athena` command."""

import argparse
import contextlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import psutil

from athena import __version__, restart
from athena.config import SECTIONS, default_data_dir

SHUTDOWN_GRACE_SECONDS = 5

# A background server started with `athena start` writes its pid here so `athena stop`
# can find it. Lives inside the data dir so each data dir tracks its own server.
PID_FILE_NAME = "athena.pid"


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from athena.config import Settings

    # Settings are read from the environment so they also reach the --reload worker.
    # A flag only overrides athena.json when it's given.
    if args.host is not None:
        os.environ["ATHENA_HOST"] = args.host
    if args.port is not None:
        os.environ["ATHENA_PORT"] = str(args.port)
    os.environ["ATHENA_DATA_DIR"] = str(args.data_dir)
    os.environ["ATHENA_LOG_TO_FILE"] = "1"
    Path(args.data_dir).mkdir(parents=True, exist_ok=True)
    if not _settings_file_ok(Path(args.data_dir)):
        return 1
    # `--reload` has its own worker process and can't restart itself: run it as before.
    # Otherwise this process is the supervisor and the server runs in a child, so that
    # "Restart Athena" works the same under every service manager (see athena/restart.py).
    if not args.reload and os.environ.get(restart.CHILD_ENV) != "1":
        return _supervise(args)
    settings = Settings(data_dir=Path(args.data_dir))
    options = {
        "factory": True,
        "host": settings.host,
        "port": settings.port,
        "log_config": None,  # athena.logging_setup configures logging in create_app
        # SSE streams (live stats, logs) never end on their own; without a timeout an
        # open dashboard keeps the server from stopping (and a service restart hangs).
        "timeout_graceful_shutdown": SHUTDOWN_GRACE_SECONDS,
    }
    if args.reload:
        uvicorn.run("athena.main:create_app", reload=True, **options)
        return 0
    server = uvicorn.Server(uvicorn.Config("athena.main:create_app", **options))
    restart.register(server)
    _stop_with_parent(server)
    server.run()
    return restart.RESTART_EXIT_CODE if restart.requested() else 0


def _stop_with_parent(server: object) -> None:
    """Stop the server when the supervisor is gone (it was killed, not asked to stop).

    A killed supervisor (Windows has no SIGTERM to forward) would leave this child
    holding the port with nobody to restart it.
    """
    import threading
    import time

    parent_pid = os.getppid()

    def watch() -> None:
        while True:
            time.sleep(2)
            if os.getppid() != parent_pid or not psutil.pid_exists(parent_pid):
                server.should_exit = True  # type: ignore[attr-defined]
                return

    threading.Thread(target=watch, name="athena-parent-watch", daemon=True).start()


def _supervise(args: argparse.Namespace) -> int:
    """Run the server in a child process and start it again when it asks for a restart.

    The child is `athena serve` with `ATHENA_SERVE_CHILD=1`. Exit code 75 means
    "restart"; any other code ends the supervisor with the same code, so a crash or an
    invalid athena.json isn't retried in a loop. Each start re-reads athena.json.
    """
    import signal

    cmd = [sys.executable, "-m", "athena", "serve", "--data-dir", str(args.data_dir)]
    env = {**os.environ, restart.CHILD_ENV: "1"}
    stopping = False
    child: subprocess.Popen | None = None

    def stop(signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True
        if child is not None and child.poll() is None:
            # Forward it: the child shuts down gracefully and exits.
            with contextlib.suppress(OSError):
                child.send_signal(signum)

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        while True:
            child = subprocess.Popen(cmd, env=env)
            code = child.wait()
            if stopping or code != restart.RESTART_EXIT_CODE:
                return code
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _settings_file_ok(data_dir: Path, starting: bool = True) -> bool:
    """Whether athena.json is valid; prints what's wrong with it if not."""
    from athena.settings_file import SettingsFile, SettingsFileError

    settings_file = SettingsFile(data_dir)
    try:
        settings_file.read()
    except SettingsFileError as exc:
        lead = "Athena can't start: " if starting else ""
        print(f"error: {lead}{exc.path} is invalid.", file=sys.stderr)
        for problem in exc.problems:
            print(f"  {problem}", file=sys.stderr)
        backup = settings_file.backup_path
        hint = f" (the previous version is {backup.name})" if backup.is_file() else ""
        print(f"Fix it in an editor{hint} and try again.", file=sys.stderr)
        return False
    except PermissionError as exc:
        hint = " (run it with sudo, as the service runs as root)" if _service_is_root() else ""
        print(f"error: can't read {exc.filename}: {exc.strerror}{hint}", file=sys.stderr)
        return False
    return True


def _openapi(args: argparse.Namespace) -> int:
    import tempfile

    from athena.config import Settings
    from athena.main import create_app

    # Exporting the schema must not touch the real data dir (e.g. /var/lib/athena,
    # which needs root), so build the app against a throwaway one.
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(Settings(data_dir=Path(tmp)))
        schema = json.dumps(app.openapi(), indent=2) + "\n"
        app.state.db.engine.dispose()  # release the SQLite file so Windows can delete it
    if args.output:
        Path(args.output).write_text(schema, encoding="utf-8")
    else:
        sys.stdout.write(schema)
    return 0


def _service(args: argparse.Namespace) -> int:
    from athena.service import ServiceSpec, build_install, build_status, build_uninstall, execute
    from athena.service.platforms import UnsupportedPlatformError

    try:
        if args.service_command == "install":
            if sys.platform.startswith("linux") and os.geteuid() != 0 and not args.dry_run:  # type: ignore[attr-defined]
                print(
                    "error: on Linux the Athena service is installed as root (use sudo)",
                    file=sys.stderr,
                )
                return 1
            spec = ServiceSpec(python=Path(sys.executable), data_dir=Path(args.data_dir))
            plan = build_install(spec)
            if args.port is not None and not _set_port(
                Path(args.data_dir), args.port, args.dry_run
            ):
                return 1
        elif args.service_command == "uninstall":
            plan = build_uninstall()
        else:
            plan = build_status()
    except UnsupportedPlatformError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return execute(plan, dry_run=getattr(args, "dry_run", False))


def _set_port(data_dir: Path, port: int, dry_run: bool) -> bool:
    """Save `server.port` in athena.json (the service itself is installed without one)."""
    from athena.settings_file import SettingsFile, SettingsFileError

    settings_file = SettingsFile(data_dir)
    if not 1 <= port <= 65535:
        print(f"error: {port} isn't a port (1-65535)", file=sys.stderr)
        return False
    if dry_run:
        print(f"  [dry-run] set server.port to {port} in {settings_file.path}")
        return True
    try:
        server = settings_file.read().server
        data_dir.mkdir(parents=True, exist_ok=True)
        settings_file.load()
        settings_file.save("server", server.model_copy(update={"port": port}))
    except SettingsFileError:
        _settings_file_ok(data_dir, starting=False)  # prints the problems
        return False
    print(f"==> saved server.port = {port} in {settings_file.path}")
    return True


def _read_new_password(args: argparse.Namespace) -> str | None:
    if args.password_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    import getpass

    first = getpass.getpass("New password: ")
    if first != getpass.getpass("Repeat password: "):
        print("error: passwords don't match", file=sys.stderr)
        return None
    return first


def _reset_password(args: argparse.Namespace) -> int:
    """Recovery for a forgotten admin password. Runs on the server, as the service's user."""
    from sqlalchemy.exc import OperationalError
    from sqlmodel import Session, select

    from athena.auth.service import MIN_PW_LENGTH, set_password
    from athena.db import Database, User

    db_path = Path(args.data_dir) / "athena.db"
    if not db_path.is_file():
        print(
            f"error: no Athena database at {db_path}. Pass --data-dir, or finish setup "
            "in the web UI first.",
            file=sys.stderr,
        )
        return 1
    database = Database(db_path)
    try:
        database.migrate()
        with Session(database.engine) as db:
            users = db.exec(select(User)).all()
            if args.username:
                user = next((u for u in users if u.username == args.username), None)
            elif len(users) == 1:
                user = users[0]
            else:
                names = ", ".join(u.username for u in users) or "none"
                print(f"error: pass --username (accounts: {names})", file=sys.stderr)
                return 1
            if user is None:
                print(f"error: no account named {args.username!r}", file=sys.stderr)
                return 1
            password = _read_new_password(args)
            if password is None:
                return 1
            if len(password) < MIN_PW_LENGTH:
                print(
                    f"error: password must be at least {MIN_PW_LENGTH} characters",
                    file=sys.stderr,
                )
                return 1
            set_password(db, user, password)
            print(f"Password for {user.username!r} reset. All of its sessions were signed out.")
            return 0
    except (OperationalError, PermissionError) as exc:
        hint = " (run it with sudo, as the service runs as root)" if _service_is_root() else ""
        print(f"error: can't open {db_path}: {exc}{hint}", file=sys.stderr)
        return 1
    finally:
        database.engine.dispose()


# ---------------------------------------------------------------- background server (start/stop)


def _pid_file(data_dir: Path) -> Path:
    return data_dir / PID_FILE_NAME


def _read_pid(data_dir: Path) -> int | None:
    pf = _pid_file(data_dir)
    if not pf.is_file():
        return None
    try:
        return int(pf.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def _write_pid(data_dir: Path, pid: int) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    _pid_file(data_dir).write_text(str(pid), encoding="utf-8")


def _remove_pid(data_dir: Path) -> None:
    _pid_file(data_dir).unlink(missing_ok=True)


def _is_running(pid: int) -> bool:
    try:
        return psutil.pid_exists(pid)
    except Exception:
        return False


def _stop_process(pid: int) -> bool:
    """SIGTERM the process, then SIGKILL if it doesn't exit within 10 s.

    Returns True once the process is gone.
    """
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return True
    proc.terminate()
    try:
        proc.wait(timeout=10)
        return True
    except psutil.TimeoutExpired:
        proc.kill()
        with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
            proc.wait(timeout=5)
    return not _is_running(pid)


def _detached_kwargs() -> dict:
    """Keyword args for Popen to detach the server from this process."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _start(args: argparse.Namespace) -> int:
    """Start the server in the background and write its pid file."""
    data_dir: Path = args.data_dir
    pid = _read_pid(data_dir)
    if pid is not None and _is_running(pid):
        print(f"athena is already running (pid {pid})", file=sys.stderr)
        return 1
    data_dir.mkdir(parents=True, exist_ok=True)
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "athena.log"
    cmd = [
        sys.executable,
        "-m",
        "athena",
        "serve",
        "--data-dir",
        str(data_dir),
    ]
    if args.host is not None:
        cmd += ["--host", args.host]
    if args.port is not None:
        cmd += ["--port", str(args.port)]
    with open(log_file, "ab", buffering=0) as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=log, **_detached_kwargs())
    _write_pid(data_dir, proc.pid)
    print(f"athena started (pid {proc.pid}); logs: {log_file}")
    return 0


def _stop(args: argparse.Namespace) -> int:
    """Stop the background server tracked by the pid file."""
    data_dir: Path = args.data_dir
    pid = _read_pid(data_dir)
    if pid is None:
        print("athena is not running (no pid file)", file=sys.stderr)
        return 1
    if not _is_running(pid):
        _remove_pid(data_dir)
        print("athena is not running (stale pid file removed)", file=sys.stderr)
        return 1
    if _stop_process(pid):
        _remove_pid(data_dir)
        print(f"athena (pid {pid}) stopped")
        return 0
    print(f"error: couldn't stop athena (pid {pid})", file=sys.stderr)
    return 1


# ---------------------------------------------------------------- doctor


def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _docker_available() -> tuple[bool, str]:
    try:
        out = subprocess.run(["docker", "--version"], capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False, "docker not found"
    if out.returncode != 0:
        return False, f"docker failed ({out.returncode})"
    return True, out.stdout.strip() or out.stderr.strip()


def _doctor(args: argparse.Namespace) -> int:
    """Run host/server diagnostics and print a report."""
    from pydantic import ValidationError

    from athena.config import ServerSettings, Settings

    data_dir: Path = args.data_dir
    try:
        effective = Settings(data_dir=data_dir)
    except ValidationError:  # a bad server value: the settings row below says which
        effective = ServerSettings()  # type: ignore[assignment]
    host = args.host if args.host is not None else effective.host
    port = args.port if args.port is not None else effective.port
    results: list[tuple[str, str, str]] = []  # name, status (ok/warn/fail), message

    # 1. athena running?
    pid = _read_pid(data_dir)
    if pid is not None and _is_running(pid):
        results.append(("athena", "ok", f"running (pid {pid})"))
    elif pid is not None:
        results.append(("athena", "fail", f"stale pid file (pid {pid} not running)"))
    else:
        results.append(("athena", "warn", "not running (no pid file)"))

    # 2. data dir
    if data_dir.is_dir():
        if os.access(data_dir, os.W_OK):
            results.append(("data dir", "ok", f"{data_dir} (writable)"))
        else:
            results.append(("data dir", "fail", f"{data_dir} (not writable)"))
    else:
        results.append(("data dir", "warn", f"{data_dir} does not exist"))

    # 3. database
    db_path = data_dir / "athena.db"
    if db_path.is_file():
        results.append(("database", "ok", str(db_path)))
    else:
        results.append(("database", "warn", "no database yet (run 'athena serve')"))

    # 3b. athena.json
    results.append(_settings_check(data_dir))

    # 4. port reachable
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    if _port_open(probe_host, port):
        results.append(("port", "ok", f"{probe_host}:{port} reachable"))
    else:
        results.append(("port", "warn", f"{probe_host}:{port} not listening"))

    # 5. docker
    ok, msg = _docker_available()
    results.append(("docker", "ok" if ok else "warn", msg))

    # 6. disk space on the data dir
    check_dir = data_dir if data_dir.is_dir() else data_dir.parent
    try:
        usage = psutil.disk_usage(str(check_dir))
        free_gb = usage.free / (1024**3)
        total_gb = usage.total / (1024**3)
        results.append(
            (
                "disk",
                "fail" if free_gb < 0.5 else "ok",
                f"{free_gb:.1f} GB free of {total_gb:.0f} GB on {check_dir}",
            )
        )
    except OSError as exc:
        results.append(("disk", "fail", f"can't read disk usage: {exc}"))

    # 7. system service
    try:
        from athena.service import build_status

        plan = build_status()
        code = subprocess.run(
            plan.steps[0].argv, capture_output=True, text=True, timeout=10
        ).returncode
        results.append(("service", "ok" if code == 0 else "warn", f"system service ({code})"))
    except Exception as exc:  # pragma: no cover - platform specific
        results.append(("service", "warn", f"couldn't check: {exc}"))

    # Print report
    worst = "ok"
    for _, status, _ in results:
        if status == "fail":
            worst = "fail"
        elif status == "warn" and worst == "ok":
            worst = "warn"

    print(f"== athena doctor (data dir: {data_dir}) ==")
    for name, status, message in results:
        tag = {"ok": "[ok]", "warn": "[warn]", "fail": "[fail]"}[status]
        print(f"{tag} {name:<12} {message}")
    print()

    return {"ok": 0, "warn": 0, "fail": 1}[worst]


# ---------------------------------------------------------------- config


def _settings_check(data_dir: Path) -> tuple[str, str, str]:
    """athena.json's row in `athena doctor`."""
    from athena.settings_file import SettingsFile, SettingsFileError

    settings_file = SettingsFile(data_dir)
    if not settings_file.path.is_file():
        return ("settings", "warn", f"no {settings_file.path.name} yet (run 'athena serve')")
    try:
        settings_file.read()
    except SettingsFileError as exc:
        more = f" (+{len(exc.problems) - 1} more)" if len(exc.problems) > 1 else ""
        return ("settings", "fail", f"{exc.problems[0]}{more}; see 'athena config check'")
    except PermissionError as exc:
        hint = " (run doctor with sudo)" if _service_is_root() else ""
        return ("settings", "fail", f"can't read {exc.filename}: {exc.strerror}{hint}")
    return ("settings", "ok", str(settings_file.path))


def _redact_url(url: str) -> str:
    """A database URL fit to print: user, host, port and path only (no secret, no query)."""
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port is not None:
        host += f":{parts.port}"
    user = f"{parts.username}:***@" if parts.username else ""
    query = "***" if parts.query else ""
    return urlunsplit((parts.scheme, user + host, parts.path, query, ""))


def _config_path(args: argparse.Namespace) -> int:
    """Print where athena.json is."""
    from athena.settings_file import SettingsFile

    print(SettingsFile(Path(args.data_dir)).path)
    return 0


def _config_show(args: argparse.Namespace) -> int:
    """Print the effective server settings and where each one comes from."""
    from athena.config import ServerSettings, Settings, server_section
    from athena.settings_file import SettingsFile

    data_dir = Path(args.data_dir)
    settings_file = SettingsFile(data_dir)
    if not _settings_file_ok(data_dir, starting=False):
        return 1
    in_file = server_section(settings_file.path)
    settings = Settings(data_dir=data_dir)
    print(f"settings file: {settings_file.path}")
    print(f"data_dir = {data_dir}  (--data-dir or the default; never in the file)")
    for field in ServerSettings.model_fields:
        value = getattr(settings, field)
        if field == "durable_execution_database_url" and value:
            value = _redact_url(value)
        if f"ATHENA_{field.upper()}" in os.environ:
            source = f"env ATHENA_{field.upper()}"
        elif field in in_file:
            source = "file"
        else:
            source = "default"
        print(f"{field} = {value}  ({source})")
    print("Other settings (system, https, ai, webdav) are in the file; edit it, then restart.")
    return 0


def _config_check(args: argparse.Namespace) -> int:
    """Check athena.json the way `athena serve` does."""
    from athena.settings_file import SettingsFile

    data_dir = Path(args.data_dir)
    if not _settings_file_ok(data_dir, starting=False):
        return 1
    path = SettingsFile(data_dir).path
    print(f"{path} is valid" if path.is_file() else f"no {path} yet: Athena will use defaults")
    return 0


def _config_reset(args: argparse.Namespace) -> int:
    """Put one section of athena.json back to its defaults."""
    from athena.settings_file import SettingsFile, SettingsFileError

    data_dir = Path(args.data_dir)
    settings_file = SettingsFile(data_dir)
    try:
        settings_file.reset(args.section)
    except FileNotFoundError:
        print(
            f"error: no {settings_file.path}: nothing to reset. Pass --data-dir.", file=sys.stderr
        )
        return 1
    except SettingsFileError as exc:
        print(
            f"error: can't reset {args.section}: the rest of the file is invalid too.",
            file=sys.stderr,
        )
        for problem in exc.problems:
            print(f"  {problem}", file=sys.stderr)
        print("Fix those (or reset their sections too) and try again.", file=sys.stderr)
        return 1
    except PermissionError as exc:
        hint = " (run it with sudo, as the service runs as root)" if _service_is_root() else ""
        print(f"error: can't write {exc.filename}: {exc.strerror}{hint}", file=sys.stderr)
        return 1
    backup = settings_file.backup_path.name
    print(f"{args.section} is back to its defaults (the previous file is {backup}).")
    print("Restart Athena to use them.")
    return 0


def _service_is_root() -> bool:
    """Whether the system service runs as root (Linux), so its files need sudo."""
    return sys.platform.startswith("linux")


# ---------------------------------------------------------------- https


def _https(args: argparse.Namespace) -> int:
    """`athena https status|off`: the way back in if HTTPS settings lock you out."""
    from athena.https import local_ca
    from athena.https import settings as https_settings
    from athena.settings_file import SettingsFile, SettingsFileError

    data_dir = Path(args.data_dir)
    settings_file = SettingsFile(data_dir)
    if not settings_file.path.is_file():
        print(
            f"error: no Athena settings at {settings_file.path}. Pass --data-dir.", file=sys.stderr
        )
        return 1
    try:
        current = settings_file.read().https
        if args.https_command == "off":
            settings_file.load()
            https_settings.save(settings_file, current.model_copy(update={"mode": "off"}))
            print(
                "HTTPS is off. Restart Athena (athena service install, or stop and "
                "start it) to serve plain HTTP only."
            )
            return 0
    except SettingsFileError:
        _settings_file_ok(data_dir, starting=False)  # prints the problems
        return 1
    except PermissionError as exc:
        hint = " (run it with sudo, as the service runs as root)" if _service_is_root() else ""
        print(f"error: can't open {exc.filename}: {exc.strerror}{hint}", file=sys.stderr)
        return 1
    print(f"mode:     {current.mode}")
    print(f"port:     {current.port}")
    print(f"redirect: {'on' if current.redirect else 'off'}")
    paths = local_ca.tls_paths(data_dir)
    if current.mode == "letsencrypt":
        from athena.https.letsencrypt import le_paths

        cert = local_ca.load_cert(le_paths(paths)[0])
    else:
        cert = local_ca.load_cert(paths.cert)
    if current.mode != "off" and cert is not None:
        dns, ips = local_ca.cert_names(cert)
        names = ", ".join([*sorted(dns), *(str(ip) for ip in sorted(ips, key=str))])
        print(f"expires:  {cert.not_valid_after_utc:%Y-%m-%d}")
        print(f"names:    {names}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="athena", description="Athena home server")
    parser.add_argument("--version", action="version", version=f"athena {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the server")
    serve.add_argument("--host", help="overrides server.host in athena.json")
    serve.add_argument("--port", type=int, help="overrides server.port in athena.json")
    serve.add_argument("--data-dir", type=Path, default=default_data_dir())
    serve.add_argument("--reload", action="store_true", help="reload on code changes (development)")
    serve.set_defaults(func=_serve)

    openapi = sub.add_parser("openapi", help="print or write the OpenAPI schema")
    openapi.add_argument("--output", "-o", type=Path)
    openapi.set_defaults(func=_openapi)

    service = sub.add_parser("service", help="manage the Athena system service")
    service_sub = service.add_subparsers(dest="service_command", required=True)
    install = service_sub.add_parser("install", help="register Athena to start automatically")
    install.add_argument("--data-dir", type=Path, default=default_data_dir())
    install.add_argument("--port", type=int, help="save it as server.port in athena.json")
    install.add_argument("--dry-run", action="store_true")
    uninstall = service_sub.add_parser("uninstall", help="remove the registration")
    uninstall.add_argument("--dry-run", action="store_true")
    service_sub.add_parser("status", help="show service status")
    service.set_defaults(func=_service)

    admin = sub.add_parser("admin", help="account recovery")
    admin_sub = admin.add_subparsers(dest="admin_command", required=True)
    reset = admin_sub.add_parser(
        "reset-password",
        help="set a new password for an account (signs it out everywhere)",
    )
    reset.add_argument("--data-dir", type=Path, default=default_data_dir())
    reset.add_argument("--username", help="needed only when there's more than one account")
    reset.add_argument(
        "--password-stdin", action="store_true", help="read the new password from stdin"
    )
    reset.set_defaults(func=_reset_password)

    background = sub.add_parser("start", help="start the server in the background")
    background.add_argument("--host", help="overrides server.host in athena.json")
    background.add_argument("--port", type=int, help="overrides server.port in athena.json")
    background.add_argument("--data-dir", type=Path, default=default_data_dir())
    background.set_defaults(func=_start)

    stop = sub.add_parser("stop", help="stop the background server")
    stop.add_argument("--data-dir", type=Path, default=default_data_dir())
    stop.set_defaults(func=_stop)

    doctor = sub.add_parser("doctor", help="run host/server diagnostics")
    doctor.add_argument("--host", help="default: server.host from athena.json")
    doctor.add_argument("--port", type=int, help="default: server.port from athena.json")
    doctor.add_argument("--data-dir", type=Path, default=default_data_dir())
    doctor.set_defaults(func=_doctor)

    config = sub.add_parser("config", help="find, check or reset athena.json (the settings file)")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    for name, func, help_text in (
        ("path", _config_path, "print where athena.json is"),
        ("show", _config_show, "print the server settings and where each comes from"),
        ("check", _config_check, "check athena.json the way 'athena serve' does"),
        ("reset", _config_reset, "put one section back to its defaults (keeps a .bak)"),
    ):
        cmd = config_sub.add_parser(name, help=help_text)
        cmd.add_argument("--data-dir", type=Path, default=default_data_dir())
        if name == "reset":
            cmd.add_argument("section", choices=SECTIONS)
        cmd.set_defaults(func=func)

    https = sub.add_parser("https", help="show HTTPS settings, or turn HTTPS off")
    https_sub = https.add_subparsers(dest="https_command", required=True)
    for name, help_text in (
        ("status", "show the HTTPS mode, port and certificate"),
        ("off", "turn HTTPS off (takes effect when Athena restarts)"),
    ):
        cmd = https_sub.add_parser(name, help=help_text)
        cmd.add_argument("--data-dir", type=Path, default=default_data_dir())
    https.set_defaults(func=_https)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
