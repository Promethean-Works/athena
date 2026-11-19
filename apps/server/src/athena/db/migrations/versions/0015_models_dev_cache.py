"""models.dev cache table

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "models_dev_cache",
        sa.Column("provider_id", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
        sa.Column("api_url", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=True),
        sa.Column("npm_package", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=True),
        sa.Column("doc_url", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=True),
        sa.Column("env_vars", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("models", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("model_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_openai_compatible", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("provider_id"),
    )
    op.create_index(
        op.f("ix_models_dev_cache_expires_at"),
        "models_dev_cache",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_models_dev_cache_expires_at"), table_name="models_dev_cache")
    op.drop_table("models_dev_cache")
