"""POST /api/system/update: the server's side of a one-click update."""

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import make_app, signed_in
from fastapi.testclient import TestClient

from athena import restart, self_update
from athena.platform.capabilities import Capability, CapabilityManifest
from athena.platform.store import CapabilityStore


class FakeServer:
    should_exit = False


def store(ready: bool = True, detail: str | None = "Athena was started from a terminal"):
    cap = Capability(
        id="self_update",
        label="Update Athena",
        status="ready" if ready else "unsupported",
        detail=None if ready else detail,
    )
    manifest = CapabilityManifest(
        os="linux", os_version="x", arch="x", detected_at=datetime.now(UTC), capabilities=[cap]
    )
    return CapabilityStore(detector=lambda: manifest)


def client(tmp_path: Path, **kw: Any) -> TestClient:
    return signed_in(TestClient(make_app(tmp_path, store=store(**kw))))


@pytest.fixture(autouse=True)
def _clean_restart():
    restart.register(None)
    yield
    restart.register(None)


def wait_job(c: TestClient, job_id: str) -> dict:
    for _ in range(100):
        job = c.get(f"/api/jobs/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("the job never finished")


def test_it_runs_the_update_and_hands_over(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    server = FakeServer()
    restart.register(server)
    monkeypatch.setattr("athena.api.system.EXIT_DELAY_SECONDS", 0.01)

    async def fake(opts, say, handoff, **kw):
        seen["version"] = opts.version
        say("Downloading Athena 0.2.0")
        handoff()
        return "0.2.0"

    monkeypatch.setattr(self_update, "run_from_server", fake)
    with client(tmp_path) as c:
        res = c.post("/api/system/update", json={"version": "0.2.0"})
        assert res.status_code == 202
        job = wait_job(c, res.json()["id"])
        assert job["status"] == "succeeded" and "Downloading Athena 0.2.0" in job["lines"]
        for _ in range(100):
            if server.should_exit:
                break
            time.sleep(0.02)
        actions = [row["action"] for row in c.get("/api/audit").json()]
    assert seen["version"] == "0.2.0"
    assert server.should_exit is True and restart.exit_requested() and not restart.requested()
    assert "system.update.start" in actions


def test_a_failure_before_the_swap_fails_the_job_and_keeps_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = FakeServer()
    restart.register(server)

    async def fake(opts, say, handoff, **kw):
        raise self_update.UpdateError("Checksum mismatch; refusing to install an unverified wheel")

    monkeypatch.setattr(self_update, "run_from_server", fake)
    with client(tmp_path) as c:
        job = wait_job(c, c.post("/api/system/update", json={}).json()["id"])
        assert job["status"] == "failed" and "unverified wheel" in job["error"]
        assert c.get("/api/health").status_code == 200
    assert server.should_exit is False


def test_a_host_that_cannot_update_gets_the_reason(tmp_path: Path) -> None:
    c = client(tmp_path, ready=False)
    res = c.post("/api/system/update", json={})
    assert res.status_code == 422
    assert res.json()["detail"] == "Athena was started from a terminal"


def test_only_admins_with_a_session_can_update(tmp_path: Path) -> None:
    anonymous = TestClient(make_app(tmp_path / "a", store=store()))
    assert anonymous.post("/api/system/update", json={}).status_code == 401
    c = client(tmp_path / "b")
    with c.app.state.db.engine.begin() as conn:  # type: ignore[attr-defined]
        conn.exec_driver_sql("UPDATE users SET is_admin = 0")
    assert c.post("/api/system/update", json={}).status_code == 403


def test_it_needs_the_csrf_token(tmp_path: Path) -> None:
    c = client(tmp_path)
    del c.headers["X-CSRF-Token"]
    assert c.post("/api/system/update", json={}).status_code == 403


@pytest.mark.parametrize("version", ["latest", "0.2", "http://evil/x", "0.2.0/../x", "v0.2.0 "])
def test_the_version_is_validated_and_never_reaches_a_url(tmp_path: Path, version: str) -> None:
    res = client(tmp_path).post("/api/system/update", json={"version": version})
    assert res.status_code == 422


@pytest.mark.parametrize("version", ["0.2.0", "0.2.0-rc.1", "0.2.0rc1"])
def test_release_and_pre_release_versions_pass_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str
) -> None:
    async def fake(opts, say, handoff, **kw):
        return "x"

    monkeypatch.setattr(self_update, "run_from_server", fake)
    with client(tmp_path) as c:
        assert c.post("/api/system/update", json={"version": version}).status_code == 202


def test_a_second_start_is_refused_while_one_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    async def slow(opts, say, handoff, **kw):
        await asyncio.sleep(0.5)
        return "0.2.0"

    monkeypatch.setattr(self_update, "run_from_server", slow)
    with client(tmp_path) as c:
        assert c.post("/api/system/update", json={}).status_code == 202
        assert c.post("/api/system/update", json={}).status_code == 409


def test_a_running_helper_blocks_a_start(tmp_path: Path) -> None:
    import os

    c = client(tmp_path)
    paths = self_update.Paths(c.app.state.settings.data_dir)  # type: ignore[attr-defined]
    paths.updates.mkdir(parents=True)
    paths.lock.write_text(str(os.getpid()), encoding="utf-8")
    assert c.post("/api/system/update", json={}).status_code == 409
