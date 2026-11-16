"""smb shares

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "smb_shares",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("path", sqlmodel.sql.sqltypes.AutoString(length=1024), nullable=False),
        sa.Column("read_only", sa.Boolean(), nullable=False),
        sa.Column("guest_ok", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["location_id"], ["file_locations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_smb_shares_location_id"), "smb_shares", ["location_id"], unique=False)
    op.create_index(op.f("ix_smb_shares_name"), "smb_shares", ["name"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_smb_shares_name"), table_name="smb_shares")
    op.drop_index(op.f("ix_smb_shares_location_id"), table_name="smb_shares")
    op.drop_table("smb_shares")
