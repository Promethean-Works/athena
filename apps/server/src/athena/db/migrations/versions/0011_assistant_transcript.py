"""The full transcript of a compacted assistant chat

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ai_conversations") as batch:
        batch.add_column(sa.Column("transcript", sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ai_conversations") as batch:
        batch.drop_column("transcript")
