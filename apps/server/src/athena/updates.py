"""The update notice: is a newer Athena release out?

Once a day (and after each start) the server asks GitHub for the latest release and
remembers the answer; `GET /api/system/update` serves it to the UI without any network
call. The request is a plain unauthenticated GET with a generic User-Agent: it carries
no version, host name, settings or any other identifying information. Admins can turn
it off (Settings → System, `update_check` in athena.json), and an empty
`ATHENA_UPDATE_CHECK_URL` disables it too (tests, air-gapped hosts).

Offline hosts, rate limits and odd answers are not errors: the check is retried an hour
later and the notice simply doesn't show. Prereleases and drafts never count, and
`/releases/latest` doesn't return them anyway.
"""

import asyncio
import contextlib
import json
import logging
import re
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from pydantic import BaseModel

from athena import __version__
from athena import system_settings as system_settings_module
from athena.platform.probe import current_os

if TYPE_CHECKING:
    from fastapi import FastAPI

log = logging.getLogger(__name__)

CHECK_EVERY = 24 * 3600.0
RETRY_AFTER_FAILURE = 3600.0
TIMEOUT = 10.0
USER_AGENT = "athena-update-check"
"""GitHub's API refuses requests without a User-Agent. This one names no version or host."""

INSTALL_SH = (
    "curl -fsSL https://github.com/Promethean-Works/athena/releases/latest/download/install.sh"
    " | bash"
)
INSTALL_PS1 = (
    "irm https://github.com/Promethean-Works/athena/releases/latest/download/install.ps1 | iex"
)

Fetch = Callable[[str], dict[str, Any]]
FetchList = Callable[[str], list[Any]]

REPO_FILES_HOSTS = ("github.com", "objects.githubusercontent.com")
RELEASE_VERSION = re.compile(r"(\d+\.\d+\.\d+)(?:[-.]?(a|b|rc)\.?(\d+))?")
SUMS_NAME = "SHA256SUMS"


class UpdateInfo(BaseModel):
    enabled: bool
    """Whether the daily check is on (Settings → System)."""
    current: str
    latest: str | None
    """The newest release found, or None when the check is off, hasn't run or failed."""
    available: bool
    """`latest` is newer than `current`."""
    checked_at: datetime | None
    release_url: str | None
    command: str
    """What to run on this host to upgrade: re-running the installer."""


def parse_version(text: str) -> tuple[int, ...] | None:
    """`v1.2.3` or `1.2.3` as numbers; None for anything else (prereleases like `1.0.0-rc1`)."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+){0,3})", text.strip())
    return tuple(int(p) for p in match.group(1).split(".")) if match else None


def is_newer(latest: str, current: str) -> bool:
    new, old = parse_version(latest), parse_version(current)
    if new is None or old is None or not any(old):  # 0.0.0 is a source checkout, not a release
        return False
    width = max(len(new), len(old))
    pad = lambda v: v + (0,) * (width - len(v))  # noqa: E731
    return pad(new) > pad(old)


def upgrade_command() -> str:
    return INSTALL_PS1 if current_os() == "windows" else INSTALL_SH


def _get_json(url: str, limit: int = 1024 * 1024) -> Any:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read(limit))


def fetch_json(url: str) -> dict[str, Any]:
    """GET `url` and parse the JSON object. Raises on any failure."""
    data = _get_json(url)
    if not isinstance(data, dict):
        raise ValueError("not a release")
    return data


def fetch_json_list(url: str) -> list[Any]:
    """GET `url` and parse the JSON array (the releases list). Raises on any failure."""
    data = _get_json(url, 4 * 1024 * 1024)
    if not isinstance(data, list):
        raise ValueError("not a list of releases")
    return data


class UpdateChecker:
    def __init__(self, fetch: Fetch = fetch_json, current: str = __version__) -> None:
        self._fetch = fetch
        self.current = current
        self.latest: str | None = None
        self.release_url: str | None = None
        self.checked_at: datetime | None = None

    async def check(self, url: str) -> bool:
        """Ask for the latest release. False when it couldn't be read (offline, rate limit)."""
        try:
            release = await asyncio.to_thread(self._fetch, url)
        except (OSError, ValueError) as exc:  # URLError and timeouts are OSErrors
            log.info("update check failed: %s", exc)
            return False
        tag = release.get("tag_name")
        if release.get("draft") or release.get("prerelease") or not isinstance(tag, str):
            return True  # an answer, but not a release to announce
        if parse_version(tag) is None:
            return True
        self.latest = tag.removeprefix("v")
        html_url = release.get("html_url")
        self.release_url = html_url if isinstance(html_url, str) else None
        self.checked_at = datetime.now(UTC)
        return True

    def forget(self) -> None:
        self.latest = self.release_url = self.checked_at = None

    def info(self, enabled: bool) -> UpdateInfo:
        latest = self.latest if enabled else None
        return UpdateInfo(
            enabled=enabled,
            current=self.current,
            latest=latest,
            available=latest is not None and is_newer(latest, self.current),
            checked_at=self.checked_at if enabled else None,
            release_url=self.release_url if enabled else None,
            command=upgrade_command(),
        )


def enabled(app: "FastAPI") -> bool:
    return system_settings_module.load(app.state.settings_file).update_check


async def check_loop(app: "FastAPI") -> None:
    """Check on start and then daily, while the setting is on. Turning it on wakes the loop."""
    checker: UpdateChecker = app.state.updates
    wake: asyncio.Event = app.state.update_event
    while True:
        wait = CHECK_EVERY
        url = app.state.settings.update_check_url
        if url and enabled(app):
            ok = await checker.check(url)
            wait = CHECK_EVERY if ok else RETRY_AFTER_FAILURE
        else:
            checker.forget()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(wake.wait(), wait)
        wake.clear()


# ---------------------------------------------------------------- self-update: the assets


class ReleaseError(Exception):
    """A readable reason a release can't be used (shown as is)."""


class Release(BaseModel):
    tag: str
    version: str
    """The wheel's PEP 440 version: tag `v0.2.0-rc.1` is `0.2.0rc1`."""
    wheel_name: str
    wheel_url: str
    sums_url: str
    html_url: str | None


def wheel_version(text: str) -> str | None:
    """`0.2.0`, `v0.2.0-rc.1` or `0.2.0rc1` as the wheel's PEP 440 version; None if invalid."""
    match = RELEASE_VERSION.fullmatch(text.strip().removeprefix("v"))
    if match is None:
        return None
    base, kind, number = match.groups()
    return f"{base}{kind}{number}" if kind else base


def version_key(version: str) -> tuple[tuple[int, ...], int, str, int] | None:
    """Sort key for `wheel_version` strings: a pre-release sorts before its final."""
    match = RELEASE_VERSION.fullmatch(version)
    if match is None:
        return None
    base, kind, number = match.groups()
    numbers = tuple(int(p) for p in base.split("."))
    return (numbers, 0, kind, int(number)) if kind else (numbers, 1, "", 0)


def release_wheel_name(version: str) -> str:
    return f"athena_server-{version}-py3-none-any.whl"


def _releases_root(check_url: str) -> str:
    url = check_url.rstrip("/")
    return url.removesuffix("/latest")


def host_allowed(url: str, check_url: str) -> bool:
    """HTTPS to GitHub (and its release CDN), or the host the update source setting names.

    The setting is the server's own (forks, tests, mirrors), never a request field.
    """
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme == "https" and (
        host in REPO_FILES_HOSTS
        or host.endswith(".githubusercontent.com")
        or host.endswith(".github.com")
    ):
        return True
    source = urlsplit(check_url)
    return (parts.scheme, parts.netloc) == (source.scheme, source.netloc) and parts.scheme in (
        "http",
        "https",
    )


def _release_from(data: dict[str, Any], check_url: str) -> Release:
    tag = data.get("tag_name")
    version = wheel_version(tag) if isinstance(tag, str) else None
    if not isinstance(tag, str) or version is None:
        raise ReleaseError("The release has no usable version")
    wheel = release_wheel_name(version)
    urls: dict[str, str] = {}
    for asset in data.get("assets") or []:
        if isinstance(asset, dict) and asset.get("name") in (wheel, SUMS_NAME):
            link = asset.get("browser_download_url")
            if isinstance(link, str):
                urls[asset["name"]] = link
    if wheel not in urls or SUMS_NAME not in urls:
        raise ReleaseError(f"Release {tag} has no {wheel} and {SUMS_NAME}")
    for link in urls.values():
        if not host_allowed(link, check_url):
            raise ReleaseError(f"Release {tag} points at {link}, which isn't an allowed host")
    html_url = data.get("html_url")
    return Release(
        tag=tag,
        version=version,
        wheel_name=wheel,
        wheel_url=urls[wheel],
        sums_url=urls[SUMS_NAME],
        html_url=html_url if isinstance(html_url, str) else None,
    )


def resolve(
    check_url: str,
    version: str | None = None,
    *,
    pre: bool = False,
    fetch: Fetch = fetch_json,
    fetch_list: FetchList = fetch_json_list,
) -> Release:
    """Find the wheel and checksum URLs of a release, when the admin starts an update.

    Uses the notice's source (`update_check_url`), so forks and tests redirect both. With no
    `version` it asks for the latest stable release (or, with `pre`, the newest of any kind).
    The version is validated before it becomes part of a URL. Raises `ReleaseError`.
    """
    if not check_url:
        raise ReleaseError("The update source is turned off (update_check_url is empty)")
    root = _releases_root(check_url)
    try:
        if version is not None:
            wanted = wheel_version(version)
            if wanted is None:
                raise ReleaseError(
                    f"{version!r} isn't a release version (like 0.2.0 or 0.2.0-rc.1)"
                )
            tag = "v" + version.strip().removeprefix("v")
            data = fetch(f"{root}/tags/{tag}")
        elif pre:
            listing = fetch_list(f"{root}?per_page=10")
            found = next(
                (r for r in listing if isinstance(r, dict) and not r.get("draft")),
                None,
            )
            if found is None:
                raise ReleaseError("No release found")
            data = found
        else:
            data = fetch(f"{root}/latest")
    except (OSError, ValueError) as exc:
        raise ReleaseError(f"Couldn't read the release: {exc}") from exc
    if data.get("draft"):
        raise ReleaseError("That release is a draft")
    if version is None and not pre and data.get("prerelease"):
        raise ReleaseError("The latest release is a pre-release")
    return _release_from(data, check_url)
