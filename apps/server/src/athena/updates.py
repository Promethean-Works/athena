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


def fetch_json(url: str) -> dict[str, Any]:
    """GET `url` and parse the JSON object. Raises on any failure."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        data = json.loads(response.read(1024 * 1024))
    if not isinstance(data, dict):
        raise ValueError("not a release")
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
