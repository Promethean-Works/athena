"""Private files for the tunnel auto-start services (the tunnel's auth token).

The token never goes in a unit file, a plist or a command line (those are readable by
other users or visible in `ps`). It is written to a file only its owner can read, and
the service is pointed at that file.
"""

import os
import platform
from pathlib import Path


def private_dir() -> Path:
    """Where the service reads its secret files; created owner-only on Unix."""
    system = platform.system().lower()
    if system == "windows":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        path = base / "Athena"
    elif system == "darwin":
        path = Path.home() / "Library" / "Application Support" / "Athena"
    else:
        path = Path("/etc/athena")
    path.mkdir(parents=True, exist_ok=True)
    if system != "windows":
        path.chmod(0o700)
    return path


def write_private(path: Path, text: str) -> None:
    """Write `text` to `path` readable by the owner only (mode 0600; on Windows the
    folder under %LOCALAPPDATA% is already limited to the user by its ACL)."""
    path.unlink(missing_ok=True)  # a leftover file may have looser permissions
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    if platform.system().lower() != "windows":
        path.chmod(0o600)


def remove_private(path: Path) -> None:
    path.unlink(missing_ok=True)


def windows_command(argv: list[str]) -> str:
    """One `schtasks /TR` string; each part quoted so paths with spaces work."""
    return " ".join(f'"{a}"' for a in argv)
