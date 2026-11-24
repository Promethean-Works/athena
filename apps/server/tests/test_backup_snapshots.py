"""Backup plans and snapshots (docs/specs/backup.md, part 2b): routes, runs, stop and start."""

import asyncio
import json
import sqlite3
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import make_app, signed_in
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from test_backup import PASSWORD, FakeProvider, FakeRestic, _real_restic, needs_restic
from test_containers import SAMPLE, ready_store

from athena.apps.store import AppStore
from athena.backup import retention, snapshots, versions
from athena.backup.restic import ResticError, Result
from athena.backup.service import ResticProvider
from athena.backup.settings import Retention
from athena.containers import service as containers_service
from athena.db.models import App, AuditEntry, BackupDestination, BackupPlan

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
    assert res.json()["items"]["apps"] == [
        {"name": "site", "bind_mounts": [], "while_running": False}
    ]

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


# ---------------------------------------------------------------- retention (fake restic)


def commands(tool: FakeRestic) -> list[str]:
    return [a[0] for a in tool.calls]


def test_restic_path_matches_how_restic_lists_a_folder() -> None:
    assert versions.restic_path("/data/apps/site/") == "/data/apps/site"
    assert versions.restic_path("C:\\ProgramData\\Athena\\apps\\site") == (
        "/C/ProgramData/Athena/apps/site"
    )


def test_forget_args_leave_out_rules_set_to_zero() -> None:
    keep = Retention(keep_last=3, keep_daily=0, keep_weekly=2, keep_monthly=0)
    assert retention.forget_args("app:site", keep) == [
        "forget", "--tag", "app:site", "--group-by", "",
        "--keep-last", "3", "--keep-weekly", "2",
    ]  # fmt: skip
    with pytest.raises(ResticError):
        retention.forget_args(
            "athena", Retention(keep_last=0, keep_daily=0, keep_weekly=0, keep_monthly=0)
        )


def test_due_when_never_done_or_old_enough() -> None:
    moment = datetime(2026, 11, 22, tzinfo=UTC)
    assert retention.due(None, 7, moment)
    assert not retention.due(moment - timedelta(days=6), 7, moment)
    assert retention.due(moment - timedelta(days=7), 7, moment)
    assert retention.due(datetime(2026, 11, 1), 7, moment)  # naive, as SQLite returns it


def test_a_run_forgets_per_item_with_the_plans_retention(
    api: TestClient, tmp_path: Path, fake_tool: StreamingFakeRestic, compose_log: Path
) -> None:
    add_app(api)
    keep = {"keep_last": 2, "keep_daily": 0, "keep_weekly": 0, "keep_monthly": 1}
    plan = add_plan(
        api,
        add_destination(api, tmp_path),
        items={"athena": True, "apps": [{"name": "site"}]},
        retention=keep,
    )
    assert run(api, plan)["status"] == "succeeded"
    forgets = [a for a in fake_tool.calls if a[0] == "forget"]
    assert [a[a.index("--tag") + 1] for a in forgets] == ["athena", "app:site"]
    for args in forgets:
        assert args[args.index("--keep-last") : args.index("--keep-last") + 2] == (
            "--keep-last",
            "2",
        )
        assert "--keep-monthly" in args and "--keep-daily" not in args
        assert "--prune" not in args


def test_a_failed_item_is_not_forgotten_and_a_failed_forget_fails_the_run(
    api: TestClient, tmp_path: Path, fake_tool: StreamingFakeRestic, compose_log: Path
) -> None:
    add_app(api)
    plan = add_plan(api, add_destination(api, tmp_path))
    fake_tool.results = [Result(1, "", "Fatal: repository is locked")]  # the first `run`: forget
    job = run(api, plan)
    assert job["status"] == "failed"
    assert "athena: retention: Fatal: repository is locked" in job["error"]
    assert "backup.run.failed" in {e.action for e in audit_entries(api)}

    async def boom(args: tuple[str, ...]) -> Result:
        return Result(1, "", "Fatal: disk full")

    fake_tool.calls.clear()
    fake_tool.on_stream = boom
    assert run(api, plan)["status"] == "failed"
    assert "forget" not in commands(fake_tool)


def test_prune_and_check_run_only_when_due(
    api: TestClient, tmp_path: Path, fake_tool: StreamingFakeRestic
) -> None:
    dest = add_destination(api, tmp_path)
    plan = add_plan(api, dest)
    assert run(api, plan)["status"] == "succeeded"
    assert commands(fake_tool).count("prune") == 1 and commands(fake_tool).count("check") == 1
    assert "--read-data" not in " ".join(" ".join(a) for a in fake_tool.calls)

    assert run(api, plan)["status"] == "succeeded"
    assert commands(fake_tool).count("prune") == 1 and commands(fake_tool).count("check") == 1

    with Session(api.app.state.db.engine) as db:  # type: ignore[attr-defined]
        row = db.get(BackupDestination, dest["id"])
        assert row is not None and row.last_pruned_at and row.last_checked_at
        row.last_pruned_at = snapshots.now() - timedelta(days=8)  # check is only 0 days old
        db.add(row)
        db.commit()
    assert run(api, plan)["status"] == "succeeded"
    assert commands(fake_tool).count("prune") == 2 and commands(fake_tool).count("check") == 1


def test_a_failed_check_fails_the_run_and_is_tried_again(
    api: TestClient, tmp_path: Path, fake_tool: StreamingFakeRestic
) -> None:
    plan = add_plan(api, add_destination(api, tmp_path))
    # `run` calls in order: forget, prune, check.
    fake_tool.results = [Result(0, "[]", ""), Result(0, "", ""), Result(1, "", "pack 1 damaged")]
    job = run(api, plan)
    assert job["status"] == "failed"
    assert "check: The repository check failed: pack 1 damaged" in job["error"]
    assert run(api, plan)["status"] == "succeeded"
    assert commands(fake_tool).count("check") == 2


def test_the_backup_settings_set_the_intervals(
    api: TestClient, tmp_path: Path, fake_tool: StreamingFakeRestic
) -> None:
    settings = api.app.state.settings_file  # type: ignore[attr-defined]
    section = settings.section("backup")
    section.prune_interval_days = 365
    settings.save("backup", section)
    plan = add_plan(api, add_destination(api, tmp_path))
    run(api, plan)
    run(api, plan)
    assert commands(fake_tool).count("prune") == 1


# ---------------------------------------------------------------- versions (fake restic)

SNAPSHOTS = json.dumps(
    [
        {
            "id": "a" * 64,
            "time": "2026-11-20T03:00:00.123456789Z",
            "paths": ["/data/apps/site"],
            "tags": ["app:site", "athena-version:0.1.0", "os:linux"],
            "summary": {"total_bytes_processed": 500, "data_added": 120},
        },
        {
            "id": "b" * 64,
            "parent": "a" * 64,
            "time": "2026-11-21T03:00:00Z",
            "paths": ["/data/apps/site"],
            "tags": ["app:site", "athena-version:0.1.0", "os:darwin"],
            "summary": {"total_bytes_processed": 600, "data_added": 10},
        },
        {"id": "c" * 64, "time": "2026-11-21T04:00:00Z", "tags": ["someone-elses"]},
    ]
)
DIFF = (
    '{"message_type":"change","path":"/site/x","modifier":"+"}\n'
    '{"message_type":"statistics","changed_files":2,"added":{"files":3},'
    '"removed":{"files":1}}\n'
)


class VersionsRestic(StreamingFakeRestic):
    """Answers `snapshots`, `diff` and `ls` like restic would."""

    def __init__(self) -> None:
        super().__init__()
        self.ls_output = ""

    async def run(self, repo, *args, timeout=0, stdin=None):  # type: ignore[no-untyped-def,override]
        self.calls.append(args)
        self.repos.append(repo)
        match args[0]:
            case "snapshots":
                return Result(0, SNAPSHOTS, "")
            case "diff":
                return Result(0, DIFF, "")
            case "ls":
                return Result(0, self.ls_output, "")
        return Result(0, "", "")


@pytest.fixture
def versions_api(tmp_path: Path, compose_log: Path) -> Iterator[tuple[TestClient, VersionsRestic]]:
    tool = VersionsRestic()
    for client in make_client(tmp_path, tool):
        yield client, tool


def test_versions_list_athenas_snapshots_newest_first(
    versions_api: tuple[TestClient, VersionsRestic], tmp_path: Path
) -> None:
    api, tool = versions_api
    dest = add_destination(api, tmp_path)
    res = api.get("/api/backup/versions", params={"destination_id": dest["id"]})
    assert res.status_code == 200, res.text
    got = res.json()
    assert [v["id"][0] for v in got] == ["b", "a"]  # the foreign snapshot is left out
    newest = got[0]
    assert newest["item"] == "app:site" and newest["destination_id"] == dest["id"]
    assert (newest["size"], newest["new_bytes"]) == (600, 10)
    assert (newest["files_added"], newest["files_changed"], newest["files_removed"]) == (3, 2, 1)
    assert (newest["athena_version"], newest["os"]) == ("0.1.0", "darwin")
    oldest = got[1]
    assert oldest["files_added"] is None  # no parent to compare with
    assert oldest["time"].startswith("2026-11-20T03:00:00")

    # Diffs are cached: a second listing runs none.
    diffs = [a for a in tool.calls if a[0] == "diff"]
    assert len(diffs) == 1
    api.get("/api/backup/versions")
    assert len([a for a in tool.calls if a[0] == "diff"]) == 1


def test_versions_filter_by_item_and_validate_it(
    versions_api: tuple[TestClient, VersionsRestic], tmp_path: Path
) -> None:
    api, tool = versions_api
    dest = add_destination(api, tmp_path)
    api.get("/api/backup/versions", params={"destination_id": dest["id"], "item": "app:site"})
    snaps = [a for a in tool.calls if a[0] == "snapshots"]
    assert snaps[-1][-2:] == ("--tag", "app:site")
    for bad in ("--help", "app:../x", "app:Site", "other"):
        res = api.get("/api/backup/versions", params={"item": bad})
        assert res.status_code == 400, bad
    assert api.get("/api/backup/versions", params={"destination_id": "nope"}).status_code == 404


def test_an_unplugged_destination_is_an_error_for_one_and_skipped_for_all(
    versions_api: tuple[TestClient, VersionsRestic], tmp_path: Path
) -> None:
    api, _ = versions_api
    dest = add_destination(api, tmp_path)
    (tmp_path / "repo").rename(tmp_path / "unplugged")
    res = api.get("/api/backup/versions", params={"destination_id": dest["id"]})
    assert res.status_code == 409 and "isn't connected" in res.text
    assert api.get("/api/backup/versions").json() == []


def test_version_files_list_one_level(
    versions_api: tuple[TestClient, VersionsRestic], tmp_path: Path
) -> None:
    api, tool = versions_api
    dest = add_destination(api, tmp_path)
    rows = [
        {"message_type": "snapshot", "struct_type": "snapshot", "id": "b" * 64},
        {"name": "site", "type": "dir", "path": "/data/apps/site"},
        {"name": "b.txt", "type": "file", "path": "/data/apps/site/b.txt", "size": 4,
         "mtime": "2026-11-21T03:00:00.5Z"},
        {"name": "data", "type": "dir", "path": "/data/apps/site/data"},
        {"name": "link", "type": "symlink", "path": "/data/apps/site/link"},
    ]  # fmt: skip
    tool.ls_output = "\n".join(json.dumps(r) for r in rows)
    url = f"/api/backup/versions/{'b' * 64}/files"
    res = api.get(url, params={"destination_id": dest["id"]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["path"] == body["root"] == "/data/apps/site"  # the folder that was backed up
    assert [(e["name"], e["kind"]) for e in body["entries"]] == [
        ("data", "dir"), ("b.txt", "file"), ("link", "symlink"),
    ]  # fmt: skip
    assert body["entries"][1]["size"] == 4
    assert tool.calls[-1] == ("ls", "--json", "b" * 64, "/data/apps/site")

    res = api.get(url, params={"destination_id": dest["id"], "path": "/data/apps/site/data/"})
    assert res.status_code == 200 and res.json()["path"] == "/data/apps/site/data"


@pytest.mark.parametrize(
    "path", ["/", "/etc", "/site/../etc", "/sitex", "/site/..", "/site\\x", "site"]
)
def test_version_files_refuse_paths_outside_the_version(
    versions_api: tuple[TestClient, VersionsRestic], tmp_path: Path, path: str
) -> None:
    api, tool = versions_api
    dest = add_destination(api, tmp_path)
    url = f"/api/backup/versions/{'b' * 64}/files"
    res = api.get(url, params={"destination_id": dest["id"], "path": path})
    assert res.status_code == 400, res.text
    assert not [a for a in tool.calls if a[0] == "ls"]


def test_version_ids_are_checked_before_restic_sees_them(
    versions_api: tuple[TestClient, VersionsRestic], tmp_path: Path
) -> None:
    api, tool = versions_api
    dest = add_destination(api, tmp_path)
    for bad in ("--help", "latest", "ABCDEF12", "abc"):
        res = api.get(f"/api/backup/versions/{bad}/files", params={"destination_id": dest["id"]})
        assert res.status_code in (400, 404), bad
    assert not [a for a in tool.calls if a[0] == "ls"]


def test_version_routes_are_admin_only(
    versions_api: tuple[TestClient, VersionsRestic], tmp_path: Path
) -> None:
    api, _ = versions_api
    dest = add_destination(api, tmp_path)
    with api.app.state.db.engine.begin() as conn:  # type: ignore[attr-defined]
        conn.exec_driver_sql("UPDATE users SET is_admin = 0")
    assert api.get("/api/backup/versions").status_code == 403
    res = api.get(f"/api/backup/versions/{'b' * 64}/files", params={"destination_id": dest["id"]})
    assert res.status_code == 403


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


@needs_restic
def test_real_restic_applies_retention_and_lists_versions(
    tmp_path: Path, compose_log: Path
) -> None:
    for c in real_client(tmp_path):
        folder = add_app(c)
        dest = c.post(
            "/api/backup/destinations",
            json={
                "name": "USB",
                "path": str(tmp_path / "repo"),
                "password": PASSWORD,
                "recovery_kit_saved": True,
            },
        ).json()
        keep = {"keep_last": 2, "keep_daily": 0, "keep_weekly": 0, "keep_monthly": 0}
        plan = add_plan(c, dest, items={"athena": True, "apps": [{"name": "site"}]}, retention=keep)
        for n in range(4):
            (folder / "data" / f"file{n}.txt").write_text(f"version {n}")
            job = run(c, plan)
            assert job["status"] == "succeeded", job
            time.sleep(1.1)  # versions with the same second sort unpredictably
        # Two versions of each item are kept, so four snapshots in all.
        snaps = restic_json(tmp_path, "snapshots")
        assert isinstance(snaps, list) and len(snaps) == 4
        assert (
            any("Running restic prune" in line for line in job["lines"]) is False
        )  # not due again
        row = plan_row(c, plan["id"])
        assert row.last_status == "ok"

        res = c.get("/api/backup/versions", params={"destination_id": dest["id"]})
        assert res.status_code == 200, res.text
        got = res.json()
        assert len(got) == 4
        assert [v["time"] for v in got] == sorted((v["time"] for v in got), reverse=True)
        site = c.get(
            "/api/backup/versions", params={"destination_id": dest["id"], "item": "app:site"}
        ).json()
        assert len(site) == 2 and {v["item"] for v in site} == {"app:site"}
        assert site[0]["files_added"] == 1  # file3.txt against the version before it
        assert site[0]["files_removed"] == 0 and site[0]["size"] > 0
        assert site[0]["os"] and site[0]["athena_version"]

        url = f"/api/backup/versions/{site[0]['id']}/files"
        root = c.get(url, params={"destination_id": dest["id"]}).json()
        assert root["path"] == root["root"] and root["root"].endswith("/data/apps/site")
        assert [e["name"] for e in root["entries"]] == ["data", "compose.yaml"]
        files = c.get(
            url, params={"destination_id": dest["id"], "path": root["root"] + "/data"}
        ).json()
        assert [e["name"] for e in files["entries"]] == [
            "file.txt", "file0.txt", "file1.txt", "file2.txt", "file3.txt"
        ]  # fmt: skip
        assert files["entries"][0]["size"] == 5

        # An older version has only the files it was taken with.
        older = c.get(
            f"/api/backup/versions/{site[1]['id']}/files",
            params={"destination_id": dest["id"], "path": root["root"] + "/data"},
        ).json()
        assert "file3.txt" not in [e["name"] for e in older["entries"]]
