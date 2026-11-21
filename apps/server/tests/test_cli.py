import io
import json
import subprocess
from pathlib import Path

import psutil
import pytest
from conftest import ADMIN, make_app, signed_in
from fastapi.testclient import TestClient

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
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: seen.update(kw))
    for key in ("ATHENA_HOST", "ATHENA_PORT", "ATHENA_DATA_DIR", "ATHENA_LOG_TO_FILE"):
        monkeypatch.delenv(key, raising=False)
    assert main(["serve", "--port", "8499", "--data-dir", str(tmp_path / "d")]) == 0
    assert seen["port"] == 8499
    assert 0 < seen["timeout_graceful_shutdown"] <= 10


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
    assert "feedback_repo = https://github.com/tiagozaccaro/athena  (default)" in out
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


def test_serve_takes_host_and_port_from_the_file(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    import uvicorn

    seen: dict = {}
    clean_env.setattr(uvicorn, "run", lambda *a, **kw: seen.update(kw))
    _settings_file(tmp_path, {"server": {"host": "127.0.0.1", "port": 8500}})
    assert main(["serve", "--data-dir", str(tmp_path)]) == 0
    assert (seen["host"], seen["port"]) == ("127.0.0.1", 8500)


def test_flag_beats_env_beats_file(tmp_path: Path, clean_env: pytest.MonkeyPatch) -> None:
    import uvicorn

    from athena.config import Settings

    seen: dict = {}
    clean_env.setattr(uvicorn, "run", lambda *a, **kw: seen.update(kw))
    _settings_file(tmp_path, {"server": {"port": 8500}})
    assert Settings(data_dir=tmp_path).port == 8500
    clean_env.setenv("ATHENA_PORT", "8600")
    assert Settings(data_dir=tmp_path).port == 8600
    assert main(["serve", "--port", "8700", "--data-dir", str(tmp_path)]) == 0
    assert seen["port"] == 8700


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
