"""Helpers shared by the SMB and NFS share providers (docs/specs/network-shares.md).

The provider modules write a host config file and ask the host's server to reload it.
A failed reload rolls the file back, so a share is never tracked that the host isn't serving.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from athena.files.paths import FileError


class ShareReloadFailed(FileError):
    """The host's share server refused the new configuration (it was rolled back)."""

    status = 502


def write_atomic(path: Path, text: str) -> None:
    """Replace `path` with `text` without ever leaving a half-written file."""
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


def run_reload(argv: list[str], what: str) -> None:
    """Run the reload command; raise `ShareReloadFailed` with its output if it fails."""
    try:
        result = subprocess.run(
            argv, check=False, capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ShareReloadFailed(f"Couldn't reload {what}: {exc}") from exc
    if result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip().splitlines()
        reason = output[-1] if output else f"exit code {result.returncode}"
        raise ShareReloadFailed(f"Couldn't reload {what}: {reason}")


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
