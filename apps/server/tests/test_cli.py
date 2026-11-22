import io
import json
import os
import subprocess
from pathlib import Path

import psutil
import pytest
from conftest import ADMIN, make_app, signed_in
from fastapi.testclient import TestClient

from athena import restart
from athena.cli import main


def test_openapi_export_does_not_touch_the_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "real-data-dir"
    monkeypatch.setenv("ATHENA_DATA_DIR", str(data_dir))
    out = tmp_path / "openapi.json"
    assert main(["openapi", "--output", str(out)]) == 0
    assert "/api/auth/login" in json.loads(out.read_text())["paths"]
    assert not data_dir.exists()


def test_openapi_export_pins_the_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A release bump must not make packages/api-client stale (CI regenerates and diffs it).
    monkeypatch.setattr("athena.main.__version__", "9.9.9")
    out = tmp_path / "openapi.json"
    assert main(["openapi", "--output", str(out)]) == 0
    assert json.loads(out.read_text())["info"]["version"] == "0.0.0"


NEW_PASSWORD = "a brand new password"


def reset(monkeypatch: pytest.MonkeyPatch, data_dir: Path, *args: str, password: str) -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO(password + "\n"))
    return main(["admin", "reset-password", "--data-dir", str(data_dir), "--password-stdin", *args])


def test_reset_password_replaces_it_and_signs_out_everywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = signed_in(TestClient(make_app(tmp_path)))
    assert client.get("/api/system/info").status_code == 200

    assert reset(monkeypatch, tmp_path / "data", password=NEW_PASSWORD) == 0
    assert "reset" in capsys.readouterr().out

    # The existing browser session is gone.
    assert client.get("/api/system/info").status_code == 401
    # Old password fails, new one works.
    assert client.post("/api/auth/login", json=ADMIN).status_code == 401
    ok = client.post("/api/auth/login", json={**ADMIN, "password": NEW_PASSWORD})
    assert ok.status_code == 200


def test_reset_password_rejects_short_passwords(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    signed_in(TestClient(make_app(tmp_path)))
    assert reset(monkeypatch, tmp_path / "data", password="short") == 1
    assert "at least 8" in capsys.readouterr().err


def test_reset_password_unknown_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    signed_in(TestClient(make_app(tmp_path)))
    code = reset(monkeypatch, tmp_path / "data", "--username", "ghost", password=NEW_PASSWORD)
    assert code == 1
    assert "no account named 'ghost'" in capsys.readouterr().err


def test_reset_password_without_a_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert reset(monkeypatch, tmp_path / "empty", password=NEW_PASSWORD) == 1
    assert "no Athena database" in capsys.readouterr().err
    assert not (tmp_path / "empty").exists()


def test_reset_password_prompts_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    signed_in(TestClient(make_app(tmp_path)))
    answers = iter([NEW_PASSWORD, "something else"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    code = main(["admin", "reset-password", "--data-dir", str(tmp_path / "data")])
    assert code == 1
    assert "don't match" in capsys.readouterr().err


def test_serve_bounds_graceful_shutdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Open SSE streams (the dashboard) must not keep the server from stopping."""
    import uvicorn

    seen: dict = {}
    monkeypatch.setattr(uvicorn.Server, "run", lambda self: seen.update(config=self.config))
    for key in ("ATHENA_HOST", "ATHENA_PORT", "ATHENA_DATA_DIR", "ATHENA_LOG_TO_FILE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(restart.CHILD_ENV, "1")
    monkeypatch.setattr("athena.cli._stop_with_parent", lambda server: None)
    assert main(["serve", "--port", "8499", "--data-dir", str(tmp_path / "d")]) == 0
    assert seen["config"].port == 8499
    assert 0 < seen["config"].timeout_graceful_shutdown <= 10
    restart.register(None)


def test_serve_exits_with_the_restart_code_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import uvicorn

    def run(self: uvicorn.Server) -> None:
        assert restart.request()

    monkeypatch.setattr(uvicorn.Server, "run", run)
    monkeypatch.setenv(restart.CHILD_ENV, "1")
    monkeypatch.setattr("athena.cli._stop_with_parent", lambda server: None)
    code = main(["serve", "--port", "8499", "--data-dir", str(tmp_path / "d")])
    assert code == restart.RESTART_EXIT_CODE
    restart.register(None)


class FakeChild:
    def __init__(self, code: int) -> None:
        self.code = code

    def wait(self) -> int:
        return self.code

    def poll(self) -> int:
        return self.code


def test_supervisor_restarts_on_75_and_stops_on_other_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codes = iter([75, 75, 0])
    starts: list[dict] = []

    def popen(cmd: list[str], env: dict) -> FakeChild:
        starts.append(env)
        return FakeChild(next(codes))

    monkeypatch.delenv(restart.CHILD_ENV, raising=False)
    monkeypatch.setattr(subprocess, "Popen", popen)
    assert main(["serve", "--data-dir", str(tmp_path / "d")]) == 0
    assert len(starts) == 3
    assert all(env[restart.CHILD_ENV] == "1" for env in starts)


def test_supervisor_does_not_retry_a_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    starts: list[int] = []

    def popen(cmd: list[str], env: dict) -> FakeChild:
        starts.append(1)
        return FakeChild(1)

    monkeypatch.delenv(restart.CHILD_ENV, raising=False)
    monkeypatch.setattr(subprocess, "Popen", popen)
    assert main(["serve", "--data-dir", str(tmp_path / "d")]) == 1
    assert len(starts) == 1


def test_a_real_supervised_server_comes_back_after_a_restart(tmp_path: Path) -> None:
    """End to end: the real CLI, a real child, POST /api/system/restart, a new start time."""
    import socket
    import sys
    import time
    import urllib.request

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    data = tmp_path / "data"
    env = {k: v for k, v in os.environ.items() if not k.startswith("ATHENA_")}
    proc = subprocess.Popen(
        [sys.executable, "-m", "athena", "serve", "--port", str(port), "--data-dir", str(data)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def health() -> str | None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
                return json.load(r)["started_at"]
        except OSError:
            return None

    def wait_for(predicate, seconds: float = 40):  # type: ignore[no-untyped-def]
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            value = predicate()
            if value:
                return value
            time.sleep(0.3)
        return None

    try:
        first = wait_for(health)
        assert first, "the server didn't start"
        base = f"http://127.0.0.1:{port}/api"
        setup = urllib.request.Request(
            f"{base}/auth/setup",
            data=json.dumps(ADMIN).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(setup, timeout=10) as r:
            csrf = json.load(r)["csrf_token"]
            cookie = r.headers["Set-Cookie"].split(";")[0]
        restart_req = urllib.request.Request(
            f"{base}/system/restart",
            data=b"",
            method="POST",
            headers={"X-CSRF-Token": csrf, "Cookie": cookie},
        )
        with urllib.request.urlopen(restart_req, timeout=10) as r:
            assert r.status == 202
        second = wait_for(lambda: (h := health()) and h != first and h)
        assert second, "the server didn't come back"
        assert proc.poll() is None  # the supervisor itself keeps running
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()


# ---------------------------------------------------------------- start / stop


class FakeProcess:
    """A fake psutil.Process that records terminate/kill/wait calls."""

    def __init__(self, pid: int, alive: bool = True) -> None:
        self.pid = pid
        self._alive = alive
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True
        self._alive = False

    def kill(self) -> None:
        self.killed = True
        self._alive = False

    def wait(self, timeout: float | None = None) -> None:
        if not self._alive:
            return
        raise psutil.TimeoutExpired("proc", timeout)


def test_start_writes_pid_and_starts_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    started: list[list[str]] = []
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda cmd, **kw: (started.append(cmd), FakePopen(1234))[1],
    )
    monkeypatch.setattr("psutil.pid_exists", lambda pid: False)
    assert main(["start", "--data-dir", str(data_dir)]) == 0
    pid_file = data_dir / "athena.pid"
    assert pid_file.read_text() == "1234"
    # Find the call that starts "athena serve" (other calls like nvidia-smi may happen first)
    serve_cmd = next(cmd for cmd in started if "athena" in cmd and "serve" in cmd)
    assert serve_cmd[1:4] == ["-m", "athena", "serve"]
    assert "--data-dir" in serve_cmd
    assert str(data_dir) in serve_cmd


def test_start_refuses_when_already_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "athena.pid").write_text("999")
    monkeypatch.setattr("psutil.pid_exists", lambda pid: True)
    assert main(["start", "--data-dir", str(data_dir)]) == 1
    assert "already running (pid 999)" in capsys.readouterr().err


def test_stop_no_pid_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["stop", "--data-dir", str(tmp_path / "data")]) == 1
    assert "no pid file" in capsys.readouterr().err


def test_stop_stale_pid_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "athena.pid").write_text("333")
    monkeypatch.setattr("psutil.pid_exists", lambda pid: False)
    assert main(["stop", "--data-dir", str(data_dir)]) == 1
    assert not (data_dir / "athena.pid").exists()
    assert "stale pid file removed" in capsys.readouterr().err


def test_stop_running_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "athena.pid").write_text("777")
    monkeypatch.setattr("psutil.pid_exists", lambda pid: True)
    monkeypatch.setattr(psutil, "Process", lambda pid: FakeProcess(pid))
    assert main(["stop", "--data-dir", str(data_dir)]) == 0
    assert not (data_dir / "athena.pid").exists()
    assert "stopped" in capsys.readouterr().out


# ---------------------------------------------------------------- config


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """No ATHENA_* server variables, and those `serve` exports put back afterwards."""
    for name in ("HOST", "PORT", "DATA_DIR", "LOG_TO_FILE", "FEEDBACK_REPO"):
        monkeypatch.setenv(f"ATHENA_{name}", "")
        monkeypatch.delenv(f"ATHENA_{name}")
    monkeypatch.delenv("ATHENA_DURABLE_EXECUTION_DATABASE_URL", raising=False)
    return monkeypatch


def _settings_file(data_dir: Path, data: object) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "athena.json"
    path.write_bytes((data if isinstance(data, str) else json.dumps(data)).encode())
    return path


def test_config_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["config", "path", "--data-dir", str(tmp_path)]) == 0
    assert Path(capsys.readouterr().out.strip()) == tmp_path / "athena.json"


def test_config_show_says_where_each_value_comes_from(
    tmp_path: Path, clean_env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    url = "postgresql://athena:hunter2@db/athena"
    _settings_file(tmp_path, {"server": {"port": 8500, "durable_execution_database_url": url}})
    clean_env.setenv("ATHENA_HOST", "127.0.0.1")
    assert main(["config", "show", "--data-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "port = 8500  (file)" in out
    assert "host = 127.0.0.1  (env ATHENA_HOST)" in out
    assert "feedback_repo = https://github.com/Promethean-Works/athena  (default)" in out
    assert "hunter2" not in out
    assert "athena:***@db" in out


def test_redact_url_hides_every_form_of_secret() -> None:
    from athena.cli import _redact_url

    assert _redact_url("postgresql://u:pw@h:5432/db") == "postgresql://u:***@h:5432/db"
    assert _redact_url("postgresql://u@h/db?password=pw") == "postgresql://u:***@h/db?***"
    assert "pw" not in _redact_url("postgresql://h/db?sslmode=require&password=pw")


def test_config_check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["config", "check", "--data-dir", str(tmp_path)]) == 0
    assert "Athena will use defaults" in capsys.readouterr().out
    _settings_file(tmp_path, '{\n  "server": {"port": 0}\n}')
    assert main(["config", "check", "--data-dir", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "athena.json:2:14: server.port: Input should be greater than or equal to 1" in err
    _settings_file(tmp_path, {"server": {"port": 8500}})
    assert main(["config", "check", "--data-dir", str(tmp_path)]) == 0
    assert "is valid" in capsys.readouterr().out


def test_config_reset_fixes_a_bad_section_and_keeps_the_rest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _settings_file(
        tmp_path, {"https": {"port": "nope"}, "system": {"terminal_enabled": False}}
    )
    assert main(["config", "reset", "https", "--data-dir", str(tmp_path)]) == 0
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["https"]["port"] == 8443
    assert data["system"]["terminal_enabled"] is False
    assert json.loads((tmp_path / "athena.json.bak").read_text(encoding="utf-8"))["https"] == {
        "port": "nope"
    }
    assert "back to its defaults" in capsys.readouterr().out


def test_config_reset_refuses_when_another_section_is_invalid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = '{\n  "https": {"port": "x"},\n  "system": {"nope": 1}\n}'
    _settings_file(tmp_path, text)
    assert main(["config", "reset", "https", "--data-dir", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "the rest of the file is invalid too" in err
    assert "athena.json:3:14: system.nope" in err  # positions in the real file
    assert (tmp_path / "athena.json").read_text(encoding="utf-8") == text


def test_config_reset_without_a_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["config", "reset", "server", "--data-dir", str(tmp_path / "typo")]) == 1
    assert "nothing to reset" in capsys.readouterr().err


def test_config_reset_needs_valid_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _settings_file(tmp_path, '{"https": {')
    assert main(["config", "reset", "https", "--data-dir", str(tmp_path)]) == 1
    assert "athena.json:1:" in capsys.readouterr().err


def _capture_serve(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Run `athena serve` as the supervised child, with the server itself stubbed out."""
    import uvicorn

    seen: dict = {}
    monkeypatch.setattr(uvicorn.Server, "run", lambda self: seen.update(config=self.config))
    monkeypatch.setenv(restart.CHILD_ENV, "1")
    monkeypatch.setattr("athena.cli._stop_with_parent", lambda server: None)
    return seen


def test_serve_takes_host_and_port_from_the_file(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    seen = _capture_serve(clean_env)
    _settings_file(tmp_path, {"server": {"host": "127.0.0.1", "port": 8500}})
    assert main(["serve", "--data-dir", str(tmp_path)]) == 0
    assert (seen["config"].host, seen["config"].port) == ("127.0.0.1", 8500)
    restart.register(None)


def test_flag_beats_env_beats_file(tmp_path: Path, clean_env: pytest.MonkeyPatch) -> None:
    from athena.config import Settings

    seen = _capture_serve(clean_env)
    _settings_file(tmp_path, {"server": {"port": 8500}})
    assert Settings(data_dir=tmp_path).port == 8500
    clean_env.setenv("ATHENA_PORT", "8600")
    assert Settings(data_dir=tmp_path).port == 8600
    assert main(["serve", "--port", "8700", "--data-dir", str(tmp_path)]) == 0
    assert seen["config"].port == 8700
    restart.register(None)


def test_service_install_port_goes_into_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from athena.cli import _set_port

    assert _set_port(tmp_path, 8500, dry_run=True)
    assert "[dry-run] set server.port to 8500" in capsys.readouterr().out
    assert not (tmp_path / "athena.json").exists()
    path = _settings_file(tmp_path, {"system": {"terminal_enabled": False}})
    assert _set_port(tmp_path, 8500, dry_run=False)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["server"]["port"] == 8500
    assert data["system"]["terminal_enabled"] is False
    assert not _set_port(tmp_path, 70000, dry_run=False)
    assert not _set_port(tmp_path, 70000, dry_run=True)


# ---------------------------------------------------------------- doctor


def test_doctor_prints_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["doctor", "--data-dir", str(tmp_path / "data")]) in (0, 1)
    out = capsys.readouterr().out
    assert "== athena doctor" in out
    assert "data dir" in out
    assert "database" in out
    assert "port" in out
    assert "docker" in out
    assert "settings" in out


def test_doctor_reports_a_broken_settings_file(
    tmp_path: Path, clean_env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _settings_file(tmp_path, {"https": {"port": "nope"}})
    assert main(["doctor", "--data-dir", str(tmp_path)]) == 1
    assert "[fail] settings" in capsys.readouterr().out
    # A bad server value too: doctor still reports instead of crashing.
    _settings_file(tmp_path, {"server": {"port": "abc"}})
    assert main(["doctor", "--data-dir", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "[fail] settings" in out and "server.port" in out


class FakePopen:
    def __init__(self, pid: int) -> None:
        self.pid = pid

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False
