"""`athena onboard`: the setup wizard in the terminal (docs/specs/onboarding-wizard.md).

Writes the same settings as the web wizard, straight to the data dir (the database and
athena.json), so it works with Athena stopped and can be run again at any time. Every
prompt has a flag, and `--yes` takes the current value of everything it isn't told.
"""

import argparse
import asyncio
import getpass
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from athena import onboarding
from athena.containers import installers
from athena.containers.runtime import start_command

LANGUAGE = re.compile(r"^(auto|[a-z]{2,3}(-[A-Z]{2})?)$")
USERNAME = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
MIN_PASSWORD = 8
Ask = Callable[[str, str], str]


def _ask(question: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    return input(f"{question}{suffix}: ").strip() or default


def _say(message: str = "") -> None:
    print(message)


def _db_path(data_dir: Path) -> Path:
    return data_dir / "athena.db"


def _step(title: str) -> None:
    _say()
    _say(f"== {title}")


def _account(args: argparse.Namespace, ask: Ask, db) -> bool:
    from athena.auth import service

    _step("Admin account")
    if service.user_count(db) > 0:
        _say("An admin account exists already: skipping.")
        return True
    username = args.username or (ask("Username", "admin") if not args.yes else "admin")
    if not USERNAME.match(username):
        print("error: usernames are 3-64 letters, digits, '_', '.' or '-'", file=sys.stderr)
        return False
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    elif args.yes:
        print("error: --yes needs --password-stdin to create the account", file=sys.stderr)
        return False
    else:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Repeat password: "):
            print("error: passwords don't match", file=sys.stderr)
            return False
    if len(password) < MIN_PASSWORD:
        print(f"error: the password needs at least {MIN_PASSWORD} characters", file=sys.stderr)
        return False
    service.create_user(db, username, password)
    _say(f"Created the admin account {username!r}.")
    return True


def _language(args: argparse.Namespace, ask: Ask, db) -> bool:
    import json

    from sqlmodel import select

    from athena.db import User

    _step("Language")
    user = db.exec(select(User).order_by(User.id)).first()
    if user is None:
        return True
    try:
        appearance = json.loads(user.appearance or "{}")
    except ValueError:
        appearance = {}
    current = appearance.get("language", "auto")
    language = args.language or (
        current if args.yes else ask("UI language (auto, en, pt-BR…)", current)
    )
    if not LANGUAGE.match(language):
        print(f"error: {language!r} isn't a language code (auto, en, pt-BR…)", file=sys.stderr)
        return False
    appearance["language"] = language
    user.appearance = json.dumps(appearance, separators=(",", ":"))
    db.add(user)
    db.commit()
    _say(f"Language: {language}")
    return True


def _run_step(argv: list[str]) -> None:
    _say("$ " + " ".join(argv))
    code = subprocess.run(argv, stdin=subprocess.DEVNULL, check=False).returncode
    if code != 0:
        raise RuntimeError(f"{argv[0]} failed (exit code {code})")


def _runtime(args: argparse.Namespace, ask: Ask) -> bool:
    from athena.platform.detect import detect

    _step("Container runtime")
    manifest = detect()
    cap = manifest.get("containers")
    if cap is not None and cap.available:
        _say(f"Ready: {cap.provider}. {cap.detail or ''}")
        return True
    _say((cap.detail if cap else None) or "No container runtime is ready.")
    managers = {
        c.id.removeprefix("packages.")
        for c in manifest.capabilities
        if c.id.startswith("packages.") and c.available
    }
    options = installers.options_for(manifest.os, manifest.arch, managers, None)
    chosen = args.runtime
    if chosen is None and not args.yes:
        for i, option in enumerate(options, 1):
            tag = f" ({option.tag})" if option.tag else ""
            star = " *" if option.recommended else ""
            how = "" if option.can_install else " - manual steps"
            _say(f"  {i}. {option.label}{tag}{star}{how}")
        _say("  * recommended")
        pick = ask("Install which? (number, Enter to skip)", "")
        if pick.isdigit() and 1 <= int(pick) <= len(options):
            chosen = options[int(pick) - 1].id
    if chosen is None:
        _say("Skipped. Run `athena onboard --runtime <id>` or use Settings later.")
        return True
    option = next((o for o in options if o.id == chosen), None)
    if option is None:
        ids = ", ".join(o.id for o in options)
        print(f"error: {chosen!r} isn't available here (options: {ids})", file=sys.stderr)
        return False
    plan = installers.plan_install(chosen, manifest.os, manifest.arch, managers)
    if plan is None:
        _say(f"Athena can't install {option.label} on this host. Do it by hand:")
        for line in option.manual:
            _say(f"  - {line}")
        return True
    is_root = os.name == "posix" and os.geteuid() == 0
    plan = installers.with_privilege(plan, is_root)

    async def step(argv: list[str]) -> None:
        await asyncio.to_thread(_run_step, argv)

    async def say(line: str) -> None:
        _say(line)

    try:
        asyncio.run(installers.run_plan(plan, step, say))
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return False
    refreshed = detect().get("containers")
    if refreshed is not None and refreshed.available:
        _say(f"Ready: {refreshed.provider}.")
    else:
        command = start_command(refreshed, manifest.os)
        _say(
            "Installed, but it isn't running yet."
            + (f" Start it with: {' '.join(command)}" if command else "")
        )
        if plan.note:
            _say(plan.note)
    return True


def _locations(args: argparse.Namespace, ask: Ask, db) -> bool:
    from athena.db.models import FileLocation
    from athena.files import locations
    from athena.files.paths import BadPath, Conflict

    _step("File locations")
    for loc in locations.all_locations(db):
        _say(f"  {loc.name}: {loc.path}")
    wanted = list(args.location or [])
    if not wanted and not args.yes:
        _say("Add folders for the file manager (Enter to finish).")
        while entry := ask("Name=/absolute/path", ""):
            wanted.append(entry)
    for entry in wanted:
        name, sep, path = entry.partition("=")
        if not sep:
            print(f"error: {entry!r} isn't NAME=PATH", file=sys.stderr)
            return False
        try:
            loc = locations.save(db, FileLocation(name="", path=""), name, path)
        except (BadPath, Conflict) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return False
        _say(f"Added {loc.name}: {loc.path}")
    return True


def _network(args: argparse.Namespace, ask: Ask, data_dir: Path) -> bool:
    from athena.settings_file import SettingsFile, SettingsFileError

    _step("Network")
    settings_file = SettingsFile(data_dir)
    try:
        settings_file.load()
    except SettingsFileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return False
    server = settings_file.section("server")
    host, port = args.host or server.host, args.port or server.port
    if not args.yes:
        if args.host is None:
            local = ask(
                "Reach Athena from other devices? (y/n)", "n" if host == "127.0.0.1" else "y"
            )
            host = "0.0.0.0" if local.lower().startswith("y") else "127.0.0.1"
        if args.port is None:
            raw = ask("Port", str(port))
            port = int(raw) if raw.isdigit() else port
    if host not in ("0.0.0.0", "127.0.0.1") or not 1 <= port <= 65535:
        print("error: host is 0.0.0.0 or 127.0.0.1, port 1-65535", file=sys.stderr)
        return False
    server.host, server.port = host, port
    settings_file.save("server", server)
    _say(f"Athena listens on {host}:{port} (applies when it restarts).")
    _say("HTTPS and remote access are in Settings → HTTPS and Settings → System.")
    return True


def run(args: argparse.Namespace, ask: Ask = _ask) -> int:
    from sqlalchemy.exc import OperationalError
    from sqlmodel import Session

    from athena.db import Database
    from athena.settings_file import SettingsFile, SettingsFileError

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        settings_file = SettingsFile(data_dir)
        settings_file.load()
        if args.reset:
            onboarding.mark(settings_file, False)
            _say("Setup will open again in the web UI (and on the dashboard).")
            return 0
    except SettingsFileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _say("Athena setup. Press Ctrl+C to stop; run it again any time.")
    if _server_running(data_dir):
        _say("Note: Athena is running. Network and language changes apply after a restart.")
    database = Database(_db_path(data_dir))
    try:
        database.migrate()
        with Session(database.engine) as db:
            ok = (
                _account(args, ask, db)
                and _language(args, ask, db)
                and _runtime(args, ask)
                and _locations(args, ask, db)
                and _network(args, ask, data_dir)
            )
    except (OperationalError, PermissionError) as exc:
        print(f"error: can't open {data_dir}: {exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nStopped. Nothing after the last step was changed.", file=sys.stderr)
        return 130
    finally:
        database.engine.dispose()
    if not ok:
        return 1
    onboarding.mark(settings_file, True)
    _say()
    _say("Done. The AI assistant is set up in the web UI: Settings → AI.")
    return 0


def _server_running(data_dir: Path) -> bool:
    from athena import cli

    pid = cli._read_pid(data_dir)
    return pid is not None and cli._is_running(pid)
