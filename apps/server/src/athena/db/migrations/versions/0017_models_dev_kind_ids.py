"""provider kinds use models.dev ids; refetch the models.dev cache

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE ai_providers SET kind = 'amazon-bedrock' WHERE kind = 'bedrock'")
    # The cache skipped most providers before; empty it so the next start refetches all.
    op.execute("DELETE FROM models_dev_cache")


def downgrade() -> None:
    op.execute("UPDATE ai_providers SET kind = 'bedrock' WHERE kind = 'amazon-bedrock'")
