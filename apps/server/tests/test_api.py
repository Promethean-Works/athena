from pathlib import Path

from conftest import make_app, signed_in
from fake_probe import FakeProbe
from fastapi.testclient import TestClient

from athena import __version__, restart
from athena.platform.detect import detect
from athena.platform.store import CapabilityStore


def client(tmp_path: Path, web_dir: Path | None = None) -> TestClient:
    return signed_in(TestClient(make_app(tmp_path, web_dir)))


def test_health(tmp_path: Path) -> None:
    res = client(tmp_path).get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["started_at"]
    # The same process answers with the same start time (the UI polls it after a restart).
    assert client(tmp_path / "other").get("/api/health").json()["started_at"] >= body["started_at"]


class FakeServer:
    should_exit = False


def test_restart_needs_a_supervisor_and_is_audited(tmp_path: Path) -> None:
    c = client(tmp_path)
    restart.register(None)
    assert c.post("/api/system/restart").status_code == 409
    server = FakeServer()
    restart.register(server)
    try:
        with c:
            res = c.post("/api/system/restart")
        assert res.status_code == 202
        assert server.should_exit is True
        assert restart.requested()
        actions = [row["action"] for row in c.get("/api/audit").json()]
        assert "system.restart" in actions
    finally:
        restart.register(None)


def test_restart_is_admin_only(tmp_path: Path) -> None:
    c = client(tmp_path)
    server = FakeServer()
    restart.register(server)
    try:
        with c.app.state.db.engine.begin() as conn:  # type: ignore[attr-defined]
            conn.exec_driver_sql("UPDATE users SET is_admin = 0")
        assert c.post("/api/system/restart").status_code == 403
        assert server.should_exit is False
    finally:
        restart.register(None)


def test_restart_needs_a_session(tmp_path: Path) -> None:
    c = TestClient(make_app(tmp_path))
    assert c.post("/api/system/restart").status_code == 401


def test_system_info(tmp_path: Path) -> None:
    body = client(tmp_path).get("/api/system/info").json()
    assert body["os"] in {"linux", "darwin", "windows"}
    assert body["version"] == __version__
    assert body["arch"]
    assert body["hostname"]


def test_root_without_web_ui_explains_dev_setup(tmp_path: Path) -> None:
    res = client(tmp_path).get("/")
    assert res.status_code == 200
    assert "pnpm dev" in res.json()["detail"]


def test_serves_bundled_web_ui(tmp_path: Path) -> None:
    web = tmp_path / "web"
    (web / "settings").mkdir(parents=True)
    (web / "index.html").write_text("<h1>athena</h1>")
    (web / "settings" / "index.html").write_text("<h1>settings</h1>")
    c = client(tmp_path, web)
    assert "athena" in c.get("/").text
    assert "settings" in c.get("/settings/").text
    # API routes still win over the static mount.
    assert c.get("/api/health").json()["status"] == "ok"


def test_openapi_has_stable_operation_ids(tmp_path: Path) -> None:
    paths = client(tmp_path).get("/api/openapi.json").json()["paths"]
    assert paths["/api/health"]["get"]["operationId"] == "getHealth"
    assert paths["/api/system/info"]["get"]["operationId"] == "getSystemInfo"


def test_capabilities_manifest(tmp_path: Path) -> None:
    with client(tmp_path) as c:
        body = c.get("/api/system/capabilities").json()
    assert body["os"] == "darwin"
    by_id = {cap["id"]: cap for cap in body["capabilities"]}
    assert by_id["containers"]["status"] == "missing"
    assert by_id["containers"]["available"] is False
    assert by_id["files"]["available"] is True
    assert "packages.apt" not in by_id


def test_capabilities_refresh_reruns_detection(tmp_path: Path) -> None:
    calls = []

    def detector():
        calls.append(1)
        return detect(FakeProbe())

    app = make_app(tmp_path, store=CapabilityStore(detector=detector))
    with signed_in(TestClient(app)) as c:
        c.get("/api/system/capabilities")
        first = len(calls)
        c.get("/api/system/capabilities")
        assert len(calls) == first  # cached
        assert c.post("/api/system/capabilities/refresh").status_code == 200
        assert len(calls) == first + 1


def test_logging_writes_to_data_dir(tmp_path: Path) -> None:
    import logging

    from athena.logging_setup import setup_logging

    log_file = setup_logging(tmp_path)
    logging.getLogger("athena.test").info("hello from the test")
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert "hello from the test" in log_file.read_text()
    for handler in list(logging.getLogger().handlers):
        logging.getLogger().removeHandler(handler)
        handler.close()
