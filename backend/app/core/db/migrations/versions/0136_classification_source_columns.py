"""Add classification_source + classification_updated_at to fund tables.

Lineage columns for the cascade strategy classifier apply gate. Each
``UPDATE strategy_label`` issued by ``apply_strategy_reclassification.py``
also stamps ``classification_source`` (which cascade layer fired) and
``classification_updated_at`` (when the apply happened) so operators
can trace any production label back to its origin.

``instruments_universe`` already carries this lineage in its JSONB
``attributes`` column, so it is excluded from this migration.

Revision ID: 0136_classification_source_columns
Revises: 0135_mv_unified_funds_institutional
Create Date: 2026-04-14
"""

import sqlalchemy as sa

from alembic import op

revision = "0136_classification_source_columns"
down_revision = "0135_mv_unified_funds_institutional"
branch_labels = None
depends_on = None


TABLES = (
    "sec_manager_funds",
    "sec_registered_funds",
    "sec_etfs",
    "sec_bdcs",
    "sec_money_market_funds",
    "esma_funds",
)


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column("classification_source", sa.Text(), nullable=True),
        )
        op.add_column(
            table,
            sa.Column(
                "classification_updated_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
        # Partial index — operators query "what changed today?" — keeps
        # the index small (only reclassified rows) and the lookup fast.
        op.create_index(
            f"idx_{table}_classification_updated",
            table,
            ["classification_updated_at"],
            postgresql_where=sa.text("classification_updated_at IS NOT NULL"),
        )


def downgrade() -> None:
    for table in TABLES:
        op.drop_index(
            f"idx_{table}_classification_updated",
            table_name=table,
        )
        op.drop_column(table, "classification_updated_at")
        op.drop_column(table, "classification_source")
