"""nfs shares

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "nfs_shares",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("path", sqlmodel.sql.sqltypes.AutoString(length=1024), nullable=False),
        sa.Column("clients", sqlmodel.sql.sqltypes.AutoString(length=2048), nullable=False),
        sa.Column("read_only", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["location_id"], ["file_locations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path"),
    )
    op.create_index(op.f("ix_nfs_shares_location_id"), "nfs_shares", ["location_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_nfs_shares_location_id"), table_name="nfs_shares")
    op.drop_table("nfs_shares")
