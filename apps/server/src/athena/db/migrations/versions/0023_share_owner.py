"""shares belong to a user id, not a username

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("shares") as batch:
        batch.add_column(sa.Column("owner_id", sa.Integer(), nullable=True))
        batch.create_index(op.f("ix_shares_owner_id"), ["owner_id"], unique=False)
        batch.create_foreign_key(
            "fk_shares_owner_id_users", "users", ["owner_id"], ["id"], ondelete="CASCADE"
        )
    op.execute(
        "UPDATE shares SET owner_id = "
        "(SELECT id FROM users WHERE users.username = shares.created_by)"
    )


def downgrade() -> None:
    with op.batch_alter_table("shares") as batch:
        batch.drop_constraint("fk_shares_owner_id_users", type_="foreignkey")
        batch.drop_index(op.f("ix_shares_owner_id"))
        batch.drop_column("owner_id")
