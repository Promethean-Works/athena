from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlmodel import SQLModel

import athena.db.models  # noqa: F401
from athena.db import Database


def test_migrations_create_the_schema(tmp_path: Path) -> None:
    db = Database(tmp_path / "athena.db")
    db.migrate()
    assert {"users", "sessions", "alembic_version"} <= set(inspect(db.engine).get_table_names())


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    db = Database(tmp_path / "athena.db")
    db.migrate()
    db.migrate()


def test_models_match_migrations(tmp_path: Path) -> None:
    """Fails when a model changes without a matching Alembic migration."""
    db = Database(tmp_path / "athena.db")
    db.migrate()
    with db.engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), SQLModel.metadata)
    assert diff == [], f"models and migrations differ; add a migration: {diff}"


def test_database_files_are_private_to_their_owner(tmp_path) -> None:
    import stat
    import sys

    import pytest

    from athena.db.engine import Database

    if sys.platform == "win32":
        pytest.skip("POSIX permissions")
    path = tmp_path / "new-data" / "athena.db"
    path.parent.mkdir()
    path.write_bytes(b"")
    path.chmod(0o644)  # a database an earlier version left world-readable
    db = Database(path)
    db.migrate()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    for extra in path.parent.glob("athena.db-*"):  # -wal, -shm
        assert stat.S_IMODE(extra.stat().st_mode) & 0o077 == 0, extra.name
    fresh = Database(tmp_path / "made" / "athena.db")
    assert stat.S_IMODE(fresh.engine.url.database and (tmp_path / "made").stat().st_mode) == 0o700
