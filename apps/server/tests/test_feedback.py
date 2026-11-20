from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import make_app, signed_in
from fake_probe import FakeProbe
from fastapi.testclient import TestClient
from sqlmodel import Session

from athena import __version__, feedback
from athena.catalog.registry import CatalogRegistry
from athena.config import Settings
from athena.db.models import Catalog
from athena.main import create_app
from athena.platform.detect import detect
from athena.platform.store import CapabilityStore


def query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


@pytest.fixture
def api(tmp_path: Path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        yield signed_in(client)


def add_remote_catalog(api: TestClient, catalog_id: str, url: str) -> None:
    """A remote catalog row plus a copy of the built-in Jellyfin under its id."""
    app = api.app
    jellyfin = app.state.catalogs.get("builtin", "jellyfin")
    apps = [*app.state.catalogs.all(), jellyfin.model_copy(update={"catalog": catalog_id})]
    app.state.catalogs = CatalogRegistry(apps)
    with Session(app.state.db.engine) as session:
        session.add(Catalog(id=catalog_id, name="Big Bear", url=url))
        session.commit()


def test_info_has_diagnostics_but_no_hostname(api: TestClient) -> None:
    info = api.get("/api/feedback").json()
    assert info["version"] == __version__
    assert info["repo_url"] == "https://github.com/tiagozaccaro/athena"
    assert info["arch"] and info["os_version"] and info["runtime"]
    assert "hostname" not in info


def test_feedback_needs_a_session(tmp_path: Path) -> None:
    with TestClient(make_app(tmp_path)) as client:
        assert client.get("/api/feedback").status_code == 401


@pytest.mark.parametrize(
    ("kind", "template"),
    [
        ("bug", "bug_report.yml"),
        ("change", "change_request.yml"),
        ("feature", "feature_request.yml"),
    ],
)
def test_athena_reports_open_the_issue_form(api: TestClient, kind: str, template: str) -> None:
    res = api.post("/api/feedback/issue-url", json={"kind": kind, "title": "Dark mode flickers"})
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["target"] == "athena"
    assert out["target_name"] == "tiagozaccaro/athena"
    assert out["url"].startswith("https://github.com/tiagozaccaro/athena/issues/new?")
    q = query(out["url"])
    assert q["template"] == template
    assert q["title"] == "Dark mode flickers"
    assert q["version"] == __version__
    assert " · " in q["os-details"]


def test_the_template_files_exist_with_the_filled_ids() -> None:
    forms = Path(__file__).parents[3] / ".github" / "ISSUE_TEMPLATE"
    for name in feedback.TEMPLATES.values():
        text = (forms / name).read_text(encoding="utf-8")
        assert "id: version" in text, name
    app_form = (forms / "app_report.yml").read_text(encoding="utf-8")
    for field in ("app", "catalog", "images", "os-details", "logs"):
        assert f"id: {field}\n" in app_form, field


def test_builtin_app_report_fills_the_app_form(api: TestClient) -> None:
    res = api.post(
        "/api/feedback/issue-url",
        json={"kind": "app", "catalog": "builtin", "app_id": "jellyfin", "logs": "boom"},
    )
    out = res.json()
    assert out["target"] == "athena"
    q = query(out["url"])
    assert q["template"] == "app_report.yml"
    assert (q["app"], q["catalog"], q["logs"]) == ("jellyfin", "builtin", "boom")
    assert "jellyfin/jellyfin" in q["images"]
    assert q["title"].startswith("Jellyfin")


def test_unknown_app_is_404(api: TestClient) -> None:
    res = api.post(
        "/api/feedback/issue-url", json={"kind": "app", "catalog": "builtin", "app_id": "nope"}
    )
    assert res.status_code == 404
    assert api.post("/api/feedback/issue-url", json={"kind": "app"}).status_code == 422


@pytest.mark.parametrize(
    ("url", "prefix", "title_key", "body_key"),
    [
        (
            "https://github.com/bigbeartechworld/big-bear-casaos",
            "https://github.com/bigbeartechworld/big-bear-casaos/issues/new?",
            "title",
            "body",
        ),
        (
            "https://codeberg.org/someone/apps.git",
            "https://codeberg.org/someone/apps/issues/new?",
            "title",
            "body",
        ),
        (
            "https://gitlab.com/someone/apps/-/tree/dev",
            "https://gitlab.com/someone/apps/-/issues/new?",
            "issue[title]",
            "issue[description]",
        ),
    ],
)
def test_remote_catalog_app_goes_to_its_repo(
    api: TestClient, url: str, prefix: str, title_key: str, body_key: str
) -> None:
    add_remote_catalog(api, "bigbear", url)
    res = api.post(
        "/api/feedback/issue-url",
        json={"kind": "app", "catalog": "bigbear", "app_id": "jellyfin", "logs": "it broke"},
    )
    out = res.json()
    assert out["target"] == "catalog"
    assert out["target_name"] == "Big Bear"
    assert out["url"].startswith(prefix)
    q = query(out["url"])
    assert q[title_key].startswith("Jellyfin")
    assert "`jellyfin`" in q[body_key] and "it broke" in q[body_key]
    assert __version__ in q[body_key]


def test_archive_catalog_app_falls_back_to_athena(api: TestClient) -> None:
    add_remote_catalog(api, "zip", "https://example.com/apps.zip")
    out = api.post(
        "/api/feedback/issue-url", json={"kind": "app", "catalog": "zip", "app_id": "jellyfin"}
    ).json()
    assert out["target"] == "athena"
    q = query(out["url"])
    assert q["template"] == "app_report.yml"
    assert q["catalog"] == "https://example.com/apps.zip"


def test_logs_keep_the_end_and_say_so(api: TestClient) -> None:
    logs = "\n".join(f"line {i}" for i in range(2000))
    out = api.post(
        "/api/feedback/issue-url",
        json={"kind": "app", "catalog": "builtin", "app_id": "jellyfin", "logs": logs},
    ).json()
    assert out["logs_truncated"] is True
    kept = query(out["url"])["logs"]
    assert len(kept) <= feedback.MAX_LOGS
    assert kept.endswith("line 1999")
    assert kept.startswith("line ")
    assert len(out["url"]) < 8000


def test_feedback_repo_can_point_at_a_fork(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        web_dir=tmp_path / "no-web",
        feedback_repo="https://codeberg.org/fork/athena",
    )
    store = CapabilityStore(detector=lambda: detect(FakeProbe(os="darwin")))
    with TestClient(create_app(settings, capability_store=store)) as client:
        api = signed_in(client)
        out = api.post("/api/feedback/issue-url", json={"kind": "bug", "title": "x"}).json()
    assert out["target_name"] == "fork/athena"
    assert out["url"].startswith("https://codeberg.org/fork/athena/issues/new?")
    assert "**version:**" in query(out["url"])["body"]


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a/b",
        "https://github.com/a",
        "https://example.com/a/b",
        "https://github.com/a/b c",
    ],
)
def test_repo_of_rejects_non_repositories(url: str) -> None:
    assert feedback.repo_of(url) is None


def test_runtime_line_drops_the_socket_path() -> None:
    from athena.api.feedback import _runtime
    from athena.platform.capabilities import Capability

    def manifest(detail: str):
        cap = Capability(
            id="containers", label="Containers", status="ready", provider="colima", detail=detail
        )
        return SimpleNamespace(get=lambda _id: cap)

    line = _runtime(manifest("Engine 29.5.2 at /Users/me/.colima/default/docker.sock"))
    assert line == "colima (Engine 29.5.2)"
    assert _runtime(manifest(r"C:\\Users\\me\\pipe")) == "colima"
