"""POST /api/system/update: the server's side of a one-click update."""

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import make_app, signed_in
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from athena import restart, self_update
from athena.backup.service import PlanRunner
from athena.db.models import AuditEntry, BackupDestination, BackupPlan
from athena.platform.capabilities import Capability, CapabilityManifest
from athena.platform.store import CapabilityStore


class FakeServer:
    should_exit = False


def store(
    ready: bool = True,
    detail: str | None = "Athena was started from a terminal",
    backup: bool = True,
):
    caps = [
        Capability(
            id="self_update",
            label="Update Athena",
            status="ready" if ready else "unsupported",
            detail=None if ready else detail,
        ),
        Capability(
            id="backup", label="Backup", status="ready" if backup else "unsupported", detail=None
        ),
    ]
    manifest = CapabilityManifest(
        os="linux", os_version="x", arch="x", detected_at=datetime.now(UTC), capabilities=caps
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


def test_a_second_start_within_a_minute_is_rate_limited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def quick(opts, say, handoff, **kw):
        return "0.2.0"

    monkeypatch.setattr(self_update, "run_from_server", quick)
    with client(tmp_path) as c:
        first = c.post("/api/system/update", json={})
        assert first.status_code == 202
        wait_job(c, first.json()["id"])
        again = c.post("/api/system/update", json={})
        assert again.status_code == 429 and int(again.headers["Retry-After"]) >= 1
        c.app.state.update_started_at -= 61  # type: ignore[attr-defined]
        assert c.post("/api/system/update", json={}).status_code == 202


def test_a_refused_start_does_not_use_up_the_rate_limit(tmp_path: Path) -> None:
    c = client(tmp_path, ready=False)
    assert c.post("/api/system/update", json={}).status_code == 422
    assert c.app.state.update_started_at is None  # type: ignore[attr-defined]


def write_state(c: TestClient, **state: Any) -> None:
    paths = self_update.Paths(c.app.state.settings.data_dir)  # type: ignore[attr-defined]
    paths.updates.mkdir(parents=True, exist_ok=True)
    import json

    paths.state.write_text(json.dumps(state), encoding="utf-8")


def test_the_status_is_idle_before_any_update(tmp_path: Path) -> None:
    with client(tmp_path) as c:
        body = c.get("/api/system/update/status").json()
    assert body["phase"] == "idle" and body["running_jobs"] == [] and body["terminals"] == 0


def test_the_status_reads_the_helpers_state_file(tmp_path: Path) -> None:
    with client(tmp_path) as c:
        write_state(
            c,
            phase="rolled_back",
            step="Rolled back",
            to="0.2.0",
            error="the health check timed out",
            started_at="2026-11-22T10:00:00+00:00",
            log_tail=["==> Stopping Athena", "Update failed"],
            **{"from": "0.1.4"},
        )
        body = c.get("/api/system/update/status").json()
    assert body["phase"] == "rolled_back" and body["error"] == "the health check timed out"
    assert (body["from_version"], body["to_version"]) == ("0.1.4", "0.2.0")
    assert body["log_tail"] == ["==> Stopping Athena", "Update failed"]


def test_the_status_lists_what_a_restart_would_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    async def slow(opts, say, handoff, **kw):
        await asyncio.sleep(0.5)
        return "0.2.0"

    monkeypatch.setattr(self_update, "run_from_server", slow)
    with client(tmp_path) as c:
        manager = c.app.state.jobs  # type: ignore[attr-defined]
        started = c.post("/api/system/update", json={})
        assert started.status_code == 202
        c.app.state.terminal_sessions[1] = asyncio.Event()  # type: ignore[attr-defined]
        body = c.get("/api/system/update/status").json()
        assert body["phase"] == "preparing" and body["job_id"] == started.json()["id"]
        assert body["terminals"] == 1 and body["running_jobs"] == []
        assert manager.running()[0].title == "Update Athena"


def test_only_admins_see_the_status(tmp_path: Path) -> None:
    assert (
        TestClient(make_app(tmp_path / "a", store=store())).get("/api/system/update/status")
    ).status_code == 401
    c = client(tmp_path / "b")
    with c.app.state.db.engine.begin() as conn:  # type: ignore[attr-defined]
        conn.exec_driver_sql("UPDATE users SET is_admin = 0")
    assert c.get("/api/system/update/status").status_code == 403


def test_the_new_server_audits_how_the_update_ended(tmp_path: Path) -> None:
    import json

    c = client(tmp_path)
    paths = self_update.Paths(c.app.state.settings.data_dir)  # type: ignore[attr-defined]
    paths.updates.mkdir(parents=True)
    paths.state.write_text(
        json.dumps({"phase": "done", "from": "0.1.4", "to": "0.2.0", "error": None}),
        encoding="utf-8",
    )
    with c:  # the lifespan starts the audit task
        for _ in range(100):
            rows = c.get("/api/audit").json()
            if any(r["action"] == "system.update.done" for r in rows):
                break
            time.sleep(0.05)
        row = next(r for r in rows if r["action"] == "system.update.done")
    assert row["username"] == "system" and row["target"] == "athena"
    with c.app.state.db.engine.begin() as conn:  # type: ignore[attr-defined]
        detail = conn.exec_driver_sql(
            "SELECT detail FROM audit_log WHERE action = 'system.update.done'"
        ).scalar_one()
    assert detail == "0.1.4 -> 0.2.0"


# ---------------------------------------------------------------- back up first, interrupted


def add_plan(c: TestClient, *, athena: bool = True, enabled: bool = True) -> None:
    items = '{"athena": %s, "apps": []}' % ("true" if athena else "false")
    with Session(c.app.state.db.engine) as db:  # type: ignore[attr-defined]
        db.add(BackupDestination(id="d1", name="Disk", kind="local", location="/x", password="p"))
        db.add(
            BackupPlan(id="p1", name="Nightly", destination_id="d1", items=items, enabled=enabled)
        )
        db.commit()


def fake_update(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    async def fake(opts, say, handoff, **kw):
        calls.append("update")
        return "0.2.0"

    monkeypatch.setattr(self_update, "run_from_server", fake)


def test_it_backs_up_athena_first_then_updates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def backup(self, job, plan_id, username, runtime, *, only_athena=False):
        calls.append(f"backup {plan_id} only_athena={only_athena}")

    monkeypatch.setattr(PlanRunner, "run", backup)
    fake_update(monkeypatch, calls)
    with client(tmp_path) as c:
        add_plan(c)
        job = wait_job(c, c.post("/api/system/update", json={"backup": True}).json()["id"])
        assert job["status"] == "succeeded" and "Backing up Athena first" in job["lines"]
        with Session(c.app.state.db.engine) as db:  # type: ignore[attr-defined]
            details = [r.detail or "" for r in db.exec(select(AuditEntry)).all()]
    assert calls == ["backup p1 only_athena=True", "update"]
    assert any("backup first" in d for d in details)


def test_a_failed_backup_stops_the_update_and_allows_a_retry_without_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def backup(self, job, plan_id, username, runtime, *, only_athena=False):
        raise RuntimeError("The destination isn't connected")

    monkeypatch.setattr(PlanRunner, "run", backup)
    fake_update(monkeypatch, calls)
    with client(tmp_path) as c:
        add_plan(c)
        job = wait_job(c, c.post("/api/system/update", json={"backup": True}).json()["id"])
        assert job["status"] == "failed"
        assert job["error"].startswith("The backup failed: The destination isn't connected")
        assert calls == []  # nothing was downloaded or stopped
        again = c.post("/api/system/update", json={})  # "update anyway": no 429 wait
        assert again.status_code == 202
        assert wait_job(c, again.json()["id"])["status"] == "succeeded"
    assert calls == ["update"]


@pytest.mark.parametrize(
    "setup",
    ["no plan", "plan without athena", "disabled plan", "no backup capability"],
)
def test_backup_first_needs_a_plan_that_includes_athena(tmp_path: Path, setup: str) -> None:
    c = client(tmp_path, backup=setup != "no backup capability")
    with c:
        if setup == "plan without athena":
            add_plan(c, athena=False)
        elif setup == "disabled plan":
            add_plan(c, enabled=False)
        elif setup == "no backup capability":
            add_plan(c)
        res = c.post("/api/system/update", json={"backup": True})
    assert res.status_code == 422 and "backup plan" in res.json()["detail"]


def test_the_status_names_the_plan_the_backup_would_use(tmp_path: Path) -> None:
    with client(tmp_path) as c:
        assert c.get("/api/system/update/status").json()["backup_plan"] is None
        add_plan(c)
        assert c.get("/api/system/update/status").json()["backup_plan"] == "Nightly"


def write_phase(c: TestClient, phase: str) -> None:
    paths = self_update.Paths(c.app.state.settings.data_dir)  # type: ignore[attr-defined]
    paths.updates.mkdir(parents=True, exist_ok=True)
    self_update.write_atomic(
        paths.state, json.dumps({"phase": phase, "from": "0.1.0", "to": "0.2.0"}).encode()
    )


def test_an_update_whose_helper_vanished_reads_as_interrupted(tmp_path: Path) -> None:
    with client(tmp_path) as c:
        write_phase(c, "installing")
        body = c.get("/api/system/update/status").json()
    assert body["phase"] == "interrupted" and body["to_version"] == "0.2.0"


@pytest.mark.parametrize("phase", ["done", "rolled_back", "failed", "aborted"])
def test_a_finished_update_is_not_interrupted(tmp_path: Path, phase: str) -> None:
    with client(tmp_path) as c:
        write_phase(c, phase)
        assert c.get("/api/system/update/status").json()["phase"] == phase


def test_a_running_helper_is_not_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(self_update, "lock_holder", lambda paths: 123)
    with client(tmp_path) as c:
        write_phase(c, "installing")
        assert c.get("/api/system/update/status").json()["phase"] == "installing"
