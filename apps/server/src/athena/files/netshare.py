"""Helpers shared by the SMB and NFS share providers (docs/specs/network-shares.md).

The provider modules write a host config file and ask the host's server to reload it.
A failed reload rolls the file back, so a share is never tracked that the host isn't serving.
"""

from __future__ import annotations

import base64
import os
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

from athena.files import paths
from athena.files.paths import FileError


class ShareReloadFailed(FileError):
    """The host's share server refused the new configuration (it was rolled back)."""

    status = 502


class ElevationDenied(FileError):
    """The host refused to give Athena root or administrator rights for this action."""

    status = 403


@dataclass(frozen=True)
class Elevation:
    """How to run host commands with more rights than Athena's own user has.

    `sudo` runs each command through `sudo -S` with `password` on stdin; `uac` starts an
    elevated PowerShell and lets Windows ask on the host's screen. The password is only
    ever held in memory for one request.
    """

    kind: str
    password: str = field(default="", repr=False)


_elevation: ContextVar[Elevation | None] = ContextVar("athena_share_elevation", default=None)

ELEVATED_TIMEOUT = 120
"""Seconds to wait for a UAC prompt on the host's screen."""


@contextmanager
def elevated(elevation: Elevation | None) -> Iterator[None]:
    """Run the host commands and file writes inside this block with `elevation`."""
    token = _elevation.set(elevation)
    try:
        yield
    finally:
        _elevation.reset(token)


def with_elevation[T](elevation: Elevation | None, fn: Callable[[], T]) -> Callable[[], T]:
    """`fn`, wrapped so it runs elevated (the context doesn't follow work into a thread)."""

    def run() -> T:
        with elevated(elevation):
            return fn()

    return run


def write_atomic(path: Path, text: str) -> None:
    """Replace `path` with `text` without ever leaving a half-written file."""
    if (elevation := _elevation.get()) is not None and elevation.kind == "sudo":
        _install_elevated(path, text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        if path.exists():
            tmp.chmod(path.stat().st_mode & 0o7777)
        else:
            tmp.chmod(0o644)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


_SUDO_REFUSED = ("incorrect password", "sorry, try again", "password is required")


def _install_elevated(path: Path, text: str) -> None:
    """Write `text` to a private temp file, then copy it over `path` with `sudo install`."""
    fd, tmp_name = tempfile.mkstemp(prefix="athena-share-")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        run_command(["install", "-m", "644", str(tmp), str(path)], f"write {path}")
    finally:
        tmp.unlink(missing_ok=True)


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _powershell_encoded(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def uac_argv(argv: list[str], env: dict[str, str] | None, error_file: str) -> list[str]:
    """`argv` (a `powershell -Command <script>` call) rewritten to run in an elevated
    PowerShell. Values in `env` become variables set from base64 literals, so nothing
    user-supplied is ever parsed as script. An error is written to `error_file`, since an
    elevated process has its own console."""
    script = argv[-1]
    setup = "".join(
        f"$env:{key} = [Text.Encoding]::UTF8.GetString("
        f"[Convert]::FromBase64String('{_b64(value)}')); "
        for key, value in (env or {}).items()
    )
    inner = (
        f"{setup}try {{ {script} }} catch {{ "
        f"[IO.File]::WriteAllText('{error_file}', $_.Exception.Message); exit 1 }}"
    )
    outer = (
        "$ErrorActionPreference = 'Stop'; "
        "$p = Start-Process -FilePath powershell.exe -Verb RunAs -Wait -PassThru "
        "-WindowStyle Hidden -ArgumentList '-NoProfile','-NonInteractive',"
        f"'-EncodedCommand','{_powershell_encoded(inner)}'; exit $p.ExitCode"
    )
    return [*argv[:-2], "-EncodedCommand", _powershell_encoded(outer)]


def run_command(argv: list[str], action: str, env: dict[str, str] | None = None) -> None:
    """Run a host command; raise `ShareReloadFailed` ("Couldn't <action>: <why>") if it fails.

    Inside `elevated(...)` the command runs with root or administrator rights, and a refusal
    raises `ElevationDenied`."""
    elevation = _elevation.get()
    stdin: str | None = None
    timeout = 20
    error_file: Path | None = None
    if elevation is not None and elevation.kind == "sudo":
        argv = ["sudo", "-S", "-k", "-p", "", *argv]
        stdin = elevation.password + "\n"
    elif elevation is not None and elevation.kind == "uac":
        fd, name = tempfile.mkstemp(prefix="athena-uac-")
        os.close(fd)
        error_file = Path(name)
        argv = uac_argv(argv, env, str(error_file))
        env = None
        timeout = ELEVATED_TIMEOUT
    try:
        result = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=stdin,
            stdin=None if stdin is not None else subprocess.DEVNULL,
            env={**os.environ, **env} if env else None,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        if error_file:
            error_file.unlink(missing_ok=True)
        raise ShareReloadFailed(f"Couldn't {action}: {exc}") from exc
    written = ""
    if error_file:
        written = error_file.read_text(encoding="utf-8", errors="replace").strip()
        error_file.unlink(missing_ok=True)
    if result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        if elevation is not None and elevation.kind == "sudo":
            if any(marker in output.lower() for marker in _SUDO_REFUSED):
                raise ElevationDenied("That password didn't work")
            output = output.replace(elevation.password, "***") if elevation.password else output
        elif elevation is not None and elevation.kind == "uac" and not written:
            raise ElevationDenied("Windows didn't approve the administrator prompt")
        lines = (written or output).splitlines()
        reason = lines[-1] if lines else f"exit code {result.returncode}"
        raise ShareReloadFailed(f"Couldn't {action}: {reason}")


def run_reload(argv: list[str], what: str) -> None:
    """Run the reload command for `what` (see `run_command`)."""
    run_command(argv, f"reload {what}")


def swap_config(path: Path, new_text: str, reload: Callable[[], None]) -> None:
    """Write `new_text` to `path`, call `reload()`, and restore the old file if it fails."""
    old = path.read_text(encoding="utf-8") if path.exists() else None
    write_atomic(path, new_text)
    try:
        reload()
    except BaseException:
        if old is None:
            path.unlink(missing_ok=True)
        else:
            write_atomic(path, old)
        raise


def shared_folder(location_path: str, rel: str) -> str:
    """The absolute folder to share: the location itself for `""`, else a folder inside it.

    Links are followed and the result must stay inside the location."""
    if not rel.strip("/"):
        return location_path
    target = paths.resolve(paths.root_of(location_path), rel)
    if not target.is_dir():
        raise paths.NotFound(f"Not a folder: {rel}")
    return str(target)


def subfolder_of(location_path: str, share_path: str) -> str:
    """Where a shared folder sits inside its location, as a `/` path ("" for the location)."""
    try:
        rel = Path(share_path).relative_to(Path(location_path).resolve())
    except (ValueError, OSError):
        return ""
    return rel.as_posix() if str(rel) != "." else ""
