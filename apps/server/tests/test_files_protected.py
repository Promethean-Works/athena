"""Athena's own data folder is closed to plain users and share visitors (pentest F1)."""

import io
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import make_app, signed_in
from fastapi.testclient import TestClient
from test_users import make_user


@pytest.fixture
def setup(tmp_path: Path) -> Iterator[tuple[TestClient, TestClient, int]]:
    """An admin, a plain user, and a location that holds the data folder (as Home does)."""
    data = tmp_path / "data"
    with TestClient(make_app(tmp_path)) as admin:
        signed_in(admin)
        (data / "secret.key").write_text("fernet-key")
        (data / "apps" / "demo").mkdir(parents=True)
        (data / "apps" / "demo" / ".env").write_text("TOKEN=1")
        (data / "apps" / "demo" / "notes.txt").write_text("hello")
        (data / "apps" / "demo" / "compose.yaml").write_text("services: {}")
        (tmp_path / "home").mkdir()
        (tmp_path / "home" / "mine.txt").write_text("mine")
        res = admin.post("/api/files/locations", json={"name": "Root", "path": str(tmp_path)})
        assert res.status_code == 201, res.text
        yield admin, make_user(admin), res.json()["id"]


def list_names(client: TestClient, loc: int, path: str = "") -> list[str]:
    res = client.get("/api/files/list", params={"location": loc, "path": path})
    assert res.status_code == 200, res.text
    return [e["name"] for e in res.json()["entries"]]


def test_admin_keeps_full_access(setup) -> None:
    admin, _, loc = setup
    assert "data" in list_names(admin, loc)
    res = admin.get("/api/files/download", params={"location": loc, "path": "data/secret.key"})
    assert res.content == b"fernet-key"


def test_user_cannot_see_or_read_the_data_folder(setup) -> None:
    _, user, loc = setup
    assert "data" not in list_names(user, loc) and "home" in list_names(user, loc)
    for url, path in [
        ("list", "data"),
        ("download", "data/secret.key"),
        ("text", "data/secret.key"),
        ("list", "data/apps/demo/.env/.."),
    ]:
        res = user.get(f"/api/files/{url}", params={"location": loc, "path": path})
        assert res.status_code in (400, 403), (url, path, res.status_code)
    res = user.get("/api/files/text", params={"location": loc, "path": "data/apps/demo/.env"})
    assert res.status_code == 403


def test_user_still_reaches_app_data_without_env_files(setup, tmp_path: Path) -> None:
    admin, user, _ = setup
    apps = admin.post(
        "/api/files/locations", json={"name": "Apps", "path": str(tmp_path / "data" / "apps")}
    )
    loc = apps.json()["id"]
    assert list_names(user, loc, "demo") == ["notes.txt"]
    res = user.get("/api/files/text", params={"location": loc, "path": "demo/notes.txt"})
    assert res.json()["content"] == "hello"
    res = user.get("/api/files/text", params={"location": loc, "path": "demo/.env"})
    assert res.status_code == 403


def test_zip_and_copy_of_a_parent_skip_the_data_folder(setup, tmp_path: Path) -> None:
    _, user, loc = setup
    res = user.get("/api/files/download", params={"location": loc, "path": ""})
    names = zipfile.ZipFile(io.BytesIO(res.content)).namelist()
    assert any(n.endswith("mine.txt") for n in names)
    assert not any("secret.key" in n or ".env" in n or "data" in n.split("/") for n in names)


def test_user_cannot_delete_or_move_a_folder_holding_it(setup, tmp_path: Path) -> None:
    _, user, loc = setup
    (tmp_path / "home" / "link").symlink_to(tmp_path / "data", target_is_directory=True)
    res = user.get("/api/files/list", params={"location": loc, "path": "home/link"})
    assert res.status_code == 403
    res = user.post(
        "/api/files/delete", json={"location": loc, "paths": ["data"], "permanent": True}
    )
    assert res.status_code == 200 and res.json()["errors"], res.text
    res = user.post(
        "/api/files/transfer",
        json={"op": "move", "location": loc, "paths": ["home"], "dest_location": loc},
    )
    assert res.status_code in (200, 202)
    assert (tmp_path / "data" / "secret.key").exists()


def test_share_link_does_not_serve_the_data_folder(setup) -> None:
    _, user, loc = setup
    res = user.post("/api/shares", json={"location": loc, "path": ""})
    assert res.status_code == 201, res.text
    base = f"/api/public/shares/{res.json()['token']}"
    visitor = TestClient(user.app)
    names = [e["name"] for e in visitor.get(f"{base}/list").json()["entries"]]
    assert "data" not in names
    assert visitor.get(f"{base}/download", params={"path": "data/secret.key"}).status_code == 403


def apps_location(admin: TestClient, tmp_path: Path) -> int:
    res = admin.post(
        "/api/files/locations", json={"name": "Apps", "path": str(tmp_path / "data" / "apps")}
    )
    return res.json()["id"]


def test_app_definitions_cannot_be_read_or_written(setup, tmp_path: Path) -> None:
    admin, user, _ = setup
    loc = apps_location(admin, tmp_path)
    assert list_names(user, loc, "demo") == ["notes.txt"]
    for name in ("compose.yaml", ".env", ".ENV", "Compose.YAML"):
        res = user.get("/api/files/text", params={"location": loc, "path": f"demo/{name}"})
        assert res.status_code == 403, name
    res = user.put(
        "/api/files/text",
        json={"location": loc, "path": "demo/compose.yaml", "content": "services: {evil: {}}"},
    )
    assert res.status_code == 403
    body = {"location": loc, "path": "demo/notes.txt", "name": "compose.yaml"}
    assert user.post("/api/files/rename", json=body).status_code == 403
    up = {"location": loc, "path": "demo", "name": "compose.yaml", "upload_id": "pentest-up-0001"}
    res = user.post(
        "/api/files/upload",
        params={**up, "offset": 0, "total": 4, "overwrite": True},
        content=b"evil",
        headers={"content-type": "application/octet-stream"},
    )
    assert res.status_code == 403
    assert (tmp_path / "data/apps/demo/compose.yaml").read_text() == "services: {}"


def test_user_cannot_move_or_delete_app_folders(setup, tmp_path: Path) -> None:
    admin, user, root = setup
    loc = apps_location(admin, tmp_path)
    (tmp_path / "home" / "x").mkdir()
    for paths in (["demo"],):
        res = user.post(
            "/api/files/delete", json={"location": loc, "paths": paths, "permanent": True}
        )
        assert res.json()["errors"], res.text
    res = user.post(
        "/api/files/transfer",
        json={
            "op": "move",
            "location": loc,
            "paths": ["demo"],
            "dest_location": root,
            "dest_path": "home",
        },
    )
    job = res.json()
    assert (tmp_path / "data/apps/demo/.env").exists(), job
    # and a folder above the data folder
    res = user.post(
        "/api/files/delete", json={"location": root, "paths": ["data"], "permanent": True}
    )
    assert res.json()["errors"]
    assert (tmp_path / "data/secret.key").exists()


def test_odd_spelling_does_not_get_around_it(setup, tmp_path: Path) -> None:
    _, user, loc = setup
    if not (tmp_path / "DATA" / "secret.key").exists():
        pytest.skip("this disk tells DATA and data apart")
    res = user.get("/api/files/text", params={"location": loc, "path": "DATA/secret.key"})
    assert res.status_code == 403
