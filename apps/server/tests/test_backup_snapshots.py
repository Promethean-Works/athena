"""Backup plans and snapshots (docs/specs/backup.md, part 2b): routes, runs, stop and start."""

import asyncio
import json
import sqlite3
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path

import pytest
from conftest import make_app, signed_in
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from test_backup import PASSWORD, FakeProvider, FakeRestic, _real_restic, needs_restic
from test_containers import SAMPLE, ready_store

from athena.apps.store import AppStore
from athena.backup import snapshots
from athena.backup.restic import Result
from athena.backup.service import ResticProvider
from athena.containers import service as containers_service
from athena.db.models import App, AuditEntry, BackupPlan

REAL_RESTIC = _real_restic()  # found now: the compose_log fixture patches `shutil.which`
COMPOSE = "services:\n  web:\n    image: nginx:1.29\n"


class StreamingFakeRestic(FakeRestic):
    """FakeRestic whose `stream` (used by `restic backup`) is scripted too."""

    def __init__(self, on_stream: Callable[[tuple[str, ...]], Awaitable[Result]] | None = None):
        super().__init__()
        self.on_stream = on_stream
        self.streamed: list[tuple[str, ...]] = []

    async def stream(self, repo, *args, on_line, timeout=0):  # type: ignore[no-untyped-def,override]
        self.streamed.append(args)
        self.repos.append(repo)
        if self.on_stream is not None:
            return await self.on_stream(args)
        await on_line(json.dumps({"message_type": "status", "percent_done": 0.5, "bytes_done": 5}))
        await on_line(
            json.dumps({"message_type": "summary", "snapshot_id": "abcdef123456", "data_added": 9})
        )
        return Result(0, "", "")


@pytest.fixture
def compose_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`docker compose <action>` becomes a command that appends `<project> <action>`."""
    log = tmp_path / "compose.log"
    monkeypatch.setattr("athena.containers.runtime.shutil.which", lambda b: f"/usr/bin/{b}")

    def fake(runtime, name, path, *args):  # type: ignore[no-untyped-def]
        code = f"open({str(log)!r}, 'a').write('{name} {args[0]}\\n')"
        return [sys.executable, "-c", code]

    monkeypatch.setattr(snapshots, "compose", fake)
    running = SAMPLE.model_copy(update={"project": "site", "state": "running"})
    monkeypatch.setattr(containers_service, "list_containers", lambda rt: [running])
    return log


def compose_calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def make_client(tmp_path: Path, tool) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    app = make_app(tmp_path, store=ready_store(), backup_allowed_roots=[tmp_path])
    app.state.restic = FakeProvider(tool)
    with TestClient(app) as client:
        yield signed_in(client)


@pytest.fixture
def fake_tool() -> StreamingFakeRestic:
    return StreamingFakeRestic()


@pytest.fixture
def api(tmp_path: Path, fake_tool: StreamingFakeRestic, compose_log: Path) -> Iterator[TestClient]:
    yield from make_client(tmp_path, fake_tool)


def add_app(c: TestClient, name: str = "site") -> Path:
    engine = c.app.state.db.engine  # type: ignore[attr-defined]
    store = AppStore(c.app.state.settings.data_dir)  # type: ignore[attr-defined]
    store.write(name, COMPOSE)
    (store.dir(name) / "data" / "file.txt").write_text("hello")
    with Session(engine) as db:
        db.add(App(name=name, source="compose"))
        db.commit()
    return store.dir(name)


def add_destination(c: TestClient, tmp_path: Path, name: str = "USB") -> dict:
    repo = tmp_path / "repo"
    # The fake restic creates nothing, so make the folder look like a repository.
    for sub in ("keys", "data"):
        (repo / sub).mkdir(parents=True, exist_ok=True)
    (repo / "config").write_text("x")
    res = c.post(
        "/api/backup/destinations",
        json={"name": name, "path": str(repo), "password": PASSWORD, "recovery_kit_saved": True},
    )
    assert res.status_code == 201, res.text
    return res.json()


def add_plan(c: TestClient, dest: dict, **kwargs) -> dict:  # type: ignore[no-untyped-def]
    body = {
        "name": "Nightly",
        "destination_id": dest["id"],
        "items": {"athena": True, "apps": []},
        **kwargs,
    }
    res = c.post("/api/backup/plans", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def wait(c: TestClient, job_id: str, timeout: float = 60) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = c.get(f"/api/jobs/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("job didn't finish")


def run(c: TestClient, plan: dict) -> dict:
    res = c.post(f"/api/backup/plans/{plan['id']}/run")
    assert res.status_code == 202, res.text
    return wait(c, res.json()["id"])


def plan_row(c: TestClient, plan_id: str) -> BackupPlan:
    with Session(c.app.state.db.engine) as db:  # type: ignore[attr-defined]
        row = db.get(BackupPlan, plan_id)
        assert row is not None
        db.expunge(row)
        return row


# ---------------------------------------------------------------- routes


def test_plan_crud(api: TestClient, tmp_path: Path) -> None:
    add_app(api)
    dest = add_destination(api, tmp_path)
    plan = add_plan(
        api,
        dest,
        items={"athena": True, "apps": [{"name": "site", "while_running": True}]},
        schedule="0 3 * * *",
    )
    assert plan["retention"] == {
        "keep_last": 7,
        "keep_daily": 7,
        "keep_weekly": 4,
        "keep_monthly": 6,
    }
    assert plan["last_status"] is None
    assert [p["name"] for p in api.get("/api/backup/plans").json()] == ["Nightly"]

    updated = {
        **plan,
        "name": "Weekly",
        "schedule": "",
        "items": {"athena": False, "apps": [{"name": "site"}]},
    }
    res = api.put(f"/api/backup/plans/{plan['id']}", json=updated)
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "Weekly"
    assert res.json()["schedule"] is None
    assert res.json()["items"]["apps"] == [{"name": "site", "while_running": False}]

    assert api.delete(f"/api/backup/plans/{plan['id']}").status_code == 204
    assert api.get("/api/backup/plans").json() == []
    assert api.delete(f"/api/backup/plans/{plan['id']}").status_code == 404
    actions = {e.action for e in audit_entries(api)}
    assert {"backup.plan.create", "backup.plan.update", "backup.plan.delete"} <= actions


def audit_entries(c: TestClient) -> list[AuditEntry]:
    with Session(c.app.state.db.engine) as db:  # type: ignore[attr-defined]
        return list(db.exec(select(AuditEntry)).all())


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"items": {"athena": False, "apps": []}}, "Pick Athena"),
        ({"items": {"athena": True, "apps": [{"name": "nope"}]}}, "No app named nope"),
        (
            {"items": {"athena": True, "apps": [{"name": "site"}, {"name": "site"}]}},
            "listed twice",
        ),
        (
            {"retention": {"keep_last": 0, "keep_daily": 0, "keep_weekly": 0, "keep_monthly": 0}},
            "Keep at least",
        ),
        ({"schedule": "not a cron"}, "Invalid cron"),
        ({"destination_id": "nope"}, "No such destination"),
        ({"name": "  "}, "Enter a name"),
    ],
)
def test_plan_validation(api: TestClient, tmp_path: Path, patch: dict, message: str) -> None:
    add_app(api)
    dest = add_destination(api, tmp_path)
    body = {
        "name": "P",
        "destination_id": dest["id"],
        "items": {"athena": True, "apps": []},
        **patch,
    }
    res = api.post("/api/backup/plans", json=body)
    assert res.status_code in (400, 404, 422), res.text
    assert message in res.text


def test_duplicate_plan_name(api: TestClient, tmp_path: Path) -> None:
    dest = add_destination(api, tmp_path)
    add_plan(api, dest)
    res = api.post(
        "/api/backup/plans",
        json={"name": "Nightly", "destination_id": dest["id"], "items": {"athena": True}},
    )
    assert res.status_code == 409


def test_a_destination_in_use_cannot_be_deleted(api: TestClient, tmp_path: Path) -> None:
    dest = add_destination(api, tmp_path)
    add_plan(api, dest)
    assert api.delete(f"/api/backup/destinations/{dest['id']}").status_code == 409


def test_plan_routes_are_admin_only(api: TestClient, tmp_path: Path) -> None:
    dest = add_destination(api, tmp_path)
    plan = add_plan(api, dest)
    with api.app.state.db.engine.begin() as conn:  # type: ignore[attr-defined]
        conn.exec_driver_sql("UPDATE users SET is_admin = 0")
    assert api.get("/api/backup/plans").status_code == 403
    assert api.post("/api/backup/plans", json={}).status_code in (403, 422)
    assert api.put(f"/api/backup/plans/{plan['id']}", json={}).status_code in (403, 422)
    assert api.delete(f"/api/backup/plans/{plan['id']}").status_code == 403
    assert api.post(f"/api/backup/plans/{plan['id']}/run").status_code == 403
    assert TestClient(make_app(tmp_path / "other")).get("/api/backup/plans").status_code == 401


# ---------------------------------------------------------------- staging Athena


def test_stage_athena_copies_what_a_restore_needs(tmp_path: Path) -> None:
    data = tmp_path / "data"
    (data / "tls").mkdir(parents=True)
    (data / "bin").mkdir()
    with sqlite3.connect(data / "athena.db") as conn:
        conn.execute("create table t (v text)")
        conn.execute("insert into t values ('kept')")
    for name in ("athena.json", "secret.key", "athena.json.bak", "athena.schema.json"):
        (data / name).write_text(name)
    (data / "tls" / "ca.crt").write_text("cert")
    (data / "bin" / "restic").write_text("binary")
    target = snapshots.staging_dir(data)
    target.mkdir(parents=True)
    (target / "stale").write_text("left over from a crashed run")

    snapshots.stage_athena(data, target)

    assert sorted(p.name for p in target.iterdir()) == [
        "athena.db",
        "athena.json",
        "secret.key",
        "tls",
    ]
    assert (target / "tls" / "ca.crt").read_text() == "cert"
    with sqlite3.connect(target / "athena.db") as conn:
        assert conn.execute("select v from t").fetchall() == [("kept",)]


# ---------------------------------------------------------------- runs (fake restic)


def test_run_snapshots_athena_and_each_app_with_tags(
    api: TestClient, tmp_path: Path, fake_tool: StreamingFakeRestic, compose_log: Path
) -> None:
    add_app(api)
    plan = add_plan(
        api, add_destination(api, tmp_path), items={"athena": True, "apps": [{"name": "site"}]}
    )
    job = run(api, plan)
    assert job["status"] == "succeeded", job
    assert len(fake_tool.streamed) == 2
    athena_args, app_args = (" ".join(a) for a in fake_tool.streamed)
    assert "--tag athena " in athena_args and "--tag app:site " in app_args
    assert "--tag os:" in app_args and "--tag athena-version:" in app_args
    assert app_args.endswith(str(tmp_path / "data" / "apps" / "site"))
    # The app is stopped for its snapshot and started again afterwards.
    assert compose_calls(compose_log) == ["site stop", "site up"]
    row = plan_row(api, plan["id"])
    assert (row.last_status, row.last_error) == ("ok", None)
    assert row.last_run_at is not None
    assert not snapshots.staging_dir(tmp_path / "data").exists()
    assert api.get("/api/backup/plans").json()[0]["last_status"] == "ok"


def test_the_password_never_reaches_argv_or_the_job_log(
    api: TestClient, tmp_path: Path, fake_tool: StreamingFakeRestic
) -> None:
    add_app(api)
    plan = add_plan(
        api, add_destination(api, tmp_path), items={"athena": True, "apps": [{"name": "site"}]}
    )
    job = run(api, plan)
    assert PASSWORD not in json.dumps(job)
    assert all(PASSWORD not in " ".join(a) for a in fake_tool.streamed)
    assert {r.password for r in fake_tool.repos} == {PASSWORD}


def test_while_running_does_not_stop_the_app(
    api: TestClient, tmp_path: Path, compose_log: Path
) -> None:
    add_app(api)
    plan = add_plan(
        api,
        add_destination(api, tmp_path),
        items={"athena": False, "apps": [{"name": "site", "while_running": True}]},
    )
    assert run(api, plan)["status"] == "succeeded"
    assert compose_calls(compose_log) == []


def test_an_app_that_was_stopped_stays_stopped(
    api: TestClient, tmp_path: Path, compose_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(containers_service, "list_containers", lambda rt: [])
    add_app(api)
    plan = add_plan(
        api, add_destination(api, tmp_path), items={"athena": False, "apps": [{"name": "site"}]}
    )
    assert run(api, plan)["status"] == "succeeded"
    assert compose_calls(compose_log) == []


def test_a_failed_backup_starts_the_app_again_and_is_reported(
    api: TestClient, tmp_path: Path, fake_tool: StreamingFakeRestic, compose_log: Path
) -> None:
    async def boom(args: tuple[str, ...]) -> Result:
        return Result(1, "", "Fatal: disk full")

    fake_tool.on_stream = boom
    add_app(api)
    plan = add_plan(
        api, add_destination(api, tmp_path), items={"athena": False, "apps": [{"name": "site"}]}
    )
    job = run(api, plan)
    assert job["status"] == "failed"
    assert "disk full" in job["error"]
    assert compose_calls(compose_log) == ["site stop", "site up"]
    row = plan_row(api, plan["id"])
    assert row.last_status == "failed" and "disk full" in (row.last_error or "")
    assert "backup.run.failed" in {e.action for e in audit_entries(api)}


def test_one_failing_item_does_not_stop_the_others(
    api: TestClient, tmp_path: Path, fake_tool: StreamingFakeRestic, compose_log: Path
) -> None:
    folder = add_app(api, "gone")
    add_app(api)
    plan = add_plan(
        api,
        add_destination(api, tmp_path),
        items={"athena": True, "apps": [{"name": "gone"}, {"name": "site"}]},
    )
    for child in sorted(folder.rglob("*"), reverse=True):
        child.unlink() if child.is_file() else child.rmdir()
    folder.rmdir()
    job = run(api, plan)
    assert job["status"] == "failed"
    assert "app:gone: gone has no folder" in job["error"]
    assert len(fake_tool.streamed) == 2  # Athena and site were still backed up
    assert compose_calls(compose_log) == ["site stop", "site up"]


def test_a_failure_to_start_again_is_its_own_error(
    api: TestClient, tmp_path: Path, compose_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake(runtime, name, path, *args):  # type: ignore[no-untyped-def]
        code = "import sys" if args[0] == "stop" else "import sys; sys.exit(3)"
        return [sys.executable, "-c", code]

    monkeypatch.setattr(snapshots, "compose", fake)
    add_app(api)
    plan = add_plan(
        api, add_destination(api, tmp_path), items={"athena": False, "apps": [{"name": "site"}]}
    )
    job = run(api, plan)
    assert job["status"] == "failed"
    assert "site could not be started again" in job["error"]


def test_cancelling_still_starts_the_app(
    api: TestClient, tmp_path: Path, fake_tool: StreamingFakeRestic, compose_log: Path
) -> None:
    async def forever(args: tuple[str, ...]) -> Result:
        await asyncio.sleep(3600)
        return Result(0, "", "")

    fake_tool.on_stream = forever
    add_app(api)
    plan = add_plan(
        api, add_destination(api, tmp_path), items={"athena": False, "apps": [{"name": "site"}]}
    )
    job_id = api.post(f"/api/backup/plans/{plan['id']}/run").json()["id"]
    for _ in range(200):
        if compose_calls(compose_log) == ["site stop"] and fake_tool.streamed:
            break
        time.sleep(0.05)
    assert fake_tool.streamed
    assert api.post(f"/api/jobs/{job_id}/cancel").status_code == 202
    job = wait(api, job_id)
    assert job["status"] == "failed"
    assert compose_calls(compose_log) == ["site stop", "site up"]
    row = plan_row(api, plan["id"])
    assert (row.last_status, row.last_error) == ("failed", "Cancelled")
    assert api.app.state.app_jobs == {}  # type: ignore[attr-defined]


def test_a_missing_destination_skips_the_run(
    api: TestClient, tmp_path: Path, fake_tool: StreamingFakeRestic
) -> None:
    dest = add_destination(api, tmp_path)
    plan = add_plan(api, dest)
    (tmp_path / "repo").rename(tmp_path / "unplugged")
    job = run(api, plan)
    assert job["status"] == "failed"
    assert "isn't connected" in job["error"]
    assert plan_row(api, plan["id"]).last_status == "skipped"
    assert fake_tool.streamed == []
    assert "backup.run.failed" not in {e.action for e in audit_entries(api)}


def test_two_runs_on_one_destination_do_not_overlap(
    api: TestClient, tmp_path: Path, fake_tool: StreamingFakeRestic
) -> None:
    release = {"go": False}

    async def slow(args: tuple[str, ...]) -> Result:
        while not release["go"]:
            await asyncio.sleep(0.02)
        return Result(0, "", "")

    fake_tool.on_stream = slow
    dest = add_destination(api, tmp_path)
    plan = add_plan(api, dest)
    other = add_plan(api, dest, name="Other")
    job_id = api.post(f"/api/backup/plans/{plan['id']}/run").json()["id"]
    for _ in range(200):
        if fake_tool.streamed:
            break
        time.sleep(0.02)
    assert api.post(f"/api/backup/plans/{other['id']}/run").status_code == 409
    release["go"] = True
    assert wait(api, job_id)["status"] == "succeeded"


def test_apps_need_a_container_runtime(
    tmp_path: Path, fake_tool: StreamingFakeRestic, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_app(tmp_path, backup_allowed_roots=[tmp_path])  # no ready container capability
    app.state.restic = FakeProvider(fake_tool)
    with TestClient(app) as c:
        signed_in(c)
        add_app(c)
        dest = add_destination(c, tmp_path)
        with_app = add_plan(c, dest, items={"athena": False, "apps": [{"name": "site"}]})
        assert c.post(f"/api/backup/plans/{with_app['id']}/run").status_code == 409
        only_athena = add_plan(c, dest, name="Athena only")
        assert run(c, only_athena)["status"] == "succeeded"


def test_an_incomplete_snapshot_is_a_warning_not_a_failure(
    api: TestClient, tmp_path: Path, fake_tool: StreamingFakeRestic
) -> None:
    async def partial(args: tuple[str, ...]) -> Result:
        return Result(3, "", "warning: unreadable file")

    fake_tool.on_stream = partial
    plan = add_plan(api, add_destination(api, tmp_path))
    job = run(api, plan)
    assert job["status"] == "succeeded"
    assert any("couldn't be read" in line for line in job["lines"])


# ---------------------------------------------------------------- a real restic


def real_client(tmp_path: Path) -> Iterator[TestClient]:
    real = REAL_RESTIC
    assert real is not None
    app = make_app(tmp_path, store=ready_store(), backup_allowed_roots=[tmp_path])
    app.state.restic = ResticProvider(tmp_path / "data", binary=real)
    with TestClient(app) as client:
        yield signed_in(client)


def restic_json(tmp_path: Path, *args: str) -> list | dict:
    out = subprocess.run(
        [str(REAL_RESTIC), "-r", str(tmp_path / "repo"), "--json", *args],
        env={"RESTIC_PASSWORD": PASSWORD, "RESTIC_CACHE_DIR": str(tmp_path / "rc"), "PATH": ""},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)


@needs_restic
def test_real_restic_snapshots_athena_and_an_app(tmp_path: Path, compose_log: Path) -> None:
    for c in real_client(tmp_path):
        folder = add_app(c)
        dest_res = c.post(
            "/api/backup/destinations",
            json={
                "name": "USB",
                "path": str(tmp_path / "repo"),
                "password": PASSWORD,
                "recovery_kit_saved": True,
            },
        )
        assert dest_res.status_code == 201, dest_res.text
        plan = add_plan(c, dest_res.json(), items={"athena": True, "apps": [{"name": "site"}]})
        job = run(c, plan)
        assert job["status"] == "succeeded", job
        snaps = restic_json(tmp_path, "snapshots")
        assert isinstance(snaps, list)
        tags = sorted(t for s in snaps for t in s["tags"] if t in ("athena", "app:site"))
        assert tags == ["app:site", "athena"]
        assert compose_calls(compose_log) == ["site stop", "site up"]

        # The app snapshot holds the folder; the Athena one holds a consistent database copy.
        by_tag = {("app:site" if "app:site" in s["tags"] else "athena"): s["id"] for s in snaps}
        app_files = restic_json_lines(tmp_path, "ls", by_tag["app:site"])
        assert any(p.endswith("data/file.txt") for p in app_files)
        athena_files = restic_json_lines(tmp_path, "ls", by_tag["athena"])
        assert any(p.endswith("/athena.db") for p in athena_files)
        assert any(p.endswith("/secret.key") for p in athena_files)
        assert not any("/bin" in p for p in athena_files)

        # Running again adds almost nothing (dedup), and restoring brings a deleted file back.
        (folder / "data" / "file.txt").unlink()
        assert run(c, plan)["status"] == "succeeded"
        assert len(restic_json(tmp_path, "snapshots")) == 4  # type: ignore[arg-type]
        assert PASSWORD not in json.dumps(job)


def restic_json_lines(tmp_path: Path, *args: str) -> list[str]:
    out = subprocess.run(
        [str(REAL_RESTIC), "-r", str(tmp_path / "repo"), "--json", *args],
        env={"RESTIC_PASSWORD": PASSWORD, "RESTIC_CACHE_DIR": str(tmp_path / "rc"), "PATH": ""},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [json.loads(line).get("path", "") for line in out.splitlines() if line.strip()]
