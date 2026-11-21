"""Backup destinations: validating where a repository goes, its password and recovery kit."""

import os
import secrets
import shutil
import sys
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from athena.backup import restic
from athena.backup.restic import Repository, Restic, ResticError

PASSWORD_BYTES = 32
MIN_PASSWORD_LENGTH = 12

# Folders that are never a place to put a backup repository.
_SYSTEM_FOLDERS_POSIX = (
    "/bin",
    "/boot",
    "/dev",
    "/etc",
    "/lib",
    "/lib64",
    "/proc",
    "/run",
    "/sbin",
    "/sys",
    "/usr",
    "/var/lib/docker",
    "/System",
    "/Library",
    "/private/etc",
)


class DestinationError(ValueError):
    """The destination can't be used; the message says why and is shown to the admin."""


def _is_inside(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents


def _system_folders() -> list[Path]:
    if sys.platform == "win32":
        roots = (
            os.environ.get("SYSTEMROOT", r"C:\Windows"),
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
        )
        return [Path(r) for r in roots]
    return [Path(p) for p in _SYSTEM_FOLDERS_POSIX]


def _is_absolute(raw: str) -> bool:
    """Absolute for this OS: `D:\\x` isn't a folder on Linux, `/x` isn't one on Windows."""
    if sys.platform == "win32":
        return PureWindowsPath(raw).is_absolute()
    return PurePosixPath(raw).is_absolute()


def check_local_path(raw: str, data_dir: Path, allowed_roots: list[Path] | None = None) -> Path:
    """The folder for a local repository, or `DestinationError`.

    It must be absolute, writable, not a system folder and not inside Athena's own data
    folder (a backup of itself that a restore would delete along with the data).
    It must also be inside one of the configured allowed backup root folders.
    """
    raw = raw.strip()
    if not raw:
        raise DestinationError("Enter a folder")
    if "\x00" in raw or not _is_absolute(raw):
        raise DestinationError("Use a full path, like /mnt/backup or D:\\Backups")
    path = Path(os.path.normpath(raw))
    resolved = path.resolve(strict=False)
    if path != resolved:
        raise DestinationError("Symbolic links are not allowed; pick a real folder path")
    if resolved == Path(resolved.anchor):
        raise DestinationError("Pick a folder, not the root of a disk")
    for folder in _system_folders():
        if _is_inside(resolved, folder.resolve()):
            raise DestinationError(f"{folder} is a system folder; pick another")
    if _is_inside(resolved, data_dir.resolve()):
        raise DestinationError(
            "That folder is inside Athena's data folder, so it would be lost with it. "
            "Pick a folder or disk outside it"
        )

    if not allowed_roots:
        raise DestinationError("No allowed backup locations are configured")
    roots = [Path(root).resolve(strict=False) for root in allowed_roots if Path(root).is_absolute()]
    if not roots:
        raise DestinationError("No allowed backup locations are configured")
    if not any(_is_inside(resolved, root) for root in roots):
        raise DestinationError("Pick a folder inside an allowed backup location")

    if resolved.exists() and not resolved.is_dir():
        raise DestinationError(f"{resolved} is a file, not a folder")
    return resolved


def check_writable(folder: Path, allowed_roots: list[Path] | None = None) -> None:
    """Create the folder if needed and prove Athena can write in it."""
    raw = str(folder).strip()
    if "\x00" in raw or not _is_absolute(raw):
        raise DestinationError("Use a full path, like /mnt/backup or D:\\Backups")
    target = Path(os.path.normpath(raw)).resolve(strict=False)
    if not allowed_roots:
        raise DestinationError("No allowed backup locations are configured")
    roots = [Path(root).resolve(strict=False) for root in allowed_roots if Path(root).is_absolute()]
    if not roots:
        raise DestinationError("No allowed backup locations are configured")
    if not any(_is_inside(target, root) for root in roots):
        raise DestinationError("Pick a folder inside an allowed backup location")

    canonical_roots = [Path(os.path.realpath(os.fspath(root))) for root in roots]

    def _canonical_inside_allowed(candidate: Path) -> Path:
        canonical_candidate = Path(os.path.realpath(os.fspath(candidate)))
        if not any(_is_inside(canonical_candidate, root) for root in canonical_roots):
            raise DestinationError("Pick a folder inside an allowed backup location")
        return canonical_candidate

    safe_target = _canonical_inside_allowed(target)
    try:
        safe_target.mkdir(parents=True, exist_ok=True)
        writable = safe_target.resolve(strict=True)
        safe_writable_path = _canonical_inside_allowed(writable)
        if safe_target.is_symlink() or safe_writable_path != safe_target:
            raise DestinationError("Symbolic links are not allowed; pick a real folder path")

        with tempfile.NamedTemporaryFile(
            dir=os.fspath(safe_writable_path), prefix=".athena-write-test-"
        ):
            pass
    except OSError as exc:
        raise DestinationError(f"Athena can't write in {safe_target}: {exc.strerror or exc}") from exc


def generate_password() -> str:
    return secrets.token_urlsafe(PASSWORD_BYTES)


def check_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise DestinationError(f"The password needs at least {MIN_PASSWORD_LENGTH} characters")
    return password


def recovery_kit(name: str, location: str, password: str) -> str:
    """The text the admin saves. Without it a dead host means unreadable backups."""
    return f"""Athena backup recovery kit
==========================

Keep this file somewhere safe and off this server (a password manager, a printout).
Anyone with it and the backup files can read your backups; without it nobody can,
including you: Athena's own copy of the password is stored on this server.

Destination: {name}
Repository:  {location}
Password:    {password}
restic:      {restic.VERSION}

Restore without Athena
----------------------
1. Install restic {restic.VERSION} (https://restic.net).
2. Point it at the repository and give it the password:

     export RESTIC_REPOSITORY='{location}'
     export RESTIC_PASSWORD='{password}'
     restic snapshots

3. Restore a snapshot into a folder (the tag says what it holds):

     restic restore latest --tag athena --target ./restored
     restic restore latest --tag app:<name> --target ./restored

For a repository on an rclone remote, use RESTIC_REPOSITORY='rclone:<remote>:<path>'
with the same rclone configuration.
"""


def kit_filename(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-") or "backup"
    return f"athena-recovery-kit-{safe}.txt"


async def init_or_open(tool: Restic, repo: Repository) -> bool:
    """Open the repository, creating it if it doesn't exist. True when it was created.

    Opening one that already exists is how a new host finds old backups. A wrong
    password for an existing one is an error: it must never be re-initialised.
    """
    probe = await tool.run(repo, "cat", "config")
    if probe.code == 0:
        return False
    if probe.code == restic.EXIT_WRONG_PASSWORD:
        raise ResticError("That password doesn't open the repository in this folder", probe.code)
    if probe.code != restic.EXIT_NO_REPOSITORY:
        raise ResticError(restic.failure_message(probe), probe.code)
    await tool.run_ok(repo, "init")
    return True


def looks_like_repository(folder: Path) -> bool:
    """A restic repository has `config`, `keys/` and `data/` at its top."""
    return (
        (folder / "config").is_file() and (folder / "keys").is_dir() and (folder / "data").is_dir()
    )


def delete_repository(folder: Path) -> None:
    """Delete a local repository's files; refuses anything that isn't one."""
    if not looks_like_repository(folder):
        raise DestinationError(f"{folder} doesn't look like a restic repository, so it was kept")
    shutil.rmtree(folder)
