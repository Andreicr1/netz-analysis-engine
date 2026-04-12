"""fund_risk_metrics elite_flag + ranking columns.

Adds the three columns that the ELITE ranking worker (Session 2.B
commit 7) populates:

- elite_flag: boolean, true for funds in the top N of their strategy
  where N is computed from the global default allocation weight for
  that strategy. Total elite funds across all strategies sums to 300.
- elite_rank_within_strategy: ordinal rank of the fund within its
  strategy bucket, 1 = best. NULL for funds outside their strategy's
  target count.
- elite_target_count_per_strategy: the computed target count for this
  fund's strategy (300 * strategy_weight), denormalized here for
  traceability and audit.

The columns are nullable to allow incremental population — the worker
may not produce values for every instrument every pass.

Partial index ``idx_fund_risk_metrics_elite_partial`` supports the
Phase 3 Screener ELITE filter hot path. Phase 2 Session A converted
``fund_risk_metrics`` to a hypertable with
``compress_segmentby = 'instrument_id'``, so the partial index is
attached to every chunk at creation time. The index columns are
``(instrument_id, calc_date DESC)`` — ``calc_date`` is the real
time column on this table (the original plan referred to ``as_of``
which does not exist in the schema).

Revision ID: 0115_fund_risk_metrics_elite_flag
Revises: 0114_wealth_vector_chunks_hypertable
Create Date: 2026-04-11
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0115_fund_risk_metrics_elite_flag"
down_revision: str | None = "0114_wealth_vector_chunks_hypertable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "fund_risk_metrics",
        sa.Column("elite_flag", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "fund_risk_metrics",
        sa.Column("elite_rank_within_strategy", sa.SmallInteger(), nullable=True),
    )
    op.add_column(
        "fund_risk_metrics",
        sa.Column("elite_target_count_per_strategy", sa.SmallInteger(), nullable=True),
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_fund_risk_metrics_elite_partial
        ON fund_risk_metrics (instrument_id, calc_date DESC)
        WHERE elite_flag = true
        """,
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_fund_risk_metrics_elite_partial")
    op.drop_column("fund_risk_metrics", "elite_target_count_per_strategy")
    op.drop_column("fund_risk_metrics", "elite_rank_within_strategy")
    op.drop_column("fund_risk_metrics", "elite_flag")
