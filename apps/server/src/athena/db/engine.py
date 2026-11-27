"""Engine creation and Alembic upgrades, configured in code so the migrations ship in the wheel."""

import contextlib
import logging
import sys
from collections.abc import Iterator
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, event
from sqlmodel import Session, create_engine

log = logging.getLogger(__name__)

MIGRATIONS = Path(__file__).parent / "migrations"


def alembic_config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def _private(path: Path) -> None:
    """Make the database readable by its owner only (POSIX).

    It holds share and webhook tokens, password hashes and session tokens. A folder Athena
    creates is 0700; an existing one is left alone (it may be the user's). The file, and so
    the -wal and -shm files SQLite copies its mode to, is 0600, including a database an
    earlier version made world-readable.
    """
    created = not path.parent.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        return
    # Best effort: a file another user owns (an earlier run under sudo) can't be changed,
    # and must not stop Athena from starting.
    with contextlib.suppress(OSError):
        if created:
            path.parent.chmod(0o700)
        path.touch(mode=0o600, exist_ok=True)
        path.chmod(0o600)


class Database:
    def __init__(self, path: Path) -> None:
        _private(path)
        self.url = f"sqlite:///{path.as_posix()}"
        self.engine: Engine = create_engine(self.url, connect_args={"check_same_thread": False})
        event.listen(self.engine, "connect", _sqlite_pragmas)

    def migrate(self) -> None:
        """Bring the schema to the latest migration. Safe to run on every start."""
        with self.engine.begin() as conn:
            cfg = alembic_config(self.url)
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
        log.info("database ready at %s", self.url)

    def session(self) -> Iterator[Session]:
        with Session(self.engine) as session:
            yield session
