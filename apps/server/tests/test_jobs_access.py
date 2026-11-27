"""Who may read a job: admins any; plain users only jobs their own routes start."""

from pathlib import Path

from conftest import make_app, signed_in
from fastapi.testclient import TestClient

from athena.jobs import Job


async def _noop(job: Job) -> None:
    await job.log("installing, with output only an admin should see")


def test_a_plain_user_can_only_read_jobs_a_user_route_started(tmp_path: Path) -> None:
    with TestClient(make_app(tmp_path)) as admin:
        signed_in(admin)
        pw = "bobs-password-1"
        admin.post("/api/users", json={"username": "bob", "password": pw, "is_admin": False})
        bob = TestClient(admin.app)
        res = bob.post("/api/auth/login", json={"username": "bob", "password": pw})
        bob.headers["X-CSRF-Token"] = res.json()["csrf_token"]

        jobs = admin.app.state.jobs
        # Start them on the app's event loop, as a route would.
        private = admin.portal.call(lambda: jobs.start("Install something", _noop))
        shared = admin.portal.call(lambda: jobs.start("Start an app", _noop, user_visible=True))

        for path in ("", "/events", "/cancel"):
            send = bob.post if path == "/cancel" else bob.get
            assert send(f"/api/jobs/{private.id}{path}").status_code == 404, path
        assert bob.get(f"/api/jobs/{shared.id}").status_code == 200
        assert admin.get(f"/api/jobs/{private.id}").status_code == 200
