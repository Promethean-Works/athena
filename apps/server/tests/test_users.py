"""Multi-user: the users API, and which routes a plain user may call."""

import re
from pathlib import Path

import pytest
from conftest import make_app, signed_in
from fastapi.testclient import TestClient

PASSWORD = "another long password"

# Everything else behind a session is admin-only. A new route is admin-only until it is
# listed here on purpose, so a forgotten guard fails this file instead of shipping.
USER_OPERATIONS = {
    "logout",
    "changePassword",
    "getCapabilities",
    "refreshCapabilities",
    "getJob",
    "streamJobEvents",
    "cancelJob",
    "getSystemInfo",
    "getUpdateInfo",
    "getSystemStats",
    "streamSystemStats",
    "listApps",
    "appAction",
    "listStoreCategories",
    "listStoreApps",
    "getStoreApp",
    "listCatalogs",
    "getAppearance",
    "setAppearance",
    "getDashboardLayout",
    "setDashboardLayout",
    "getSystemSettings",
    "getAiSettings",
    "listFileLocations",
    "listFiles",
    "readTextFile",
    "writeTextFile",
    "createFolder",
    "renameFile",
    "deleteFiles",
    "transferFiles",
    "downloadFile",
    "uploadChunk",
    "cancelUpload",
    "listShares",
    "createShare",
    "updateShare",
    "removeShare",
    "getFeedbackInfo",
    "get_tunnel_status_api_tunnel_status_get",
    "buildIssueUrl",
}


@pytest.fixture
def admin(tmp_path: Path) -> TestClient:
    return signed_in(TestClient(make_app(tmp_path)))


def make_user(admin: TestClient, name: str = "alice", is_admin: bool = False) -> TestClient:
    body = {"username": name, "password": PASSWORD, "is_admin": is_admin}
    assert admin.post("/api/users", json=body).status_code == 201
    other = TestClient(admin.app)
    res = other.post("/api/auth/login", json={"username": name, "password": PASSWORD})
    assert res.status_code == 200, res.text
    other.headers["X-CSRF-Token"] = res.json()["csrf_token"]
    return other


def test_every_protected_route_is_admin_only_unless_listed(admin: TestClient) -> None:
    user = make_user(admin)
    anon = TestClient(admin.app)
    seen: set[str] = set()
    wrong: list[str] = []
    for path, item in admin.app.openapi()["paths"].items():
        if not path.startswith("/api/"):
            continue
        for method, spec in item.items():
            url = re.sub(r"\{[^}]+\}", "1", path)
            if anon.request(method, url).status_code != 401:
                continue  # public
            op = spec["operationId"]
            seen.add(op)
            if op.startswith("stream") or op in {"logout", "changePassword"}:
                continue  # never-ending streams, and calls that end the test user's session
            code = user.request(method, url).status_code
            if op in USER_OPERATIONS:
                if code == 403:
                    wrong.append(f"{method} {path} ({op}) should be open to users")
            else:
                if code != 403:
                    wrong.append(f"{method} {path} ({op}) must be admin-only, got {code}")
    assert not wrong, "\n".join(wrong)
    assert seen >= USER_OPERATIONS, USER_OPERATIONS - seen


def test_user_gets_403_not_401(admin: TestClient) -> None:
    user = make_user(admin)
    assert user.get("/api/users").status_code == 403
    assert user.get("/api/auth/status").json()["user"]["is_admin"] is False


def test_admin_creates_lists_and_removes_users(admin: TestClient) -> None:
    make_user(admin, "alice")
    rows = admin.get("/api/users").json()
    assert [r["username"] for r in rows] == ["admin", "alice"]
    assert rows[1]["is_admin"] is False
    alice = rows[1]["id"]
    assert admin.delete(f"/api/users/{alice}").status_code == 204
    assert [r["username"] for r in admin.get("/api/users").json()] == ["admin"]


def test_username_rules(admin: TestClient) -> None:
    ok = {"username": "bob", "password": PASSWORD}
    assert admin.post("/api/users", json=ok).status_code == 201
    assert admin.post("/api/users", json={**ok, "username": "BOB"}).status_code == 409
    assert admin.post("/api/users", json={**ok, "username": "x"}).status_code == 422
    assert (
        admin.post("/api/users", json={**ok, "username": "carl", "password": "short"}).status_code
        == 422
    )


def test_the_last_admin_stays(admin: TestClient) -> None:
    me = admin.get("/api/users").json()[0]["id"]
    assert admin.delete(f"/api/users/{me}").status_code == 409
    assert admin.patch(f"/api/users/{me}", json={"is_admin": False}).status_code == 409
    make_user(admin, "second", is_admin=True)
    # Two admins: demoting the other one is fine, deleting yourself still isn't.
    assert admin.delete(f"/api/users/{me}").status_code == 409
    other = next(u["id"] for u in admin.get("/api/users").json() if u["username"] == "second")
    assert admin.patch(f"/api/users/{other}", json={"is_admin": False}).status_code == 200
    assert admin.delete(f"/api/users/{other}").status_code == 204


def test_demoting_or_deleting_ends_their_sessions(admin: TestClient) -> None:
    boss = make_user(admin, "boss", is_admin=True)
    assert boss.get("/api/users").status_code == 200
    boss_id = next(u["id"] for u in admin.get("/api/users").json() if u["username"] == "boss")
    admin.patch(f"/api/users/{boss_id}", json={"is_admin": False})
    assert boss.get("/api/users").status_code == 401
    again = make_user.__wrapped__ if False else None  # noqa: F841
    res = TestClient(admin.app).post(
        "/api/auth/login", json={"username": "boss", "password": PASSWORD}
    )
    assert res.json()["user"]["is_admin"] is False
    assert admin.delete(f"/api/users/{boss_id}").status_code == 204
    assert (
        TestClient(admin.app)
        .post("/api/auth/login", json={"username": "boss", "password": PASSWORD})
        .status_code
        == 401
    )


def test_password_reset_signs_the_user_out(admin: TestClient) -> None:
    alice = make_user(admin)
    alice_id = next(u["id"] for u in admin.get("/api/users").json() if u["username"] == "alice")
    res = admin.patch(f"/api/users/{alice_id}", json={"password": "a brand new password"})
    assert res.status_code == 200
    assert alice.get("/api/apps").status_code == 401
    login = TestClient(admin.app).post(
        "/api/auth/login", json={"username": "alice", "password": "a brand new password"}
    )
    assert login.status_code == 200
    assert admin.patch(f"/api/users/{alice_id}", json={}).status_code == 422


def test_users_are_audited(admin: TestClient) -> None:
    make_user(admin)
    actions = [e["action"] for e in admin.get("/api/audit").json()]
    assert "user.create" in actions


def test_mcp_refuses_plain_users(admin: TestClient) -> None:
    user = make_user(admin)
    assert user.post("/api/mcp", json={}).status_code in (401, 403)
