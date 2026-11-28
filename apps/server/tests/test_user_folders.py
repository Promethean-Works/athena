"""Per-user folders and which locations plain users may open (docs/specs/user-folders.md)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import make_app, signed_in
from fastapi.testclient import TestClient
from test_users import make_user


@pytest.fixture
def admin(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(make_app(tmp_path)) as client:
        yield signed_in(client)


def mine(client: TestClient) -> dict:
    res = client.get("/api/files/locations")
    assert res.status_code == 200, res.text
    own = [loc for loc in res.json() if loc["owner_id"] is not None]
    assert len(own) == 1, res.json()
    return own[0]


def put(client: TestClient, loc: int, name: str, body: bytes, path: str = "") -> int:
    res = client.post(
        "/api/files/upload",
        params={
            "location": loc,
            "path": path,
            "name": name,
            "upload_id": "folders-up-0001",
            "offset": 0,
            "total": len(body),
        },
        content=body,
        headers={"content-type": "application/octet-stream"},
    )
    return res.status_code


def test_a_new_user_has_only_their_own_folder(admin: TestClient, tmp_path: Path) -> None:
    alice = make_user(admin, "alice")
    res = alice.get("/api/files/locations").json()
    assert [loc["owner_id"] is not None for loc in res] == [True]
    loc = res[0]
    assert loc["name"] == "My files (alice)" and loc["writable"] and loc["available"]
    assert (tmp_path / "data" / "users" / str(loc["owner_id"]) / "files").is_dir()
    assert put(alice, loc["id"], "a.txt", b"hi") == 200
    got = alice.get("/api/files/download", params={"location": loc["id"], "path": "a.txt"})
    assert got.content == b"hi"


def test_admin_locations_are_closed_to_users_until_opened(
    admin: TestClient, tmp_path: Path
) -> None:
    (tmp_path / "media").mkdir()
    media = admin.post(
        "/api/files/locations", json={"name": "Media", "path": str(tmp_path / "media")}
    )
    media_id = media.json()["id"]
    alice = make_user(admin, "alice")
    assert media_id not in [loc["id"] for loc in alice.get("/api/files/locations").json()]
    assert alice.get("/api/files/list", params={"location": media_id}).status_code == 404
    assert put(alice, media_id, "x.txt", b"x") == 404
    # An id that doesn't exist looks the same, so ids don't leak.
    assert alice.get("/api/files/list", params={"location": 9999}).status_code == 404

    res = admin.put(
        f"/api/files/locations/{media_id}",
        json={"name": "Media", "path": str(tmp_path / "media"), "users_can_open": True},
    )
    assert res.json()["users_can_open"] is True
    assert alice.get("/api/files/list", params={"location": media_id}).status_code == 200


def test_users_cannot_reach_each_others_folders(admin: TestClient, tmp_path: Path) -> None:
    alice, bob = make_user(admin, "alice"), make_user(admin, "bob")
    a, b = mine(alice), mine(bob)
    assert a["id"] != b["id"]
    assert put(bob, b["id"], "secret.txt", b"bobs") == 200
    assert alice.get("/api/files/list", params={"location": b["id"]}).status_code == 404
    res = alice.get("/api/files/download", params={"location": b["id"], "path": "secret.txt"})
    assert res.status_code == 404
    # Not through an opened location that contains the data folder either.
    root = admin.post(
        "/api/files/locations",
        json={"name": "All", "path": str(tmp_path), "users_can_open": True},
    ).json()["id"]
    rel = f"data/users/{b['owner_id']}/files/secret.txt"
    assert alice.get("/api/files/text", params={"location": root, "path": rel}).status_code == 403
    own = f"data/users/{a['owner_id']}/files"
    assert alice.get("/api/files/list", params={"location": root, "path": own}).status_code == 200
    # Transfers can't name another user's folder as a source or a destination.
    res = alice.post(
        "/api/files/transfer",
        json={"op": "copy", "location": a["id"], "paths": ["x"], "dest_location": b["id"]},
    )
    assert res.status_code == 404


def test_a_users_share_link_works_for_visitors(admin: TestClient) -> None:
    alice = make_user(admin, "alice")
    a = mine(alice)
    assert put(alice, a["id"], "pic.txt", b"public") == 200
    res = alice.post("/api/shares", json={"location": a["id"], "path": "pic.txt"})
    assert res.status_code == 201, res.text
    base = f"/api/public/shares/{res.json()['token']}"
    assert TestClient(admin.app).get(f"{base}/download").content == b"public"


def test_admins_see_every_users_folder_but_cannot_edit_or_remove_it(admin: TestClient) -> None:
    alice = make_user(admin, "alice")
    a = mine(alice)
    names = [loc["name"] for loc in admin.get("/api/files/locations").json()]
    assert "My files (alice)" in names
    body = {"name": "x", "path": a["path"]}
    assert admin.put(f"/api/files/locations/{a['id']}", json=body).status_code == 409
    assert admin.delete(f"/api/files/locations/{a['id']}").status_code == 409


def test_deleting_a_user_deletes_their_folder(admin: TestClient, tmp_path: Path) -> None:
    alice = make_user(admin, "alice")
    a = mine(alice)
    assert put(alice, a["id"], "a.txt", b"gone soon") == 200
    folder = tmp_path / "data" / "users" / str(a["owner_id"])
    assert (folder / "files" / "a.txt").exists()
    assert admin.delete(f"/api/users/{a['owner_id']}").status_code == 204
    assert not folder.exists()
    names = [loc["name"] for loc in admin.get("/api/files/locations").json()]
    assert "My files (alice)" not in names


def test_a_user_cannot_list_other_users_ids_through_the_data_folder(
    admin: TestClient, tmp_path: Path
) -> None:
    alice, bob = make_user(admin, "alice"), make_user(admin, "bob")
    mine(alice), mine(bob)
    root = admin.post(
        "/api/files/locations",
        json={"name": "All", "path": str(tmp_path), "users_can_open": True},
    ).json()["id"]
    for path in ("data/users", f"data/users/{mine(bob)['owner_id']}"):
        res = alice.get("/api/files/list", params={"location": root, "path": path})
        assert res.status_code == 403, path


def test_admins_have_their_own_folder_too(admin: TestClient, tmp_path: Path) -> None:
    res = admin.get("/api/files/locations").json()
    own = [loc for loc in res if loc["owner_id"] is not None]
    assert [loc["name"] for loc in own] == ["My files (admin)"]
    assert (tmp_path / "data" / "users" / str(own[0]["owner_id"]) / "files").is_dir()
    assert put(admin, own[0]["id"], "a.txt", b"admin file") == 200
    alice = make_user(admin, "alice")
    mine(alice)
    assert alice.get("/api/files/list", params={"location": own[0]["id"]}).status_code == 404
