"""File locations: the folders the file manager may reach (docs/design/files.md)."""

import os
import shutil
import sys
from pathlib import Path

from sqlmodel import Session, select

from athena.db.models import FileLocation, SystemSetting, User
from athena.files.paths import BadPath, Conflict, NotFound

SEEDED_KEY = "files_defaults_seeded"


def default_locations(data_dir: Path) -> list[tuple[str, Path]]:
    """Home, and the folder that holds the apps' data.

    Linux runs Athena as a root service, where "home" would be /root; /home holds the
    people's folders there instead.
    """
    if sys.platform.startswith("linux") and os.geteuid() == 0:
        home = Path("/home")
    else:
        home = Path.home()
    found = [("Home", home)] if home.is_dir() else []
    return [*found, ("App data", data_dir / "apps")]


def seed_defaults(db: Session, data_dir: Path) -> None:
    """Add the default locations once, on the first start. Removing them sticks."""
    if db.get(SystemSetting, SEEDED_KEY) is not None:
        return
    for name, path in default_locations(data_dir):
        path.mkdir(parents=True, exist_ok=True)
        db.add(FileLocation(name=name, path=str(path.resolve())))
    db.add(SystemSetting(key=SEEDED_KEY, value="1"))
    db.commit()


def all_locations(db: Session) -> list[FileLocation]:
    return list(db.exec(select(FileLocation).order_by(FileLocation.id)))  # type: ignore[arg-type]


def can_open(loc: FileLocation, user: User) -> bool:
    """Admins open every location; a user their own folder and the ones shared with users."""
    if user.is_admin:
        return True
    return loc.owner_id == user.id if loc.owner_id is not None else loc.users_can_open


def visible_to(db: Session, user: User) -> list[FileLocation]:
    return [loc for loc in all_locations(db) if can_open(loc, user)]


def user_folder(data_dir: Path, user_id: int) -> Path:
    return data_dir / "users" / str(user_id) / "files"


def ensure_user_folder(db: Session, data_dir: Path, user: User) -> FileLocation:
    """A user's own "My files" folder and its location, made on first need. The stored
    name carries the username so it stays unique; the UI shows it as "My files"."""
    assert user.id is not None
    found = db.exec(select(FileLocation).where(FileLocation.owner_id == user.id)).first()
    folder = user_folder(data_dir, user.id)
    folder.mkdir(parents=True, exist_ok=True)
    if found is not None:
        if found.path != str(folder.resolve()):  # the data folder was moved
            found.path = str(folder.resolve())
            db.add(found)
            db.commit()
        return found
    loc = FileLocation(
        name=f"My files ({user.username})"[:64], path=str(folder.resolve()), owner_id=user.id
    )
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc


def delete_user_folder(data_dir: Path, user_id: int) -> None:
    """When an account is deleted, its folder (`users/<id>`) goes with it, so a later
    account that gets the same id can't inherit the files."""
    shutil.rmtree(user_folder(data_dir, user_id).parent, ignore_errors=True)


def get(db: Session, location_id: int, user: User | None = None) -> FileLocation:
    """The location, or NotFound. With `user`, a location they can't open is NotFound too
    (404, so ids don't leak which locations exist)."""
    loc = db.get(FileLocation, location_id)
    if loc is None or (user is not None and not can_open(loc, user)):
        raise NotFound("No such location")
    return loc


def checked_path(raw: str) -> str:
    """An absolute, existing folder, with `~` expanded and links resolved."""
    path = Path(raw.strip()).expanduser()
    if not path.is_absolute():
        raise BadPath("Use an absolute path, like /srv/media or D:\\Media")
    if not path.is_dir():
        raise BadPath(f"{path} isn't an existing folder")
    return str(path.resolve())


def save(
    db: Session, loc: FileLocation, name: str, path: str, users_can_open: bool = False
) -> FileLocation:
    name = name.strip()
    if not name:
        raise BadPath("Give the location a name")
    taken = db.exec(select(FileLocation).where(FileLocation.name == name)).first()
    if taken is not None and taken.id != loc.id:
        raise Conflict(f"A location named {name} already exists")
    loc.name = name
    loc.path = checked_path(path)
    loc.users_can_open = users_can_open
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc
