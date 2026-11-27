"""remote mounts

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "remote_mounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("remote", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("path", sqlmodel.sql.sqltypes.AutoString(length=1024), nullable=False),
        sa.Column("mount_point", sqlmodel.sql.sqltypes.AutoString(length=1024), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("read_only", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["location_id"], ["file_locations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("location_id"),
    )
    op.create_index(op.f("ix_remote_mounts_remote"), "remote_mounts", ["remote"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_remote_mounts_remote"), table_name="remote_mounts")
    op.drop_table("remote_mounts")
