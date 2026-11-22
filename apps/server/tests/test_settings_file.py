"""athena.json: strict startup read, atomic saves that keep hand edits (specs/settings-file.md)."""

import json
import os
import stat
from pathlib import Path

import pytest
from conftest import ADMIN, make_app, signed_in
from fastapi.testclient import TestClient

from athena import settings_file as sf
from athena.cli import main as cli_main
from athena.https.settings import HttpsSettings
from athena.settings_file import AthenaConfig, SettingsFile, SettingsFileError
from athena.system_settings import SystemSettings


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data, indent=2)
    path.write_bytes(text.encode())


def _on_disk(f: SettingsFile) -> dict:
    return json.loads(f.path.read_text(encoding="utf-8"))


def test_missing_file_means_defaults_and_gets_written(tmp_path: Path) -> None:
    f = SettingsFile(tmp_path)
    assert f.load() == AthenaConfig()
    data = _on_disk(f)
    assert data["$schema"] == "./athena.schema.json"
    assert list(data)[1:] == ["server", "system", "https", "ai", "webdav", "backup"]
    assert data["server"]["port"] == 8420
    assert data["system"]["terminal_enabled"] is True
    assert "tunnel_secrets_set" not in data["system"]
    assert "dns_secrets_set" not in data["https"]["letsencrypt"]
    schema = json.loads(f.schema_path.read_text(encoding="utf-8"))
    assert {"$schema", "server", "system", "https", "ai", "webdav"} <= set(schema["properties"])
    if os.name == "posix":
        assert stat.S_IMODE(f.path.stat().st_mode) == 0o600


def test_partial_file_fills_in_defaults(tmp_path: Path) -> None:
    _write(tmp_path / sf.FILE_NAME, {"https": {"port": 9443}})
    config = SettingsFile(tmp_path).load()
    assert config.https.port == 9443
    assert config.https.mode == "off"
    assert config.system == SystemSettings()


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{\n  "https": {"port": 8443,}\n}', "athena.json:2:"),
        (
            '{\n  "https": {\n    "port": 70000\n  }\n}',
            "athena.json:3:5: https.port: Input should be less than or equal to 65535",
        ),
        ({"system": {"terminal_enabld": False}}, "system.terminal_enabld: Extra inputs"),
        ({"sytem": {}}, "sytem: Extra inputs"),
        ([1, 2], "must hold one JSON object"),
    ],
)
def test_invalid_file_refuses_to_load(tmp_path: Path, content: object, expected: str) -> None:
    _write(tmp_path / sf.FILE_NAME, content)
    with pytest.raises(SettingsFileError) as err:
        SettingsFile(tmp_path).load()
    assert expected in str(err.value)


def test_problems_never_show_the_values(tmp_path: Path) -> None:
    # A misplaced secret or password hash must not end up in a log or terminal.
    _write(tmp_path / sf.FILE_NAME, {"webdav": {"password_hash": ["argon2-secret"]}})
    with pytest.raises(SettingsFileError) as err:
        SettingsFile(tmp_path).load()
    assert "argon2-secret" not in str(err.value)


def test_save_keeps_hand_edits_to_other_sections(tmp_path: Path) -> None:
    f = SettingsFile(tmp_path)
    f.load()
    data = _on_disk(f)
    data["https"]["port"] = 9443  # a hand edit while Athena runs
    _write(f.path, data)

    f.save("system", SystemSettings(terminal_enabled=False))

    data = _on_disk(f)
    assert data["https"]["port"] == 9443
    assert data["system"]["terminal_enabled"] is False
    # The hand edit applies on restart; this run keeps what it started with.
    assert f.get().https.port == HttpsSettings().port
    assert f.get().system.terminal_enabled is False
    # The previous version is kept.
    assert json.loads(f.backup_path.read_text(encoding="utf-8"))["https"]["port"] == 9443


def test_save_refuses_to_overwrite_a_broken_file(tmp_path: Path) -> None:
    f = SettingsFile(tmp_path)
    f.load()
    _write(f.path, '{"https": ')
    with pytest.raises(SettingsFileError):
        f.save("system", SystemSettings(terminal_enabled=False))
    assert f.path.read_text(encoding="utf-8") == '{"https": '
    assert f.get().system.terminal_enabled is True


def test_save_retries_while_windows_holds_the_file(tmp_path: Path, monkeypatch) -> None:
    f = SettingsFile(tmp_path)
    f.load()
    real = os.replace
    failures = iter([PermissionError("in use"), PermissionError("in use")])

    def flaky(src, dst):
        if (err := next(failures, None)) is not None:
            raise err
        real(src, dst)

    monkeypatch.setattr(sf.os, "replace", flaky)
    monkeypatch.setattr(sf, "_REPLACE_WAIT", 0)
    f.save("system", SystemSettings(terminal_enabled=False))
    assert _on_disk(f)["system"]["terminal_enabled"] is False


def test_a_broken_save_answers_409(tmp_path: Path) -> None:
    with TestClient(make_app(tmp_path)) as client:
        signed_in(client)
        path = client.app.state.settings_file.path
        path.write_bytes(b"{")
        res = client.put("/api/settings/system", json={"terminal_enabled": False})
        assert res.status_code == 409
        assert "athena.json" in res.json()["detail"]
        assert path.read_bytes() == b"{"


def test_settings_survive_a_restart(tmp_path: Path) -> None:
    with TestClient(make_app(tmp_path)) as client:
        signed_in(client)
        res = client.put("/api/settings/system", json={"terminal_enabled": False})
        assert res.status_code == 200, res.text
    with TestClient(make_app(tmp_path)) as client:
        res = client.post("/api/auth/login", json=ADMIN)
        assert res.status_code == 200, res.text
        assert client.get("/api/settings/system").json()["terminal_enabled"] is False


def test_serve_refuses_an_invalid_file(tmp_path: Path, capsys, monkeypatch) -> None:
    # `athena serve` exports its options as ATHENA_*; put them back afterwards.
    for name in ("HOST", "PORT", "DATA_DIR", "LOG_TO_FILE"):
        monkeypatch.setenv(f"ATHENA_{name}", "")
        monkeypatch.delenv(f"ATHENA_{name}")
    _write(tmp_path / sf.FILE_NAME, {"https": {"port": "eighty"}})
    assert cli_main(["serve", "--port", "8499", "--data-dir", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "Athena can't start" in err
    assert "https.port" in err
    assert "athena.json.bak" not in err  # there is no previous version yet


def test_a_failed_save_leaves_the_running_settings_alone(tmp_path: Path) -> None:
    # Callers change what load() gave them, then save; a refused save must not leak.
    from athena.files import webdav

    f = SettingsFile(tmp_path)
    f.load()
    f.path.write_bytes(b"{")
    with pytest.raises(SettingsFileError):
        webdav.new_password(f, "admin")
    assert f.get().webdav.password_hash is None
    # And a saved section isn't shared with the caller's object afterwards.
    f.path.unlink()
    mine = SystemSettings(terminal_enabled=False)
    f.save("system", mine)
    mine.terminal_enabled = True
    assert f.get().system.terminal_enabled is False


def test_secrets_stay_encrypted_in_the_file(tmp_path: Path) -> None:
    with TestClient(make_app(tmp_path)) as client:
        signed_in(client)
        body = {"tunnel_provider": "ngrok", "tunnel_config": {"auth_token": "very-secret"}}
        assert client.put("/api/settings/system", json=body).status_code == 200
        text = client.app.state.settings_file.path.read_text(encoding="utf-8")
    assert "very-secret" not in text
    assert '"auth_token": "enc:' in text


def test_https_off_refuses_a_broken_file(tmp_path: Path, capsys) -> None:
    _write(tmp_path / sf.FILE_NAME, '{"https": {"mode": "self_signed",}}')
    assert cli_main(["https", "off", "--data-dir", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "athena.json:1:" in err
    assert "can't start" not in err


def test_admins_see_where_the_file_is(tmp_path: Path) -> None:
    with TestClient(make_app(tmp_path)) as client:
        signed_in(client)
        res = client.get("/api/settings/file")
        assert res.status_code == 200, res.text
        assert Path(res.json()["path"]) == client.app.state.settings_file.path
        assert res.json()["backup_path"].endswith("athena.json.bak")
        with client.app.state.db.engine.begin() as conn:
            conn.exec_driver_sql("UPDATE users SET is_admin = 0")
        assert client.get("/api/settings/file").status_code == 403
