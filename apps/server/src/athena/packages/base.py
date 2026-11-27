"""Shared pieces for package managers (docs/design/platform.md, "Package managers per OS").

Every manager reads through `Runner` (so tests can replay recorded output) and parses
with pure functions that tests run against fixtures in tests/fixtures/packages/. Changes
(install, uninstall, upgrade, refresh) are argv lists that a job runs, streaming output.
"""

import asyncio
import logging
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import ClassVar
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, computed_field

log = logging.getLogger(__name__)

READ_TIMEOUT = 120.0
SEARCH_LIMIT = 100

# Package names reach the CLI as one argv element (no shell), so the only risk is a name
# read as an option. Names start with a letter or digit; the rest covers apt (libc6:arm64,
# g++), brew taps (user/tap/formula), flatpak and winget ids (org.gnome.Calculator,
# Git.Git) and versions some managers put in names (python3.12).
PACKAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+:@/~-]{0,199}$")
SEARCH_QUERY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+:@/~-]{0,99}$")


class PackageRef(BaseModel):
    """A search result."""

    name: str
    """What install/uninstall take (a flatpak or winget id, a brew token)."""
    title: str | None = None
    """A display name when it differs from `name` (flatpak, winget, brew casks)."""
    version: str | None = None
    description: str | None = None
    source: str | None = None
    """Where it comes from, when the manager has several (flatpak remote, brew cask)."""
    installed: bool = False


class InstalledPackage(BaseModel):
    name: str
    title: str | None = None
    version: str | None = None
    description: str | None = None
    source: str | None = None


class UpgradablePackage(BaseModel):
    name: str
    version: str | None = None
    """The installed version."""
    latest: str | None = None


class PackageField(BaseModel):
    label: str
    value: str


class PackageDetails(BaseModel):
    """What a package manager knows about one package (the Details view)."""

    name: str
    title: str | None = None
    version: str | None = None
    summary: str | None = None
    """One line."""
    description: str | None = None
    """The long text, when there is one."""
    homepage: str | None = None
    license: str | None = None
    source: str | None = None
    installed: bool = False
    installed_version: str | None = None
    size: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    maintainer: str | None = None
    extra: list[PackageField] = Field(default_factory=list)
    """Anything else the manager reports, as label and value."""
    icon_url: str | None = Field(default=None, exclude=True)
    """Where the manager's store keeps the icon. Never sent to the browser: the server
    fetches it (`GET /api/packages/{manager}/icon`)."""

    @computed_field
    @property
    def has_icon(self) -> bool:
        return bool(self.icon_url)


@dataclass(frozen=True)
class CmdResult:
    code: int
    stdout: str
    stderr: str


Runner = Callable[[list[str], Mapping[str, str] | None], Awaitable[CmdResult]]


class PackageError(RuntimeError):
    """A read command failed; the message is meant for the user."""


def command_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment for package commands: English, uncolored, non-interactive output."""
    env = dict(os.environ)
    if sys.platform != "win32":
        # Parsers expect English headers and messages. C.UTF-8 keeps non-ASCII intact.
        env["LC_ALL"] = "C.UTF-8"
        env["LANG"] = "C.UTF-8"
    env["NO_COLOR"] = "1"
    env.update(extra or {})
    return env


def resolve(argv: list[str]) -> list[str]:
    """Use the executable's full path. On Windows this finds .cmd shims (Scoop), which
    launching by bare name doesn't."""
    path = shutil.which(argv[0])
    return [path, *argv[1:]] if path else argv


async def run_command(argv: list[str], env: Mapping[str, str] | None = None) -> CmdResult:
    """The real runner: no shell, no stdin, a timeout, never raises for a bad exit code."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *resolve(argv),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            env=command_env(env),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        return CmdResult(-1, "", str(exc))
    try:
        out, err = await asyncio.wait_for(proc.communicate(), READ_TIMEOUT)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return CmdResult(-1, "", f"{argv[0]} took longer than {int(READ_TIMEOUT)} s")
    return CmdResult(
        proc.returncode or 0,
        out.decode(errors="replace"),
        err.decode(errors="replace"),
    )


def error_text(result: CmdResult, what: str) -> str:
    detail = (result.stderr.strip() or result.stdout.strip()).splitlines()
    tail = detail[-1] if detail else f"exit code {result.code}"
    return f"{what} failed: {tail}"


class PackageManager:
    """One package manager. Subclasses set the class attributes and implement the reads."""

    id: ClassVar[str]
    label: ClassVar[str]
    env: ClassVar[dict[str, str]] = {}
    can_upgrade_one: ClassVar[bool] = True
    """False where only a full upgrade is safe (pacman)."""
    can_refresh: ClassVar[bool] = False
    """True when package lists can be refreshed separately (apt update)."""
    note: ClassVar[str | None] = None
    """Shown in the UI, e.g. that installs on Arch also upgrade the system."""
    logo_url: ClassVar[str | None] = None
    """The manager's own logo, on its official site (fetched by the server, never bundled)."""
    icon_hosts: ClassVar[tuple[str, ...]] = ()
    """Extra hosts its store may serve icons or redirect the logo from. The logo's own site
    is always allowed."""

    def __init__(self, run: Runner = run_command) -> None:
        self._run = run

    async def run(self, argv: list[str], what: str, ok_codes: tuple[int, ...] = (0,)) -> str:
        result = await self._run(argv, self.env)
        if result.code not in ok_codes:
            raise PackageError(error_text(result, what))
        return result.stdout

    # -- reads (async: some managers need more than one command)

    async def search(self, query: str) -> list[PackageRef]:
        raise NotImplementedError

    async def find(self, query: str) -> list[PackageRef]:
        """`search` over the query and its aliases (vscode -> visual studio code), merged.

        The query itself decides success: an alias that errors or finds nothing is skipped.
        """
        from athena.packages.aliases import expand_query, merge_results

        queries = expand_query(query)
        batches = [await self.search(queries[0])]
        for extra in queries[1:]:
            try:
                batches.append(await self.search(extra))
            except PackageError:
                continue
        return merge_results(batches)[:SEARCH_LIMIT]

    @classmethod
    def image_hosts(cls) -> tuple[str, ...]:
        """Where this manager's logo and package icons may come from (https only)."""
        hosts = list(cls.icon_hosts)
        if cls.logo_url:
            host = urlsplit(cls.logo_url).hostname or ""
            hosts.append(".".join(host.split(".")[-2:]))
        return tuple(hosts)

    async def details(self, name: str, source: str | None = None) -> PackageDetails:
        raise NotImplementedError

    async def info(self, name: str, source: str | None = None) -> PackageDetails:
        """Details for one package, with whether it is installed filled in."""
        details = await self.details(name, source)
        if not details.installed:
            try:
                have = {p.name: p.version for p in await self.installed()}
            except PackageError:
                have = {}
            if name in have:
                details.installed, details.installed_version = True, have[name]
        return details

    async def installed(self) -> list[InstalledPackage]:
        raise NotImplementedError

    async def upgradable(self) -> list[UpgradablePackage]:
        raise NotImplementedError

    # -- changes (run as jobs)

    def install_argv(self, name: str, source: str | None = None) -> list[str]:
        raise NotImplementedError

    def uninstall_argv(self, name: str) -> list[str]:
        raise NotImplementedError

    def upgrade_argv(self, name: str | None) -> list[str]:
        """Upgrade one package, or everything when `name` is None."""
        raise NotImplementedError

    def refresh_argv(self) -> list[str] | None:
        return None


# ------------------------------------------------------------------ parsing helpers


def nonblank(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def column_table(text: str, min_columns: int = 2) -> list[list[str]]:
    """Rows of a column-aligned table (snap, winget, scoop), as lists of cell strings.

    Finds the header (the first line followed by a dashes line, or the first line with
    enough words when there is no dashes line), takes column starts from where the
    dash groups or header words begin, and slices each row at those positions.
    Columns are positional, so localized headers (winget) still work.
    """
    # Progress spinners end with \r: keep only what was printed last on each line.
    lines = [line.rsplit("\r", 1)[-1].rstrip() for line in text.splitlines()]
    header_at = None
    starts: list[int] = []
    for i, line in enumerate(lines[:-1]):
        nxt = lines[i + 1]
        if line.strip() and nxt.strip() and set(nxt.strip()) <= {"-", " "}:
            header_at = i
            groups = list(re.finditer(r"-+", nxt))
            if len(groups) >= min_columns:  # scoop: one dash group per column
                starts = [g.start() for g in groups]
            else:  # winget: one long dashes line; use the header words
                starts = [m.start() for m in re.finditer(r"(?<!\S)\S", line)]
            break
    if header_at is None:
        for i, line in enumerate(lines):
            words = list(re.finditer(r"\S+", line))
            if len(words) >= min_columns:
                header_at, starts = i, [w.start() for w in words]
                break
    if header_at is None:
        return []
    first = header_at + 1
    if first < len(lines) and lines[first].strip() and set(lines[first].strip()) <= {"-", " "}:
        first += 1
    rows = []
    for line in lines[first:]:
        if not line.strip():
            continue
        cells = []
        for j, start in enumerate(starts):
            end = starts[j + 1] if j + 1 < len(starts) else None
            cells.append(line[start:end].strip() if start < len(line) else "")
        rows.append(cells)
    return rows


def parse_fields(text: str, known: set[str], flush_left: bool = False) -> dict[str, str]:
    """`Key : value` lines (dnf, zypper, pacman, apt, winget, scoop, choco, flatpak).

    Only keys in `known` (lowercase) start a field, so a description line that happens to
    contain a colon stays part of the description. Other lines continue the field before
    them (a leading `:` as dnf prints is dropped). Fields repeated keep the first value.
    With `flush_left`, any unindented `Key : value` line also starts a field (dnf, zypper,
    pacman, apt print every key at the left edge and indent continuations).
    """
    fields: dict[str, list[str]] = {}
    current: list[str] | None = None
    for raw in text.replace("\xa0", " ").splitlines():
        match = re.match(r"^\s*([^:]{1,30}?)\s*:\s?(.*)$", raw)
        key = match.group(1).strip().lower() if match else ""
        if match and (key in known or (flush_left and not raw[:1].isspace())):
            if key in fields:
                current = None  # a repeated key (apt lists several stanzas): keep the first
                continue
            current = fields.setdefault(key, [])
            current.append(match.group(2).strip())
        elif current is not None:
            current.append(raw.strip().lstrip(":").strip())
    return {k: "\n".join(v).strip() for k, v in fields.items()}


def split_description(text: str | None) -> tuple[str | None, str | None]:
    """First line as the summary, the rest as the long text (apt's `.` is a blank line)."""
    if not text:
        return None, None
    first, _, rest = text.partition("\n")
    long = "\n".join("" if line.strip() == "." else line.strip() for line in rest.splitlines())
    return first.strip() or None, re.sub(r"\n{3,}", "\n\n", long).strip() or None


def clean_dependencies(items: list[str]) -> list[str]:
    """Names only: `libc6 (>= 2.38)` and `glibc>=2.38` become `libc6` and `glibc`."""
    out = []
    for item in items:
        item = item.strip()
        if item.startswith(("so:", "cmd:", "pc:")):
            continue  # apk lists shared libraries and commands next to packages
        name = re.split(r"[\s(<>=:]", item, maxsplit=1)[0]
        if name and name != "None":
            out.append(name)
    return list(dict.fromkeys(out))


def human_kib(kib: float) -> str:
    size, unit = float(kib), "KiB"
    for unit in ("KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            break
        size /= 1024
    return f"{size:.1f} {unit}".replace(".0 ", " ")
