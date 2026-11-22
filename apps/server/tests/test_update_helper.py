"""The self-update helper, in-process, with fake commands and a fake health server."""

import hashlib
import io
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from athena import update_helper
from athena.update_helper import Helper

PY = sys.executable


def write_file(code: str) -> list[str]:
    return [PY, "-c", code]


class World:
    """A fake install: `installed.txt` holds the version, `started.txt` the process id."""

    def __init__(self, tmp_path: Path) -> None:
        self.dir = tmp_path
        self.data = tmp_path / "data"
        self.updates = self.data / "updates"
        self.data.mkdir()
        self.updates.mkdir()
        (self.dir / "installed.txt").write_text("0.1.0")
        (self.dir / "started.txt").write_text("old-process")
        (self.data / "athena.db").write_bytes(b"old database")
        (self.data / "athena.json").write_text("{}")
        (self.data / "secret.key").write_text("key")
        self.saved = self.updates / "pre-0.1.0"
        self.saved.mkdir()
        (self.saved / "athena.db").write_bytes(b"old database")
        (self.saved / "athena.json").write_text("{}")
        (self.saved / "secret.key").write_text("key")
        self.new_wheel = self.updates / "new.whl"
        self.new_wheel.write_bytes(b"new wheel")
        self.old_wheel = self.updates / "old.whl"
        self.old_wheel.write_bytes(b"old wheel")
        self.counter = 0
        world = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                started = world.dir / "started.txt"
                if not started.exists():
                    self.send_response(503)
                    self.end_headers()
                    return
                body = json.dumps(
                    {
                        "status": "ok",
                        "version": (world.dir / "installed.txt").read_text(),
                        "started_at": started.read_text(),
                    }
                ).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                return None

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def install(self, version: str, ok: bool = True) -> list[dict]:
        code = f"open({str(self.dir / 'installed.txt')!r}, 'w').write({version!r})"
        if not ok:
            code += "; raise SystemExit(1)"
        return [{"argv": write_file(code), "ignore_errors": False}]

    def start(self, marker: str, ok: bool = True) -> list[dict]:
        code = f"open({str(self.dir / 'started.txt')!r}, 'w').write({marker!r})"
        # A server that migrated the database forward before it was rolled back.
        installed = str(self.dir / "installed.txt")
        db = str(self.data / "athena.db")
        code += (
            f"; open({db!r}, 'wb').write(b'migrated forward') "
            f"if open({installed!r}).read() != '0.1.0' else None"
        )
        if not ok:
            code += "; raise SystemExit(1)"
        return [{"argv": write_file(code), "ignore_errors": False}]

    def stop(self) -> list[dict]:
        marker = str(self.dir / "started.txt")
        code = f"import os; os.path.exists({marker!r}) and os.remove({marker!r})"
        return [{"argv": write_file(code), "ignore_errors": False}]

    def plan(self, **over) -> dict:
        port = self.server.server_address[1]
        plan = {
            "from": "0.1.0",
            "to": "0.2.0",
            "data_dir": str(self.data),
            "updates_dir": str(self.updates),
            "state_file": str(self.updates / "state.json"),
            "log_file": str(self.data / "logs" / "update.log"),
            "lock_file": str(self.updates / "lock"),
            "env": {},
            "health_url": f"http://127.0.0.1:{port}/api/health",
            "health_timeout": 3,
            "poll_interval": 0.1,
            "port": None,
            "old_started_at": "old-process",
            "wheel": {"path": str(self.new_wheel), "sha256": sha(b"new wheel")},
            "stop": self.stop(),
            "install": self.install("0.2.0"),
            "start": self.start("new-process"),
            "fallback_start": self.start("fallback-process"),
            "rollback": {
                "restore": [
                    {"src": str(self.saved / n), "dst": str(self.data / n)}
                    for n in ("athena.db", "athena.json", "secret.key")
                ],
                "wheel": {"path": str(self.old_wheel), "sha256": sha(b"old wheel")},
                "install": self.install("0.1.0"),
            },
        }
        plan.update(over)
        return plan

    def state(self) -> dict:
        return json.loads((self.updates / "state.json").read_text())


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def world(tmp_path: Path):
    w = World(tmp_path)
    yield w
    w.close()


def run(plan: dict) -> int:
    return Helper(plan, out=io.StringIO()).finish()


def test_a_good_update_ends_done(world: World) -> None:
    assert run(world.plan()) == update_helper.EXIT_DONE
    state = world.state()
    assert (state["phase"], state["from"], state["to"], state["error"]) == (
        "done",
        "0.1.0",
        "0.2.0",
        None,
    )
    assert (world.dir / "installed.txt").read_text() == "0.2.0"
    assert not (world.updates / "lock").exists()
    assert "Updated to Athena 0.2.0" in (world.data / "logs" / "update.log").read_text()


def assert_rolled_back(world: World, code: int) -> None:
    assert code == update_helper.EXIT_ROLLED_BACK
    assert world.state()["phase"] == "rolled_back"
    assert (world.dir / "installed.txt").read_text() == "0.1.0"
    # The new version migrated the database; the saved copy came back byte for byte.
    assert (world.data / "athena.db").read_bytes() == b"old database"


def test_a_failed_install_rolls_back(world: World) -> None:
    code = run(world.plan(install=world.install("0.2.0", ok=False)))
    assert_rolled_back(world, code)
    assert "exit code 1" in world.state()["error"]


def test_a_start_that_never_answers_rolls_back(world: World) -> None:
    # The new server starts but still reports the old version: the health check times out.
    plan = world.plan(install=world.install("0.1.9"), health_timeout=1)
    plan["rollback"]["install"] = world.install("0.1.0")
    code = run(plan)
    assert_rolled_back(world, code)
    assert "didn't come up" in world.state()["error"]


def test_a_start_that_always_fails_ends_failed(world: World) -> None:
    # The same start runs for the rollback, so a start that always fails ends as failed.
    assert run(world.plan(start=world.start("x", ok=False))) == update_helper.EXIT_FAILED


def test_a_start_that_keeps_the_old_process_id_is_not_success(world: World) -> None:
    # Right version, but the start time never changed: it is still the old process.
    plan = world.plan(start=world.start("old-process"), health_timeout=1)
    code = run(plan)
    assert code == update_helper.EXIT_ROLLED_BACK or code == update_helper.EXIT_FAILED
    assert world.state()["phase"] != "done"


def test_a_failed_rollback_is_failed_and_still_tries_to_start(world: World) -> None:
    plan = world.plan(install=world.install("0.2.0", ok=False))
    plan["rollback"]["install"] = world.install("0.1.0", ok=False)
    code = run(plan)
    assert code == update_helper.EXIT_FAILED
    assert world.state()["phase"] == "failed"
    # The fallback start ran: the service isn't left stopped.
    assert (world.dir / "started.txt").read_text() == "fallback-process"
    assert "installer" in (world.data / "logs" / "update.log").read_text()


def test_a_changed_wheel_is_refused_before_anything_is_stopped(world: World) -> None:
    plan = world.plan(wheel={"path": str(world.new_wheel), "sha256": sha(b"something else")})
    code = run(plan)
    assert code == update_helper.EXIT_ABORTED
    assert world.state()["phase"] == "aborted"
    assert "refusing to install it" in world.state()["error"]
    assert (world.dir / "started.txt").read_text() == "old-process"  # never stopped
    assert (world.dir / "installed.txt").read_text() == "0.1.0"


def test_no_rollback_prepared_ends_failed(world: World) -> None:
    plan = world.plan(install=world.install("0.2.0", ok=False))
    plan["rollback"] = {"restore": [], "wheel": None, "install": []}
    assert run(plan) == update_helper.EXIT_FAILED
    assert world.state()["phase"] == "failed"


def test_without_a_service_there_is_nothing_to_stop_or_wait_for(world: World) -> None:
    plan = world.plan(stop=[], start=[], health_url=None, port=None)
    assert run(plan) == update_helper.EXIT_DONE
    assert (world.dir / "installed.txt").read_text() == "0.2.0"


def test_old_downloads_are_pruned_but_the_last_two_stay(world: World) -> None:
    import os

    for i, name in enumerate(["0.0.1", "0.0.2", "0.1.5", "0.2.0"]):
        folder = world.updates / name
        folder.mkdir()
        os.utime(folder, (1000 + i, 1000 + i))
    run(world.plan())
    left = sorted(p.name for p in world.updates.iterdir() if p.name[0].isdigit())
    assert left == ["0.1.5", "0.2.0"]


def test_port_wait_returns_when_nothing_listens(world: World) -> None:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    helper = Helper(world.plan(port=free), out=io.StringIO())
    helper.wait_port_free()
    helper._log.close()


def test_the_helper_imports_only_the_standard_library() -> None:
    import ast

    tree = ast.parse(Path(update_helper.__file__).read_text(encoding="utf-8"))
    names = {
        n.names[0].name.split(".")[0]
        if isinstance(n, ast.Import)
        else (n.module or "").split(".")[0]
        for n in ast.walk(tree)
        if isinstance(n, ast.Import | ast.ImportFrom)
    }
    assert names <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names)


def test_cleanup_runs_last_even_after_a_rollback(world: World) -> None:
    marker = world.dir / "cleaned.txt"
    code = f"open({str(marker)!r}, 'w').write('x')"
    cleanup = [{"argv": write_file(code), "ignore_errors": True}]
    run(world.plan(install=world.install("0.2.0", ok=False), cleanup=cleanup))
    assert marker.read_text() == "x"
    assert not (world.updates / "lock").exists()


def test_a_failing_cleanup_does_not_change_the_result(world: World) -> None:
    cleanup = [{"argv": write_file("raise SystemExit(1)"), "ignore_errors": False}]
    assert run(world.plan(cleanup=cleanup)) == update_helper.EXIT_DONE
    assert world.state()["phase"] == "done"


def test_with_no_argument_the_plan_is_next_to_the_run_folder(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A Windows scheduled task's command line is limited to 261 characters, so the helper
    # (copied to <updates>/run/) finds <updates>/plan.json itself.
    run_dir = world.updates / "run"
    run_dir.mkdir()
    script = run_dir / "update_helper.py"
    script.write_bytes(Path(update_helper.__file__).read_bytes())
    (world.updates / "plan.json").write_text(json.dumps(world.plan()), encoding="utf-8")
    monkeypatch.setattr(update_helper, "__file__", str(script))
    assert update_helper.main([]) == update_helper.EXIT_DONE
    assert world.state()["phase"] == "done"
