"""backup destinations and plans

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backup_destinations",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("location", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("password", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "backup_plans",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("destination_id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("items", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("schedule", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("retention", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True),
        sa.Column("last_error", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["destination_id"], ["backup_destinations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("backup_plans")
    op.drop_table("backup_destinations")
