"""Turning API paths into host paths without leaving a location.

The API names a file by a location id plus a path relative to it, always with `/`
separators ("photos/2024/a.jpg", "" for the location itself). Two ways to resolve:

- `resolve()` follows symlinks, for reading and listing: the real path must be inside
  the location's real path, so a link that points outside is refused.
- `entry()` resolves only the parent and keeps the last name as is, for acting on the
  entry itself (delete, rename, move): deleting a link removes the link, never what it
  points to, even when that is outside the location.
"""

import os
import sys
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

WINDOWS = sys.platform == "win32"
# Characters Windows can't store in a name. New names avoid them on every OS, so files
# made through Athena can be copied to any host. Existing names are read as they are.
WINDOWS_RESERVED = set('<>:"/\\|?*')
WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)
}
UPLOAD_PREFIX = ".athena-upload-"


# Athena's own data folder, off limits to plain users and share visitors for the length of
# one request (set by `protect`). Everything in it is the server's: `secret.key`, the
# database, `athena.json`, TLS keys, logs. Only `<data>/apps` is reachable (the "App
# data" location), minus what the server runs or keeps secret: each app's `.env` and
# compose files (editing one is running code as the Athena account on the next restart).
# Paths are compared by file identity (device and inode), not by text, so a different
# spelling on a case-insensitive disk (`DATA`, `.ENV`) doesn't get around it.
APP_PRIVATE = {".env", "compose.yaml", "compose.prev.yaml"}


@dataclass(frozen=True)
class _Guard:
    data: Path
    data_id: tuple[int, int] | None
    apps_id: tuple[int, int] | None


_protected: ContextVar[_Guard | None] = ContextVar("protected_data_dir", default=None)


def _identity(path: Path) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino)


def protect(data_dir: Path) -> None:
    """Refuse the data folder (see above) for the rest of this request."""
    data = data_dir.resolve()
    _protected.set(_Guard(data, _identity(data), _identity(data / "apps")))


def _chain(path: Path) -> list[Path]:
    """`path` and its parents, nearest first."""
    return [path, *path.parents]


def is_protected(path: Path) -> bool:
    """True when a restricted request must not read, list, copy or change `path`."""
    guard = _protected.get()
    if guard is None or guard.data_id is None:
        return False
    below: list[Path] = []  # the names under the data folder, from `path` upward
    for ancestor in _chain(path):
        ident = _identity(ancestor)
        if ident == guard.data_id:
            if not below:
                return True  # the data folder itself
            if guard.apps_id is None or _identity(below[-1]) != guard.apps_id:
                return True  # anything but apps/
            return any(p.name.casefold() in APP_PRIVATE for p in below[:-1])
        below.append(ancestor)
    return False


def holds_protected(path: Path) -> bool:
    """True when deleting, renaming or moving the folder `path` would take protected
    files along: the data folder, `apps`, an app's own folder, or anything above them."""
    guard = _protected.get()
    if guard is None or guard.data_id is None or os.path.islink(path):
        return False
    here = _identity(path)
    if here is None or not os.path.isdir(path):
        return False
    if here in (guard.data_id, guard.apps_id):
        return True
    if guard.apps_id is not None and _identity(path.parent) == guard.apps_id:
        return True  # apps/<name>: holds the app's .env and compose.yaml
    return any(_identity(p) == here for p in _chain(guard.data))


class FileError(Exception):
    """A file operation that can't be done; `status` is the HTTP status to answer with."""

    status = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class BadPath(FileError):
    status = 400


class Forbidden(FileError):
    status = 403


class NotFound(FileError):
    status = 404


class Conflict(FileError):
    status = 409


def _check_segment(part: str) -> None:
    if part in ("", ".", "..") or "\0" in part or (WINDOWS and ("\\" in part or ":" in part)):
        raise BadPath(f"Invalid path segment: {part!r}")


def split(rel: str) -> list[str]:
    """The segments of an API path. Leading and trailing slashes are ignored."""
    rel = rel.strip("/")
    if not rel:
        return []
    parts = rel.split("/")
    for part in parts:
        _check_segment(part)
    return parts


def check_new_name(name: str) -> str:
    """A name for something Athena creates: one segment, valid on every OS."""
    if not name or len(name.encode()) > 255:
        raise BadPath("Names must be 1 to 255 bytes long")
    if name in (".", "..") or name.endswith((" ", ".")) or name != name.strip():
        raise BadPath("Names can't be . or .., or start or end with a space, or end with a dot")
    if any(c in WINDOWS_RESERVED or ord(c) < 32 for c in name):
        raise BadPath("Names can't contain control characters or any of < > : \" / \\ | ? *")
    if name.split(".")[0].upper() in WINDOWS_DEVICES:
        raise BadPath(f"{name} is a reserved name on Windows")
    if name.startswith(UPLOAD_PREFIX):
        raise BadPath("That name is reserved for uploads in progress")
    return name


def root_of(location_path: str) -> Path:
    """The real path of a location's folder."""
    root = Path(location_path).resolve()
    if not root.is_dir():
        raise NotFound(f"The location's folder doesn't exist: {location_path}")
    return root


def inside(root: Path, path: Path) -> bool:
    return path == root or path.is_relative_to(root)


def resolve(root: Path, rel: str) -> Path:
    """The real path for `rel`, following links. It may not exist yet."""
    path = root.joinpath(*split(rel)).resolve()
    if not inside(root, path):
        raise Forbidden("That path leads outside the location")
    refuse_protected(path)
    return path


def refuse_protected(path: Path) -> None:
    if is_protected(path):
        raise Forbidden("Athena keeps its own files there; only an admin can open them")


def entry(root: Path, rel: str) -> Path:
    """The entry `rel` names, with its parent resolved but the entry itself not followed."""
    parts = split(rel)
    if not parts:
        raise BadPath("This can't be done to the location itself")
    parent = str(resolve(root, "/".join(parts[:-1])))
    # Normalize and check again: Windows drops trailing dots and spaces, so "..." would
    # name the parent folder itself and "a " the entry "a". Refuse any name that
    # normalizing changes.
    candidate = os.path.abspath(os.path.join(parent, parts[-1]))
    prefix = parent if parent.endswith(os.sep) else parent + os.sep
    if (
        not candidate.startswith(prefix)
        or os.path.dirname(candidate) != parent
        or os.path.basename(candidate) != parts[-1]
    ):
        raise BadPath(f"Invalid name: {parts[-1]!r}")
    refuse_protected(Path(candidate))
    if holds_protected(Path(candidate)):
        raise Forbidden("That folder holds Athena's own files; only an admin can change it")
    return Path(candidate)


def existing_entry(root: Path, rel: str) -> Path:
    path = entry(root, rel)
    if not path.exists(follow_symlinks=False):
        raise NotFound(f"Not found: {rel}")
    return path


def relative(root: Path, path: Path) -> str:
    """The API path of `path`, which must be inside `root` (its parent resolved)."""
    return path.relative_to(root).as_posix() if path != root else ""


def available_name(folder: Path, name: str) -> str:
    """`name`, or "name (1).ext", "name (2).ext"… if that is taken in `folder`."""
    if not (folder / name).exists(follow_symlinks=False):
        return name
    # The extension is after the last dot, but a leading dot (".bashrc") isn't one.
    stem, ext = name.rsplit(".", 1) if "." in name[1:] else (name, "")
    for i in range(1, 10_000):
        candidate = f"{stem} ({i}).{ext}" if ext else f"{stem} ({i})"
        if not (folder / candidate).exists(follow_symlinks=False):
            return candidate
    raise Conflict(f"Couldn't find a free name for {name}")
