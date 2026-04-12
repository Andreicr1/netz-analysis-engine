"""mv_fund_risk_latest materialized view.

Pre-computes the latest (by calc_date) fund_risk_metrics row per
instrument_id. Screener queries read from this view directly instead
of running a correlated subquery like:

  SELECT * FROM fund_risk_metrics f
  WHERE f.calc_date = (
    SELECT MAX(calc_date) FROM fund_risk_metrics
    WHERE instrument_id = f.instrument_id
  )

which is prohibitively slow at 9k+ instruments.

Rationale for WHERE organization_id IS NULL:
``fund_risk_metrics`` has two writer workers:
1. ``global_risk_metrics`` (lock 900_071) writes global rows with
   ``organization_id = NULL`` covering every instrument in
   ``instruments_universe`` — this is where ELITE ranking lives.
2. ``risk_calc`` (lock 900_007) can overwrite rows with DTW drift
   for org-imported instruments (``organization_id`` set).

ELITE ranking is a global concept (the top 300 funds across the
catalog, NOT per-tenant), so it is only written on global rows. The
screener hot path reads the global set; per-tenant DTW overlay is
applied separately when rendering funds inside a user's universe.

The MV's unique index on ``instrument_id`` enables CONCURRENT refresh.
Supporting indexes match the Phase 3 Screener's primary filter +
sort hot paths:

- partial on ``WHERE elite_flag = true`` for the ELITE filter
- btree on ``sharpe_1y DESC NULLS LAST`` for the default sort

Refreshed by the ``risk_calc`` worker after each pass (wired in the
ELITE ranking commit of this session).

Revision ID: 0116_mv_fund_risk_latest
Revises: 0115_fund_risk_metrics_elite_flag
Create Date: 2026-04-11
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0116_mv_fund_risk_latest"
down_revision: str | None = "0115_fund_risk_metrics_elite_flag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE MATERIALIZED VIEW mv_fund_risk_latest AS
        SELECT DISTINCT ON (instrument_id)
            instrument_id,
            calc_date,
            manager_score,
            sharpe_1y,
            sortino_1y,
            volatility_1y,
            volatility_garch,
            cvar_95_12m,
            cvar_95_conditional,
            max_drawdown_1y,
            return_1y,
            blended_momentum_score,
            peer_strategy_label,
            peer_sharpe_pctl,
            peer_sortino_pctl,
            peer_return_pctl,
            peer_drawdown_pctl,
            peer_count,
            elite_flag,
            elite_rank_within_strategy,
            elite_target_count_per_strategy
        FROM fund_risk_metrics
        WHERE organization_id IS NULL
        ORDER BY instrument_id, calc_date DESC
        WITH NO DATA
        """,
    )

    op.execute(
        """
        CREATE UNIQUE INDEX uq_mv_fund_risk_latest_instrument
        ON mv_fund_risk_latest (instrument_id)
        """,
    )

    op.execute(
        """
        CREATE INDEX idx_mv_fund_risk_latest_elite
        ON mv_fund_risk_latest (instrument_id)
        WHERE elite_flag = true
        """,
    )

    op.execute(
        """
        CREATE INDEX idx_mv_fund_risk_latest_sharpe
        ON mv_fund_risk_latest (sharpe_1y DESC NULLS LAST)
        """,
    )

    op.execute(
        """
        CREATE INDEX idx_mv_fund_risk_latest_manager_score
        ON mv_fund_risk_latest (manager_score DESC NULLS LAST)
        """,
    )

    op.execute("REFRESH MATERIALIZED VIEW mv_fund_risk_latest")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_fund_risk_latest")
