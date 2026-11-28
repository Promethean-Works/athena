"""file locations: per-user folders and which locations plain users may open

Existing locations are closed to plain users on upgrade (users_can_open false); an
admin opens them again in Settings.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("file_locations") as batch:
        batch.add_column(sa.Column("owner_id", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("users_can_open", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.create_index(op.f("ix_file_locations_owner_id"), ["owner_id"], unique=False)
        batch.create_foreign_key(
            "fk_file_locations_owner_id_users", "users", ["owner_id"], ["id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    with op.batch_alter_table("file_locations") as batch:
        batch.drop_constraint("fk_file_locations_owner_id_users", type_="foreignkey")
        batch.drop_index(op.f("ix_file_locations_owner_id"))
        batch.drop_column("users_can_open")
        batch.drop_column("owner_id")
