"""Add applied_batch_id to strategy_reclassification_stage.

Each invocation of ``apply_strategy_reclassification.py`` generates a
single batch UUID and stamps every applied row with it. This lets
operators rollback an entire batch (``WHERE applied_batch_id = :id``)
and gives the per-batch audit event a stable correlation key.

Revision ID: 0137_stage_applied_batch_id
Revises: 0136_classification_source_columns
Create Date: 2026-04-14
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0137_stage_applied_batch_id"
down_revision = "0136_classification_source_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "strategy_reclassification_stage",
        sa.Column(
            "applied_batch_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_stage_applied_batch",
        "strategy_reclassification_stage",
        ["applied_batch_id"],
        postgresql_where=sa.text("applied_batch_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_stage_applied_batch",
        table_name="strategy_reclassification_stage",
    )
    op.drop_column("strategy_reclassification_stage", "applied_batch_id")
