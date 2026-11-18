"""automation triggers and job runs

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "automation_triggers",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("cron_expression", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=True),
        sa.Column("action", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("webhook_token", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
        sa.Column(
            "next_run_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_run_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_automation_triggers_next_run_at"),
        "automation_triggers",
        ["next_run_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_automation_triggers_updated_at"),
        "automation_triggers",
        ["updated_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_automation_triggers_webhook_token"),
        "automation_triggers",
        ["webhook_token"],
        unique=True,
    )

    op.create_table(
        "automation_job_runs",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("trigger_id", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("output", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("error", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("automation_job_runs")
    op.drop_index(op.f("ix_automation_triggers_webhook_token"), table_name="automation_triggers")
    op.drop_index(op.f("ix_automation_triggers_updated_at"), table_name="automation_triggers")
    op.drop_index(op.f("ix_automation_triggers_next_run_at"), table_name="automation_triggers")
    op.drop_table("automation_triggers")
