import asyncio
import time
from typing import Any

import pytest
from conftest import make_app, signed_in
from fastapi.testclient import TestClient

from athena import updates
from athena.system_settings import SystemSettings
from athena.updates import UpdateChecker, is_newer, parse_version

URL = "https://updates.invalid/latest"


def release(tag: str, **over: Any) -> dict[str, Any]:
    return {"tag_name": tag, "html_url": f"https://example.invalid/{tag}", **over}


@pytest.mark.parametrize(
    ("latest", "current", "newer"),
    [
        ("v0.2.0", "0.1.0", True),
        ("0.1.1", "0.1.0", True),
        ("1.0", "0.9.9", True),
        ("v0.1.0", "0.1.0", False),
        ("0.1.0", "0.2.0", False),
        ("0.2.0", "0.0.0", False),  # a source checkout never nags
        ("0.2.0-rc1", "0.1.0", False),  # prereleases are not announced
        ("nightly", "0.1.0", False),
    ],
)
def test_is_newer(latest: str, current: str, newer: bool) -> None:
    assert is_newer(latest, current) is newer


def test_parse_version_rejects_prereleases() -> None:
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("1.0.0-rc.1") is None


def check(checker: UpdateChecker) -> bool:
    return asyncio.run(checker.check(URL))


def test_checker_remembers_the_latest_release() -> None:
    checker = UpdateChecker(fetch=lambda url: release("v0.3.0"), current="0.2.0")
    assert check(checker)
    info = checker.info(True)
    assert (info.latest, info.available) == ("0.3.0", True)
    assert info.release_url == "https://example.invalid/v0.3.0"
    assert info.checked_at is not None
    assert info.command.startswith(("curl ", "irm "))


@pytest.mark.parametrize(
    "answer", [release("v9.0.0", prerelease=True), release("v9.0.0", draft=True)]
)
def test_checker_ignores_prereleases_and_drafts(answer: dict[str, Any]) -> None:
    checker = UpdateChecker(fetch=lambda url: answer, current="0.2.0")
    assert check(checker)
    assert checker.info(True).available is False


@pytest.mark.parametrize("error", [OSError("offline"), TimeoutError(), ValueError("bad json")])
def test_checker_survives_offline_and_bad_answers(error: Exception) -> None:
    def fail(url: str) -> dict[str, Any]:
        raise error

    checker = UpdateChecker(fetch=fail, current="0.2.0")
    assert check(checker) is False
    info = checker.info(True)
    assert (info.latest, info.available) == (None, False)


def test_a_failed_check_keeps_the_earlier_answer() -> None:
    answers: list[Any] = [release("v0.3.0"), OSError("offline")]

    def fetch(url: str) -> dict[str, Any]:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    checker = UpdateChecker(fetch=fetch, current="0.2.0")
    assert check(checker)
    assert check(checker) is False
    assert checker.info(True).latest == "0.3.0"


def test_the_request_carries_nothing_identifying(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = {}

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def read(self, n: int) -> bytes:
            return b'{"tag_name": "v1.0.0"}'

    def fake_urlopen(request: Any, timeout: float) -> Response:
        sent["url"], sent["headers"], sent["data"] = (
            request.full_url,
            dict(request.header_items()),
            request.data,
        )
        return Response()

    monkeypatch.setattr(updates.urllib.request, "urlopen", fake_urlopen)
    assert updates.fetch_json(URL)["tag_name"] == "v1.0.0"
    assert sent["url"] == URL
    assert sent["data"] is None
    assert sent["headers"] == {
        "User-agent": "athena-update-check",
        "Accept": "application/vnd.github+json",
    }


def app_with(tmp_path, answer: dict[str, Any] | Exception, current: str = "0.1.0"):
    def fetch(url: str) -> dict[str, Any]:
        if isinstance(answer, Exception):
            raise answer
        return answer

    app = make_app(tmp_path, update_check_url=URL)
    app.state.updates = UpdateChecker(fetch=fetch, current=current)
    return app


def test_api_reports_an_available_update(tmp_path) -> None:
    with TestClient(app_with(tmp_path, release("v0.2.0"))) as client:
        signed_in(client)
        body = client.get("/api/system/update").json()
        for _ in range(100):  # the loop checks in the background right after start
            if body["latest"]:
                break
            time.sleep(0.05)
            body = client.get("/api/system/update").json()
        assert body["enabled"] is True
        assert (body["current"], body["latest"], body["available"]) == ("0.1.0", "0.2.0", True)


def test_with_the_switch_off_nothing_is_sent(tmp_path) -> None:
    calls: list[str] = []

    def fetch(url: str) -> dict[str, Any]:
        calls.append(url)
        return release("v0.2.0")

    app = make_app(tmp_path, update_check_url=URL)
    app.state.updates = UpdateChecker(fetch=fetch, current="0.1.0")
    app.state.settings_file.save("system", SystemSettings(update_check=False))
    with TestClient(app) as client:
        signed_in(client)
        time.sleep(0.3)
        body = client.get("/api/system/update").json()
        assert body["enabled"] is False
        assert (body["latest"], body["available"]) == (None, False)
    assert calls == []


def test_turning_the_switch_off_hides_the_notice_and_is_audited(tmp_path) -> None:
    with TestClient(app_with(tmp_path, release("v0.2.0"))) as client:
        signed_in(client)
        settings = client.get("/api/settings/system").json()
        assert settings["update_check"] is True  # on by default
        res = client.put("/api/settings/system", json={**settings, "update_check": False})
        assert res.status_code == 200 and res.json()["update_check"] is False
        assert client.get("/api/system/update").json()["available"] is False
        actions = [e["action"] for e in client.get("/api/audit").json()]
        assert "settings.update_check" in actions


def test_update_info_needs_a_session(tmp_path) -> None:
    with TestClient(make_app(tmp_path)) as client:
        assert client.get("/api/system/update").status_code == 401


def test_no_url_means_no_check(tmp_path) -> None:
    with TestClient(make_app(tmp_path)) as client:
        signed_in(client)
        body = client.get("/api/system/update").json()
        assert body["enabled"] is False
        assert body["available"] is False
