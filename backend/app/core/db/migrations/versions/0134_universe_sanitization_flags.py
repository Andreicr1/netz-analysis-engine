"""Add is_institutional + exclusion_reason for universe sanitization.

Adds a three-column triplet (``is_institutional``, ``exclusion_reason``,
``sanitized_at``) to the six fund source tables plus a generated
``is_institutional`` column on ``instruments_universe`` that reads from
the JSONB ``attributes`` payload.

Default is TRUE on every existing row: the sanitization worker
(``universe_sanitization``, lock 900_063) re-runs to compute the flag.
Partial indexes on ``is_institutional = true`` keep downstream filtered
queries fast; the sanitized subset is ~65% of the universe.

Revision ID: 0134_universe_sanitization_flags
Revises: 0133_strategy_reclassification_stage
Create Date: 2026-04-14
"""

import sqlalchemy as sa

from alembic import op

revision = "0134_universe_sanitization_flags"
down_revision = "0133_strategy_reclassification_stage"
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
            sa.Column(
                "is_institutional",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("true"),
            ),
        )
        op.add_column(
            table,
            sa.Column("exclusion_reason", sa.Text, nullable=True),
        )
        op.add_column(
            table,
            sa.Column(
                "sanitized_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
        op.create_index(
            f"idx_{table}_institutional",
            table,
            ["is_institutional"],
            postgresql_where=sa.text("is_institutional = true"),
        )

    # instruments_universe stores the flag inline via a generated column
    # reading from the JSONB ``attributes`` payload so propagation from
    # source tables is a single JSONB merge.
    op.execute(
        """
        ALTER TABLE instruments_universe
        ADD COLUMN is_institutional BOOLEAN
        GENERATED ALWAYS AS (
            COALESCE((attributes->>'is_institutional')::boolean, true)
        ) STORED
        """,
    )
    op.create_index(
        "idx_instruments_universe_institutional",
        "instruments_universe",
        ["is_institutional"],
        postgresql_where=sa.text("is_institutional = true"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_instruments_universe_institutional",
        table_name="instruments_universe",
    )
    op.execute(
        "ALTER TABLE instruments_universe DROP COLUMN is_institutional",
    )
    for table in TABLES:
        op.drop_index(f"idx_{table}_institutional", table_name=table)
        op.drop_column(table, "sanitized_at")
        op.drop_column(table, "exclusion_reason")
        op.drop_column(table, "is_institutional")
