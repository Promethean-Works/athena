import io
import json
import subprocess
import sys
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


def test_config_show_prints_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ATHENA_PORT", raising=False)
    assert main(["config", "show"]) == 0
    out = capsys.readouterr().out
    assert "port=" in out
    assert "(default)" in out


def test_config_get_prints_one_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ATHENA_PORT", "9999")
    assert main(["config", "get", "port"]) == 0
    assert capsys.readouterr().out.strip() == "9999"


def test_config_get_unknown_key(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["config", "get", "nope"]) == 1
    assert "unknown setting" in capsys.readouterr().err


def test_config_set_prints_export_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["config", "set", "port", "9999"]) == 0
    out = capsys.readouterr().out
    if sys.platform == "win32":
        assert 'setx ATHENA_PORT "9999"' in out
    else:
        assert 'export ATHENA_PORT="9999"' in out


# ---------------------------------------------------------------- doctor


def test_doctor_prints_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["doctor", "--data-dir", str(tmp_path / "data")]) in (0, 1)
    out = capsys.readouterr().out
    assert "== athena doctor" in out
    assert "data dir" in out
    assert "database" in out
    assert "port" in out
    assert "docker" in out


class FakePopen:
    def __init__(self, pid: int) -> None:
        self.pid = pid

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False
