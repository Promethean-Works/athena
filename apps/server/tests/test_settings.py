from pathlib import Path

from conftest import ADMIN, make_app, signed_in
from fastapi.testclient import TestClient

from athena.auth.deps import COOKIE_NAME

NEW = "a much better password"


def test_settings_require_a_session(tmp_path: Path) -> None:
    client = TestClient(make_app(tmp_path))
    assert client.get("/api/settings/appearance").status_code == 401
    assert client.put("/api/settings/appearance", json={}).status_code == 401
    assert client.post("/api/auth/password", json={}).status_code == 401


def test_appearance_defaults_then_saved(tmp_path: Path) -> None:
    client = signed_in(TestClient(make_app(tmp_path)))
    assert client.get("/api/settings/appearance").json() == {
        "mode": "system",
        "base_color": "neutral",
        "theme": "neutral",
        "chart_color": "neutral",
        "font": "inter",
        "font_heading": "inherit",
        "radius": "default",
    }
    chosen = {
        "mode": "dark",
        "base_color": "stone",
        "theme": "blue",
        "chart_color": "emerald",
        "font": "geist",
        "font_heading": "lora",
        "radius": "large",
    }
    res = client.put("/api/settings/appearance", json=chosen)
    assert res.status_code == 200, res.text
    assert client.get("/api/settings/appearance").json() == chosen


def test_appearance_partial_update_fills_defaults(tmp_path: Path) -> None:
    client = signed_in(TestClient(make_app(tmp_path)))
    assert client.put("/api/settings/appearance", json={"theme": "rose"}).status_code == 200
    got = client.get("/api/settings/appearance").json()
    assert got["theme"] == "rose" and got["base_color"] == "neutral"


def test_appearance_rejects_bad_values(tmp_path: Path) -> None:
    client = signed_in(TestClient(make_app(tmp_path)))
    for body in ({"mode": "sepia"}, {"theme": "Blue!"}, {"font": "x" * 40}, {"radius": ""}):
        assert client.put("/api/settings/appearance", json=body).status_code == 422, body


def test_appearance_needs_csrf(tmp_path: Path) -> None:
    client = signed_in(TestClient(make_app(tmp_path)))
    del client.headers["X-CSRF-Token"]
    assert client.put("/api/settings/appearance", json={}).status_code == 403


def test_stored_garbage_falls_back_to_defaults(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    client = signed_in(TestClient(app))
    with app.state.db.engine.begin() as conn:
        conn.exec_driver_sql("UPDATE users SET appearance = '{not json'")
    assert client.get("/api/settings/appearance").json()["theme"] == "neutral"


def test_change_password_keeps_this_session_only(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    client = signed_in(TestClient(app))
    other = TestClient(app)
    assert other.post("/api/auth/login", json=ADMIN).status_code == 200
    assert other.get("/api/settings/appearance").status_code == 200

    res = client.post(
        "/api/auth/password",
        json={"current_password": ADMIN["password"], "new_password": NEW},
    )
    assert res.status_code == 204, res.text
    assert client.get("/api/settings/appearance").status_code == 200  # still signed in
    assert other.get("/api/settings/appearance").status_code == 401  # signed out

    fresh = TestClient(app)
    assert fresh.post("/api/auth/login", json=ADMIN).status_code == 401
    assert (
        fresh.post("/api/auth/login", json={"username": "admin", "password": NEW}).status_code
        == 200
    )
    audit = [
        r[0] for r in app.state.db.engine.connect().exec_driver_sql("SELECT action FROM audit_log")
    ]
    assert "auth.password" in audit


def test_change_password_wrong_current_is_400_not_401(tmp_path: Path) -> None:
    client = signed_in(TestClient(make_app(tmp_path)))
    res = client.post("/api/auth/password", json={"current_password": "nope", "new_password": NEW})
    assert res.status_code == 400
    assert res.json()["detail"] == "Current password is wrong"
    assert client.cookies.get(COOKIE_NAME)
    assert client.get("/api/settings/appearance").status_code == 200


def test_change_password_rules(tmp_path: Path) -> None:
    client = signed_in(TestClient(make_app(tmp_path)))
    short = client.post(
        "/api/auth/password", json={"current_password": ADMIN["password"], "new_password": "x"}
    )
    assert short.status_code == 422
    same = client.post(
        "/api/auth/password",
        json={"current_password": ADMIN["password"], "new_password": ADMIN["password"]},
    )
    assert same.status_code == 400


def test_change_password_is_throttled(tmp_path: Path) -> None:
    client = signed_in(TestClient(make_app(tmp_path)))
    codes = [
        client.post(
            "/api/auth/password", json={"current_password": "wrong", "new_password": NEW}
        ).status_code
        for _ in range(6)
    ]
    assert codes[:5] == [400] * 5
    assert codes[5] == 429


def test_dashboard_layout_defaults_saves_and_resets(tmp_path: Path) -> None:
    client = signed_in(TestClient(make_app(tmp_path)))
    assert client.get("/api/settings/dashboard").json() == {"cards": None}
    layout = {"cards": [{"id": "stats", "size": "full"}, {"id": "storage", "size": "half"}]}
    res = client.put("/api/settings/dashboard", json=layout)
    assert res.status_code == 200, res.text
    assert client.get("/api/settings/dashboard").json() == layout
    # A card id the server doesn't know is fine: the UI owns the list.
    res = client.put("/api/settings/dashboard", json={"cards": [{"id": "future-card"}]})
    assert res.json() == {"cards": [{"id": "future-card", "size": "half"}]}
    assert client.put("/api/settings/dashboard", json={"cards": None}).status_code == 200
    assert client.get("/api/settings/dashboard").json() == {"cards": None}


def test_dashboard_layout_is_validated(tmp_path: Path) -> None:
    client = signed_in(TestClient(make_app(tmp_path)))
    bad = [
        {"cards": [{"id": "Stats"}]},
        {"cards": [{"id": "x" * 41}]},
        {"cards": [{"id": "stats", "size": "huge"}]},
        {"cards": [{"id": "stats"}, {"id": "stats"}]},
        {"cards": [{"id": f"c{i}"} for i in range(41)]},
    ]
    for body in bad:
        assert client.put("/api/settings/dashboard", json=body).status_code == 422, body


def test_dashboard_layout_ignores_invalid_stored_json(tmp_path: Path) -> None:
    client = signed_in(TestClient(make_app(tmp_path)))
    with client.app.state.db.engine.begin() as conn:  # type: ignore[attr-defined]
        conn.exec_driver_sql("UPDATE users SET dashboard = '{\"cards\": 5}'")
    assert client.get("/api/settings/dashboard").json() == {"cards": None}


def test_audit_list_is_admin_only_newest_first_without_detail(tmp_path: Path) -> None:
    from sqlmodel import Session

    from athena import audit

    client = signed_in(TestClient(make_app(tmp_path)))
    with Session(client.app.state.db.engine) as db:  # type: ignore[attr-defined]
        for i in range(3):
            audit.record(db, "admin", "app.start", f"athena-test-{i}", detail="secret-ish")
    res = client.get("/api/audit", params={"limit": 2})
    assert res.status_code == 200, res.text
    rows = res.json()
    assert [r["target"] for r in rows] == ["athena-test-2", "athena-test-1"]
    assert all("detail" not in r for r in rows)
    assert client.get("/api/audit", params={"limit": 51}).status_code == 422
    with client.app.state.db.engine.begin() as conn:  # type: ignore[attr-defined]
        conn.exec_driver_sql("UPDATE users SET is_admin = 0")
    assert client.get("/api/audit").status_code == 403
