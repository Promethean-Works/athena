"""next run time for scheduled backup plans

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "backup_plans",
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_backup_plans_next_run_at"),
        "backup_plans",
        ["next_run_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_backup_plans_next_run_at"), table_name="backup_plans")
    op.drop_column("backup_plans", "next_run_at")
