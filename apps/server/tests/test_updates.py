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


# ---------------------------------------------------------------- self-update: the assets

SOURCE = "https://api.github.com/repos/Promethean-Works/athena/releases/latest"


def assets(
    version: str, host: str = "https://github.com/Promethean-Works/athena/releases/download"
):
    tag = f"v{version}"
    return [
        {
            "name": f"athena_server-{version}-py3-none-any.whl",
            "browser_download_url": f"{host}/{tag}/athena_server-{version}-py3-none-any.whl",
        },
        {"name": "SHA256SUMS", "browser_download_url": f"{host}/{tag}/SHA256SUMS"},
    ]


def full_release(tag: str, version: str, **extra: Any) -> dict[str, Any]:
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/x/y/releases/tag/{tag}",
        "assets": assets(version),
        **extra,
    }


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0.2.0", "0.2.0"),
        ("v0.2.0", "0.2.0"),
        ("0.2.0-rc.1", "0.2.0rc1"),
        ("v0.2.0-rc1", "0.2.0rc1"),
        ("0.2.0rc1", "0.2.0rc1"),
        ("1.0.0-a.3", "1.0.0a3"),
        ("0.2.0-beta1", None),
        ("0.2", None),
        ("../../etc/passwd", None),
        ("0.2.0/../x", None),
        ("0.2.0 --index-url x", None),
        ("", None),
    ],
)
def test_wheel_versions(text: str, expected: str | None) -> None:
    assert updates.wheel_version(text) == expected


def test_a_prerelease_sorts_before_its_final() -> None:
    key = updates.version_key
    assert key("0.2.0rc1") < key("0.2.0") < key("0.2.1")
    assert key("0.2.0a1") < key("0.2.0b1") < key("0.2.0rc1")
    assert key("0.10.0") > key("0.9.0")


def test_resolve_latest_finds_the_wheel_and_sums() -> None:
    seen: list[str] = []

    def fetch(url: str) -> dict[str, Any]:
        seen.append(url)
        return full_release("v0.2.0", "0.2.0")

    release = updates.resolve(SOURCE, fetch=fetch)
    assert seen == [SOURCE]
    assert release.version == "0.2.0"
    assert release.wheel_name == "athena_server-0.2.0-py3-none-any.whl"
    assert release.wheel_url.endswith("/v0.2.0/athena_server-0.2.0-py3-none-any.whl")
    assert release.sums_url.endswith("/v0.2.0/SHA256SUMS")


def test_resolve_a_version_asks_for_its_tag_and_maps_prereleases() -> None:
    seen: list[str] = []

    def fetch(url: str) -> dict[str, Any]:
        seen.append(url)
        return full_release("v0.2.0-rc.1", "0.2.0rc1", prerelease=True)

    release = updates.resolve(SOURCE, "0.2.0-rc.1", fetch=fetch)
    assert seen == [SOURCE.removesuffix("/latest") + "/tags/v0.2.0-rc.1"]
    assert release.version == "0.2.0rc1"
    assert release.wheel_name == "athena_server-0.2.0rc1-py3-none-any.whl"


def test_resolve_never_lets_a_bad_version_reach_a_url() -> None:
    def fetch(url: str) -> dict[str, Any]:
        raise AssertionError("no request for an invalid version")

    with pytest.raises(updates.ReleaseError, match="isn't a release version"):
        updates.resolve(SOURCE, "0.2.0/../../x", fetch=fetch)


def test_resolve_pre_takes_the_newest_non_draft() -> None:
    listing = [
        {"tag_name": "v0.3.0", "draft": True, "assets": []},
        full_release("v0.3.0-rc.1", "0.3.0rc1", prerelease=True),
        full_release("v0.2.0", "0.2.0"),
    ]
    seen: list[str] = []

    def fetch_list(url: str) -> list[Any]:
        seen.append(url)
        return listing

    release = updates.resolve(SOURCE, pre=True, fetch_list=fetch_list)
    assert release.version == "0.3.0rc1"
    assert seen[0].startswith(SOURCE.removesuffix("/latest") + "?")


def test_resolve_refuses_drafts_and_prereleases_without_asking_for_one() -> None:
    with pytest.raises(updates.ReleaseError, match="pre-release"):
        updates.resolve(
            SOURCE, fetch=lambda u: full_release("v0.3.0-rc.1", "0.3.0rc1", prerelease=True)
        )
    with pytest.raises(updates.ReleaseError, match="draft"):
        updates.resolve(SOURCE, fetch=lambda u: full_release("v0.3.0", "0.3.0", draft=True))


def test_resolve_needs_both_assets() -> None:
    release = full_release("v0.2.0", "0.2.0")
    release["assets"] = release["assets"][:1]
    with pytest.raises(updates.ReleaseError, match="SHA256SUMS"):
        updates.resolve(SOURCE, fetch=lambda u: release)


def test_resolve_refuses_assets_on_other_hosts() -> None:
    release = full_release("v0.2.0", "0.2.0")
    release["assets"] = assets("0.2.0", "https://evil.example/download")
    with pytest.raises(updates.ReleaseError, match="allowed host"):
        updates.resolve(SOURCE, fetch=lambda u: release)


def test_resolve_wraps_network_errors() -> None:
    def fail(url: str) -> dict[str, Any]:
        raise OSError("HTTP Error 404")

    with pytest.raises(updates.ReleaseError, match="Couldn't read the release"):
        updates.resolve(SOURCE, "0.2.0", fetch=fail)
    with pytest.raises(updates.ReleaseError, match="turned off"):
        updates.resolve("", fetch=fail)


def test_allowed_hosts() -> None:
    ok = updates.host_allowed
    assert ok("https://github.com/a/b/releases/download/v1/x.whl", SOURCE)
    assert ok("https://release-assets.githubusercontent.com/x", SOURCE)
    assert not ok("http://github.com/a/b/x.whl", SOURCE)  # HTTPS only
    assert not ok("https://github.com.evil.example/x", SOURCE)
    assert not ok("https://evil.example/x", SOURCE)
    local = "http://127.0.0.1:9000/releases/latest"  # a fork or a test names its own source
    assert ok("http://127.0.0.1:9000/files/x.whl", local)
    assert not ok("http://127.0.0.1:9001/files/x.whl", local)


def test_the_update_source_can_be_set_in_athena_json(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from athena.config import Settings

    (tmp_path / "athena.json").write_text(
        json.dumps({"server": {"update_check_url": "http://127.0.0.1:9/releases/latest"}}),
        encoding="utf-8",
    )
    monkeypatch.delenv("ATHENA_UPDATE_CHECK_URL")
    assert Settings(data_dir=tmp_path).update_check_url == "http://127.0.0.1:9/releases/latest"
    monkeypatch.setenv("ATHENA_UPDATE_CHECK_URL", "")  # the environment still wins
    assert Settings(data_dir=tmp_path).update_check_url == ""
