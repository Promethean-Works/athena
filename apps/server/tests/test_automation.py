"""Automation triggers and job runs."""

from conftest import make_app, signed_in
from fastapi.testclient import TestClient

from athena.automation.service import compute_next_run
from athena.db.models import AutomationTrigger

ADMIN = {"username": "admin", "password": "correct horse battery"}


def _client(tmp_path):
    app = make_app(tmp_path)
    client = TestClient(app)
    client.__enter__()  # run the lifespan so the automation scheduler starts
    signed_in(client)
    return client, app


def test_triggers_need_a_session(tmp_path):
    client = TestClient(make_app(tmp_path))
    assert client.get("/api/automation/triggers").status_code == 401
    assert client.post("/api/automation/triggers", json={}).status_code == 401


def test_create_list_get_update_delete_cron_trigger(tmp_path):
    client, _ = _client(tmp_path)

    body = {
        "kind": "cron",
        "name": "nightly backup",
        "cron_expression": "0 2 * * *",
        "action": {"kind": "app", "name": "home-assistant", "verb": "restart"},
        "enabled": True,
    }
    r = client.post("/api/automation/triggers", json=body)
    assert r.status_code == 201, r.text
    trigger = r.json()
    assert trigger["id"] and trigger["kind"] == "cron"
    assert trigger["next_run_at"] is not None  # computed at creation
    assert trigger["webhook_token"] is None

    # list
    r = client.get("/api/automation/triggers")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["name"] == "nightly backup"

    # get
    r = client.get(f"/api/automation/triggers/{trigger['id']}")
    assert r.status_code == 200
    assert r.json()["name"] == "nightly backup"

    # update
    r = client.patch(
        f"/api/automation/triggers/{trigger['id']}",
        json={
            "kind": "cron",
            "name": "nightly backup v2",
            "cron_expression": "0 3 * * *",
            "action": {"kind": "app", "name": "home-assistant", "verb": "stop"},
            "enabled": True,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "nightly backup v2"
    assert r.json()["action"]["verb"] == "stop"

    # disable
    r = client.patch(
        f"/api/automation/triggers/{trigger['id']}",
        json={
            "kind": "cron",
            "name": "nightly backup v2",
            "cron_expression": "0 3 * * *",
            "action": {"kind": "app", "name": "home-assistant", "verb": "stop"},
            "enabled": False,
        },
    )
    assert r.status_code == 200
    assert r.json()["enabled"] is False

    # delete
    r = client.delete(f"/api/automation/triggers/{trigger['id']}")
    assert r.status_code == 204, r.text
    r = client.get("/api/automation/triggers")
    assert r.status_code == 200
    assert r.json() == []


def test_invalid_cron_expression_rejected(tmp_path):
    client, _ = _client(tmp_path)
    r = client.post(
        "/api/automation/triggers",
        json={
            "kind": "cron",
            "name": "bad",
            "cron_expression": "not a cron",
            "action": {"kind": "app", "name": "x", "verb": "start"},
            "enabled": True,
        },
    )
    assert r.status_code == 422, r.text


def test_missing_cron_expression_rejected(tmp_path):
    client, _ = _client(tmp_path)
    r = client.post(
        "/api/automation/triggers",
        json={
            "kind": "cron",
            "name": "bad",
            "action": {"kind": "app", "name": "x", "verb": "start"},
            "enabled": True,
        },
    )
    assert r.status_code == 422, r.text


def test_http_trigger_gets_webhook_token(tmp_path):
    client, _ = _client(tmp_path)
    r = client.post(
        "/api/automation/triggers",
        json={
            "kind": "http",
            "name": "webhook job",
            "action": {"kind": "app", "name": "x", "verb": "start"},
            "enabled": True,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["webhook_token"] is not None
    assert len(r.json()["webhook_token"]) == 32


def test_webhook_fires_http_trigger(tmp_path):
    client, app = _client(tmp_path)
    r = client.post(
        "/api/automation/triggers",
        json={
            "kind": "http",
            "name": "webhook job",
            "action": {"kind": "app", "name": "x", "verb": "start"},
            "enabled": True,
        },
    )
    assert r.status_code == 201, r.text
    token = r.json()["webhook_token"]

    # No session needed: the token is the credential. Same app so the trigger
    # exists in the same in-memory DB and job manager.
    public = TestClient(app)
    r = public.post(f"/api/automation/webhook/{token}")
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "started"
    assert r.json()["job_run_id"]


def test_webhook_unknown_token(tmp_path):
    _, app = _client(tmp_path)
    public = TestClient(app)
    r = public.post("/api/automation/webhook/doesnotexist")
    assert r.status_code == 404, r.text


def test_webhook_disabled_or_wrong_kind(tmp_path):
    client, app = _client(tmp_path)
    public = TestClient(app)

    # Disabled http trigger.
    r = client.post(
        "/api/automation/triggers",
        json={
            "kind": "http",
            "name": "disabled webhook",
            "action": {"kind": "app", "name": "x", "verb": "start"},
            "enabled": False,
        },
    )
    assert r.status_code == 201, r.text
    disabled_token = r.json()["webhook_token"]

    r = public.post(f"/api/automation/webhook/{disabled_token}")
    assert r.status_code == 403, r.text


def test_compute_next_run_preserves_timezone():
    from datetime import UTC, datetime

    base = datetime(2026, 11, 17, 23, 20, 0, tzinfo=UTC)
    nxt = compute_next_run("*/5 * * * *", base)
    assert nxt == datetime(2026, 11, 17, 23, 25, 0, tzinfo=UTC)


def test_firing_trigger_creates_and_updates_job_run(tmp_path):
    client, app = _client(tmp_path)

    # Create a cron trigger whose next run is in the past, so the scheduler
    # fires it as soon as the automation event is woken.
    r = client.post(
        "/api/automation/triggers",
        json={
            "kind": "cron",
            "name": "fired job",
            "cron_expression": "* * * * *",
            "action": {"kind": "app", "name": "home-assistant", "verb": "restart"},
            "enabled": True,
        },
    )
    assert r.status_code == 201, r.text
    trigger_id = r.json()["id"]

    # Backdate next_run_at so the scheduler considers it due right away.
    from datetime import UTC, datetime, timedelta

    from sqlmodel import Session

    with Session(app.state.db.engine) as session:
        trigger = session.get(AutomationTrigger, trigger_id)
        trigger.next_run_at = datetime.now(UTC) - timedelta(minutes=5)
        session.add(trigger)
        session.commit()

    app.state.automation_event.set()

    # Poll via HTTP (each request yields to the event loop, letting the
    # scheduler fire the trigger and the job complete).
    run_id = None
    runs = []
    for _ in range(40):
        r = client.get("/api/automation/jobs")
        assert r.status_code == 200
        runs = r.json()
        if runs and runs[0]["status"] != "running":
            run_id = runs[0]["id"]
            break

    assert run_id is not None, f"scheduler did not fire the trigger; jobs={runs}"
    run = runs[0]
    # No container runtime on this fake host, so the app action fails and the
    # run is recorded as failed with an error.
    assert run["status"] == "failed", run
    assert run["error"] is not None and "runtime" in run["error"].lower(), run
    assert run["trigger_id"] == trigger_id


def test_job_run_detail_endpoint(tmp_path):
    client, _ = _client(tmp_path)
    r = client.get("/api/automation/jobs/nonexistent")
    assert r.status_code == 404


def test_validate_action_endpoint(tmp_path):
    client, _ = _client(tmp_path)
    r = client.post(
        "/api/automation/triggers/validate-action",
        json={
            "action": {"kind": "package", "manager": "apt", "name": "jq", "verb": "install"},
        },
    )
    assert r.status_code == 200, r.text


def test_updating_http_trigger_keeps_webhook_token(tmp_path):
    client, _ = _client(tmp_path)
    body = {
        "kind": "http",
        "name": "webhook job",
        "action": {"kind": "app", "name": "x", "verb": "start"},
        "enabled": True,
    }
    r = client.post("/api/automation/triggers", json=body)
    assert r.status_code == 201, r.text
    trigger = r.json()

    r = client.patch(f"/api/automation/triggers/{trigger['id']}", json={**body, "enabled": False})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is False
    assert r.json()["webhook_token"] == trigger["webhook_token"]
