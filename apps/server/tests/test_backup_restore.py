"""Restoring one app from a version (docs/specs/backup.md, part 2d)."""

import asyncio
import json
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import make_app, signed_in
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from test_backup import PASSWORD, FakeProvider, needs_restic
from test_backup_snapshots import (
    COMPOSE,
    REAL_RESTIC,
    StreamingFakeRestic,
    add_app,
    add_destination,
    add_plan,
    audit_entries,
    compose_calls,
    real_client,
    run,
    wait,
)
from test_containers import SAMPLE, ready_store

from athena.apps.store import AppStore
from athena.backup import restore, snapshots
from athena.backup.restic import ResticError, Result
from athena.containers import service as containers_service
from athena.db.models import App

VERSION = "a" * 64
ROOT = "/data/apps/site"


def snapshot_json(tags: list[str], paths: list[str] | None = None) -> str:
    return json.dumps(
        [{"id": VERSION, "time": "2026-11-20T03:00:00Z", "paths": paths or [ROOT], "tags": tags}]
    )


class RestoreRestic(StreamingFakeRestic):
    """`snapshots` answers one version; `restore` writes an app folder into the target."""

    def __init__(self) -> None:
        super().__init__()
        self.tags = ["app:site", "athena-version:0.1.0", f"os:{sys.platform}"]
        self.files: dict[str, str] = {"compose.yaml": COMPOSE, "data/file.txt": "old"}
        self.exit_code = 0
        self.hang = False
        self.restoring = False

    async def run(self, repo, *args, timeout=0, stdin=None):  # type: ignore[no-untyped-def,override]
        self.calls.append(args)
        self.repos.append(repo)
        if args[0] == "snapshots":
            return Result(0, snapshot_json(self.tags), "")
        return Result(0, "", "")

    async def stream(self, repo, *args, on_line, timeout=0):  # type: ignore[no-untyped-def,override]
        self.streamed.append(args)
        self.repos.append(repo)
        assert args[0] == "restore"
        self.restoring = True
        if self.hang:
            await asyncio.sleep(3600)
        await on_line(json.dumps({"message_type": "status", "percent_done": 0.5}))
        if self.exit_code:
            return Result(self.exit_code, "", "Fatal: boom")
        target = Path(args[args.index("--target") + 1]) / ROOT.strip("/")
        for name, text in self.files.items():
            (target / name).parent.mkdir(parents=True, exist_ok=True)
            (target / name).write_text(text)
        return Result(0, "", "")


@pytest.fixture
def fail() -> set[str]:
    """Compose actions (`stop`, `up`) that should fail."""
    return set()


@pytest.fixture
def compose_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail: set[str]) -> Path:
    """`docker compose <action>` appends `<project> <action>` to a file (or fails)."""
    log = tmp_path / "compose.log"
    monkeypatch.setattr("athena.containers.runtime.shutil.which", lambda b: f"/usr/bin/{b}")

    def fake(runtime, name, path, *args):  # type: ignore[no-untyped-def]
        code = f"open({str(log)!r}, 'a').write('{name} {args[0]}\\n')"
        if args[0] in fail:
            code += "; raise SystemExit(1)"
        return [sys.executable, "-c", code]

    monkeypatch.setattr(restore, "compose", fake)
    monkeypatch.setattr(snapshots, "compose", fake)
    running = SAMPLE.model_copy(update={"project": "site", "state": "running"})
    monkeypatch.setattr(containers_service, "list_containers", lambda rt: [running])
    return log


@pytest.fixture
def tool() -> RestoreRestic:
    return RestoreRestic()


@pytest.fixture
def api(tmp_path: Path, tool: RestoreRestic, compose_log: Path) -> Iterator[TestClient]:
    app = make_app(tmp_path, store=ready_store(), backup_allowed_roots=[tmp_path])
    app.state.restic = FakeProvider(tool)
    with TestClient(app) as client:
        yield signed_in(client)


def restore_app(c: TestClient, dest: dict, **kwargs) -> dict:  # type: ignore[no-untyped-def]
    res = c.post(
        "/api/backup/restore/app",
        json={"destination_id": dest["id"], "version_id": VERSION, **kwargs},
    )
    assert res.status_code == 202, res.text
    return wait(c, res.json()["id"])


def asides(c: TestClient) -> list[Path]:
    store = AppStore(c.app.state.settings.data_dir)  # type: ignore[attr-defined]
    return [p for p, _, _ in restore.aside_folders(store)]


def test_restoring_the_same_app_replaces_its_folder_and_keeps_the_old_one(
    api: TestClient, tmp_path: Path, compose_log: Path
) -> None:
    folder = add_app(api)
    (folder / "data" / "file.txt").write_text("new")
    dest = add_destination(api, tmp_path)
    job = restore_app(api, dest)
    assert job["status"] == "succeeded", job
    assert (folder / "data" / "file.txt").read_text() == "old"
    assert compose_calls(compose_log) == ["site stop", "site up"]
    [aside] = asides(api)
    assert aside.name.startswith("site.before-restore-")
    assert (aside / "data" / "file.txt").read_text() == "new"
    assert api.app.state.app_jobs == {}  # type: ignore[attr-defined]
    assert not (
        api.app.state.settings.data_dir / "cache" / "backup" / f"restore-{'a' * 16}"
    ).exists()  # type: ignore[attr-defined]
    assert any(e.action == "backup.restore" and e.target == "site" for e in audit_entries(api))
    assert PASSWORD not in json.dumps(job)


def test_the_password_stays_out_of_argv(
    api: TestClient, tmp_path: Path, tool: RestoreRestic
) -> None:
    add_app(api)
    restore_app(api, add_destination(api, tmp_path))
    assert tool.streamed and PASSWORD not in json.dumps(tool.streamed)
    assert tool.repos[-1].password == PASSWORD


def test_a_new_name_creates_an_app_beside_the_original(
    api: TestClient, tmp_path: Path, compose_log: Path
) -> None:
    folder = add_app(api)
    (folder / "data" / "file.txt").write_text("new")
    job = restore_app(api, add_destination(api, tmp_path), name="site-copy")
    assert job["status"] == "succeeded", job
    store = AppStore(api.app.state.settings.data_dir)  # type: ignore[attr-defined]
    assert (store.dir("site-copy") / "data" / "file.txt").read_text() == "old"
    assert (folder / "data" / "file.txt").read_text() == "new"  # the original is untouched
    assert compose_calls(compose_log) == ["site-copy up"]
    assert asides(api) == []
    with Session(api.app.state.db.engine) as db:  # type: ignore[attr-defined]
        assert db.exec(select(App).where(App.name == "site-copy")).first() is not None


def test_a_deleted_app_comes_back_under_its_own_name(
    api: TestClient, tmp_path: Path, compose_log: Path
) -> None:
    dest = add_destination(api, tmp_path)
    job = restore_app(api, dest)
    assert job["status"] == "succeeded", job
    assert compose_calls(compose_log) == ["site up"]
    with Session(api.app.state.db.engine) as db:  # type: ignore[attr-defined]
        assert db.exec(select(App).where(App.name == "site")).first() is not None


def post(c: TestClient, dest: dict, **kwargs):  # type: ignore[no-untyped-def]
    return c.post(
        "/api/backup/restore/app",
        json={"destination_id": dest["id"], "version_id": VERSION, **kwargs},
    )


def test_requests_are_validated_before_a_job_starts(
    api: TestClient, tmp_path: Path, tool: RestoreRestic
) -> None:
    add_app(api)
    add_app(api, "taken")
    dest = add_destination(api, tmp_path)
    assert post(api, dest, name="taken").status_code == 409
    assert post(api, dest, name="Not Valid").status_code == 400
    assert post(api, dest, version_id="../etc").status_code == 400
    assert (
        api.post(
            "/api/backup/restore/app", json={"destination_id": "x", "version_id": VERSION}
        ).status_code
        == 404
    )
    tool.tags = ["athena", "os:linux"]
    res = post(api, dest)
    assert res.status_code == 400 and "isn't an app's" in res.json()["detail"]
    assert tool.streamed == []
    # A folder without an app row is never overwritten.
    tool.tags = ["app:orphan"]
    (api.app.state.settings.data_dir / "apps" / "orphan").mkdir()  # type: ignore[attr-defined]
    assert post(api, dest).status_code == 409


def test_a_busy_app_is_refused(api: TestClient, tmp_path: Path) -> None:
    add_app(api)
    dest = add_destination(api, tmp_path)
    api.app.state.app_jobs["site"] = "other-job"  # type: ignore[attr-defined]
    assert post(api, dest).status_code == 409


def test_a_failed_restic_restore_leaves_the_app_alone(
    api: TestClient, tmp_path: Path, tool: RestoreRestic, compose_log: Path
) -> None:
    folder = add_app(api)
    tool.exit_code = 1
    job = restore_app(api, add_destination(api, tmp_path))
    assert job["status"] == "failed" and "boom" in job["error"]
    assert compose_calls(compose_log) == []  # never stopped
    assert (folder / "data" / "file.txt").read_text() == "hello"
    assert asides(api) == []
    assert api.app.state.app_jobs == {}  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "files, message",
    [
        ({"data/file.txt": "x"}, "no compose.yaml"),
        ({"compose.yaml": "services: nope"}, "isn't usable"),
    ],
)
def test_a_version_that_is_not_an_app_is_refused_before_anything_stops(
    api: TestClient, tmp_path: Path, tool: RestoreRestic, compose_log: Path, files, message
) -> None:  # type: ignore[no-untyped-def]
    folder = add_app(api)
    tool.files = files
    job = restore_app(api, add_destination(api, tmp_path))
    assert job["status"] == "failed" and message in job["error"]
    assert compose_calls(compose_log) == []
    assert (folder / "data" / "file.txt").read_text() == "hello"


def test_a_symlinked_compose_file_is_refused(
    api: TestClient, tmp_path: Path, tool: RestoreRestic
) -> None:
    folder = add_app(api)
    outside = tmp_path / "outside.yaml"
    outside.write_text(COMPOSE)
    staging = tmp_path / "stage"
    app = staging / "site"
    app.mkdir(parents=True)
    try:
        (app / "compose.yaml").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks aren't available")
    with pytest.raises(ResticError, match=r"no compose\.yaml"):
        restore.check_staged(app, staging)
    assert (folder / "compose.yaml").is_file()


def test_a_failure_to_start_is_reported_and_the_old_folder_kept(
    api: TestClient, tmp_path: Path, compose_log: Path, fail: set[str]
) -> None:
    folder = add_app(api)
    fail.add("up")
    job = restore_app(api, add_destination(api, tmp_path))
    assert job["status"] == "failed" and "site could not be started" in job["error"]
    assert (folder / "data" / "file.txt").read_text() == "old"  # the restore itself happened
    assert len(asides(api)) == 1


def test_a_failed_stop_changes_nothing_and_starts_the_app_again(
    api: TestClient, tmp_path: Path, compose_log: Path, fail: set[str]
) -> None:
    folder = add_app(api)
    fail.add("stop")
    job = restore_app(api, add_destination(api, tmp_path))
    assert job["status"] == "failed" and "stop failed" in job["error"]
    assert compose_calls(compose_log) == ["site stop", "site up"]
    assert (folder / "data" / "file.txt").read_text() == "hello"
    assert asides(api) == []


def test_cancelling_while_restoring_files_touches_nothing(
    api: TestClient, tmp_path: Path, tool: RestoreRestic, compose_log: Path
) -> None:
    folder = add_app(api)
    tool.hang = True
    dest = add_destination(api, tmp_path)
    job_id = post(api, dest).json()["id"]
    for _ in range(200):
        if tool.restoring:
            break
        time.sleep(0.05)
    assert api.post(f"/api/jobs/{job_id}/cancel").status_code == 202
    job = wait(api, job_id)
    assert job["status"] == "failed" and job["error"] == "Cancelled"
    assert compose_calls(compose_log) == []
    assert (folder / "data" / "file.txt").read_text() == "hello"
    assert api.app.state.app_jobs == {}  # type: ignore[attr-defined]


def test_a_windows_style_root_is_found_in_the_staging_folder(tmp_path: Path) -> None:
    assert restore._staged_folder(tmp_path, "/C/athena/apps/site") == (
        tmp_path / "C" / "athena" / "apps" / "site"
    )


def test_old_moved_aside_folders_are_swept_by_age(tmp_path: Path) -> None:
    store = AppStore(tmp_path)
    now = datetime(2026, 11, 22, tzinfo=UTC)
    for name, when in (
        ("site", now - timedelta(days=8)),
        ("site", now - timedelta(days=1)),
        ("other", now - timedelta(days=30)),
    ):
        path = restore.aside_path(store, name, when)
        (path / "data").mkdir(parents=True)
    (store.root / "site").mkdir()
    assert restore.sweep_aside(store, 7, now, "site") == 1
    assert len(restore.aside_folders(store, "site")) == 1
    assert restore.sweep_aside(store, 7, now) == 1  # `other`
    assert (store.root / "site").is_dir()  # the live app is never matched
    assert restore.sweep_aside(store, -1, now) == 1


def test_the_delete_button_removes_only_that_apps_folders(api: TestClient, tmp_path: Path) -> None:
    add_app(api)
    restore_app(api, add_destination(api, tmp_path))
    assert len(asides(api)) == 1
    assert api.delete("/api/backup/apps/other/before-restore").status_code == 204
    assert len(asides(api)) == 1
    assert api.delete("/api/backup/apps/site/before-restore").status_code == 204
    assert asides(api) == []
    assert api.delete("/api/backup/apps/Bad Name/before-restore").status_code == 400


def test_restore_routes_are_admin_only(api: TestClient, tmp_path: Path) -> None:
    add_app(api)
    dest = add_destination(api, tmp_path)
    with api.app.state.db.engine.begin() as conn:  # type: ignore[attr-defined]
        conn.exec_driver_sql("UPDATE users SET is_admin = 0")
    assert post(api, dest).status_code == 403
    assert api.delete("/api/backup/apps/site/before-restore").status_code == 403


# ---------------------------------------------------------------- a real restic


@needs_restic
def test_real_restic_restores_an_older_version_of_an_app(tmp_path: Path, compose_log: Path) -> None:
    assert REAL_RESTIC is not None
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
        plan = add_plan(c, dest, items={"athena": False, "apps": [{"name": "site"}]})
        (folder / "data" / "file.txt").write_text("first")
        assert run(c, plan)["status"] == "succeeded"
        time.sleep(1.1)
        (folder / "data" / "file.txt").write_text("second")
        (folder / "data" / "extra.txt").write_text("only in the second")
        assert run(c, plan)["status"] == "succeeded"
        found = c.get(
            "/api/backup/versions", params={"destination_id": dest["id"], "item": "app:site"}
        ).json()
        oldest = found[-1]
        (folder / "data" / "file.txt").write_text("broken")

        res = c.post(
            "/api/backup/restore/app",
            json={"destination_id": dest["id"], "version_id": oldest["id"]},
        )
        assert res.status_code == 202, res.text
        job = wait(c, res.json()["id"])
        assert job["status"] == "succeeded", job
        assert (folder / "data" / "file.txt").read_text() == "first"
        assert not (folder / "data" / "extra.txt").exists()
        assert (folder / "compose.yaml").read_text() == COMPOSE
        [aside] = asides(c)
        assert (aside / "data" / "file.txt").read_text() == "broken"
        assert compose_calls(compose_log)[-2:] == ["site stop", "site up"]
