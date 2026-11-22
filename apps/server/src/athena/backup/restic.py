"""restic (BSD-2-Clause, github.com/restic/restic), downloaded on first use, and a runner.

Athena pins one restic release and the SHA-256 of each archive it may download (from the
release's `SHA256SUMS`). To move to a newer restic, update `VERSION` and `CHECKSUMS`
together. A restic on `PATH` is never used, so every host runs the same tested version.

The repository password reaches restic only through the `RESTIC_PASSWORD` environment
variable of the child process: never on the command line, never in a log line.
"""

import asyncio
import contextlib
import logging
import os
import platform
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import httpx2

from athena.downloads import (
    DownloadError,
    Log,
    extract_single,
    fetch_verified,
    quiet,
    sha256_file,
    write_executable,
)

log = logging.getLogger(__name__)

VERSION = "0.20.0"

# Archive name -> SHA-256, copied from the release's SHA256SUMS.
CHECKSUMS = {
    "restic_0.20.0_darwin_amd64.bz2": (
        "21f0070ef2bc6f3da2e33c070628e3e026e5237ba5fcddb1f9e0e8cabdd809d5"
    ),
    "restic_0.20.0_darwin_arm64.bz2": (
        "0962c515acd9fb6937a658e9d8505200f72a6a0c6a2d334c0290b8002377dfb7"
    ),
    "restic_0.20.0_linux_386.bz2": (
        "a23e8de316f2aa8ab2fcface8128d56c2afd24682dafb213484f87d441a28634"
    ),
    "restic_0.20.0_linux_amd64.bz2": (
        "0ccd9fa7885074a24603b051e01bf9bd8b5e45d6a1791e9d9887e9e9372107f7"
    ),
    "restic_0.20.0_linux_arm.bz2": (
        "34fcedbb2493ade701e166af0cef5ea3d3f5aad1b0c268c7105e1ec511b7d7e1"
    ),
    "restic_0.20.0_linux_arm64.bz2": (
        "1188daded239bccb5952a01d2ad33e77a0d3dc34f9d9fc1e7fdda618d44938ef"
    ),
    "restic_0.20.0_windows_386.zip": (
        "ab849c4e351af2a2d9b96722668f8779ba6b38e7ef29cfa5c67d14d9b2cdcc2d"
    ),
    "restic_0.20.0_windows_amd64.zip": (
        "bba9061c3dce081701ab353ec8cb73a78be73b71a538aad560f2d1067602b7fe"
    ),
}

_ARCH = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "armv7l": "arm",
    "armv6l": "arm",
    "i386": "386",
    "i686": "386",
    "x86": "386",
}

# restic's exit codes (https://restic.readthedocs.io/en/stable/075_scripting.html).
EXIT_NO_REPOSITORY = 10
EXIT_WRONG_PASSWORD = 12

RUN_TIMEOUT = 6 * 3600.0
"""Upper bound for one restic command; a first backup of a big folder can take hours."""


class ResticError(Exception):
    """A restic command failed. The message is safe to show to the admin."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


def asset_for(system: str, machine: str) -> str:
    """The release archive for this OS and CPU, or `DownloadError`."""
    system = system.lower()
    arch = _ARCH.get(machine.lower())
    ext = "zip" if system == "windows" else "bz2"
    name = f"restic_{VERSION}_{system}_{arch}.{ext}"
    if arch is None or name not in CHECKSUMS:
        raise DownloadError(f"restic has no release for {system} on {machine}")
    return name


def binary_path(data_dir: Path) -> Path:
    return data_dir / "bin" / ("restic.exe" if sys.platform == "win32" else "restic")


def _stamp(binary: Path) -> Path:
    """The binary's own SHA-256, written at install, checked before each run."""
    return binary.with_name(binary.name + ".sha256")


def _installed_ok(binary: Path) -> bool:
    stamp = _stamp(binary)
    if not binary.is_file() or not stamp.is_file():
        return False
    expected = stamp.read_text(encoding="utf-8").split()
    return len(expected) == 2 and expected[1] == VERSION and expected[0] == sha256_file(binary)


def _install(binary: Path, data: bytes) -> None:
    write_executable(binary, data)
    _stamp(binary).write_text(f"{sha256_file(binary)} {VERSION}\n", encoding="utf-8")


async def ensure_restic(
    data_dir: Path,
    log_line: Log = quiet,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> Path:
    """The path of a verified restic binary, downloading it if missing, changed or outdated."""
    binary = binary_path(data_dir)
    if await asyncio.to_thread(_installed_ok, binary):
        return binary
    asset = asset_for(platform.system(), platform.machine())
    url = f"https://github.com/restic/restic/releases/download/v{VERSION}/{asset}"
    archive = await fetch_verified(url, CHECKSUMS[asset], log_line=log_line, transport=transport)
    data = extract_single(archive, asset)
    await asyncio.to_thread(_install, binary, data)
    await log_line(f"Installed restic {VERSION} at {binary}")
    return binary


@dataclass(frozen=True)
class Repository:
    """Where a restic repository is and how to open it. `password` is never logged."""

    location: str
    """A local folder, or `rclone:<remote>:<path>`."""
    password: str
    env: Mapping[str, str] | None = None
    """Extra environment (the rclone config path and password, later)."""

    def __repr__(self) -> str:  # a stray `log.info("%r", repo)` must not leak the password
        return f"Repository({self.location!r})"


@dataclass(frozen=True)
class Result:
    code: int
    stdout: str
    stderr: str


def _environment(repo: Repository, cache_dir: Path | None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("RESTIC_", "AWS_", "RCLONE_"))}
    env["LC_ALL"] = "C.UTF-8"
    env["RESTIC_REPOSITORY"] = repo.location
    env["RESTIC_PASSWORD"] = repo.password
    env["RESTIC_PROGRESS_FPS"] = "1"
    if cache_dir is not None:
        env["RESTIC_CACHE_DIR"] = str(cache_dir)
    env.update(repo.env or {})
    return env


class Restic:
    """Runs restic commands against a repository."""

    def __init__(self, binary: Path, cache_dir: Path | None = None) -> None:
        self.binary = binary
        self.cache_dir = cache_dir

    async def run(
        self, repo: Repository, *args: str, timeout: float = RUN_TIMEOUT, stdin: bytes | None = None
    ) -> Result:
        """Run `restic <args>`. Never raises for a non-zero exit; see `run_ok`."""
        # stdin is DEVNULL unless data is piped in: under the Windows service (pythonw.exe)
        # there are no console handles to inherit (docs/agents/gotchas/windows.md).
        proc = await asyncio.create_subprocess_exec(
            str(self.binary),
            *args,
            env=_environment(repo, self.cache_dir),
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(stdin), timeout)
        except BaseException:
            # Timed out or cancelled: never leave restic running (it holds a repo lock).
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
            raise
        return Result(
            proc.returncode if proc.returncode is not None else -1,
            out.decode("utf-8", errors="replace"),
            err.decode("utf-8", errors="replace"),
        )

    async def run_ok(self, repo: Repository, *args: str, stdin: bytes | None = None) -> Result:
        """Like `run`, but a failure raises `ResticError` with restic's own message."""
        result = await self.run(repo, *args, stdin=stdin)
        if result.code != 0:
            raise ResticError(failure_message(result), result.code)
        return result


def failure_message(result: Result) -> str:
    """The last meaningful line restic printed, for the admin."""
    lines = [ln.strip() for ln in (result.stderr or result.stdout).splitlines() if ln.strip()]
    text = lines[-1] if lines else f"restic exited with code {result.code}"
    return text[:500]
