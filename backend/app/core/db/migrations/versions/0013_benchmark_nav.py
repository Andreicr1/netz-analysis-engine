"""Benchmark NAV table + nav_timeseries performance index.

Creates benchmark_nav — a GLOBAL table (no organization_id, no RLS)
for storing benchmark NAV and return data per allocation block.
FK to allocation_blocks.block_id.

Also adds a composite index on nav_timeseries(instrument_id, nav_date DESC)
filtered by return_1d IS NOT NULL — critical for batch-fetch performance
in risk_calc, optimizer, backtest, and correlation queries.

depends_on: 0011 (instruments_data_migration).
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ═══════════════════════════════════════════════════════════════
    #  benchmark_nav — global table (no org_id, no RLS)
    #  Same pattern as allocation_blocks, macro_data.
    # ═══════════════════════════════════════════════════════════════
    op.create_table(
        "benchmark_nav",
        sa.Column("block_id", sa.String(80), sa.ForeignKey("allocation_blocks.block_id"), nullable=False),
        sa.Column("nav_date", sa.Date(), nullable=False),
        sa.Column("nav", sa.Numeric(18, 6), nullable=False),
        sa.Column("return_1d", sa.Numeric(12, 8)),
        sa.Column("return_type", sa.String(10), nullable=False, server_default="log"),
        sa.Column("source", sa.String(30), nullable=False, server_default="yfinance"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("block_id", "nav_date"),
    )

    # Return type CHECK
    op.execute("""
        ALTER TABLE benchmark_nav
        ADD CONSTRAINT chk_benchmark_nav_return_type
        CHECK (return_type IN ('log', 'arithmetic'))
    """)

    # ═══════════════════════════════════════════════════════════════
    #  Performance index on nav_timeseries
    #  Supports IN(:instrument_ids) + date range + NOT NULL filter
    #  used by risk_calc, optimizer, backtest, correlation engines.
    # ═══════════════════════════════════════════════════════════════
    op.execute("""
        CREATE INDEX ix_nav_timeseries_instrument_date
        ON nav_timeseries (instrument_id, nav_date DESC)
        WHERE return_1d IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_nav_timeseries_instrument_date")
    op.drop_table("benchmark_nav")
