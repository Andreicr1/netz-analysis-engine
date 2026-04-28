"""PR-Q85 — Re-prioritize UCITS ticker selection by exchange suffix.

esma_isin_ticker_map has multiple listings per fund_lei (cross-listed
share classes). Previous propagation to esma_funds.yahoo_ticker grabbed
an arbitrary first listing, usually .LX (Luxembourg) which Yahoo Finance
often returns 404 for. This migration re-resolves all tickers using
exchange suffix priority: .L > .PA > .AS > .MI > .MC > .BR > .VI > .SW
> .OL > .CO > .HE > .F > .LX.

Only applies genuine exchange UPGRADES (new suffix priority < current
suffix priority). Same-exchange ticker changes are skipped to avoid
unnecessary churn. Idempotent via strict-less-than comparison.

Revision ID: 0191_q85_reprioritize_esma_tickers
Revises: 0190_screening_runs_allow_watchlist
Create Date: 2026-04-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0191_q85_reprioritize_esma_tickers"
down_revision: str | None = "0190_screening_runs_allow_watchlist"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Exchange suffix priority — lower = better liquidity / Yahoo coverage
_PRIO_CASE = """
    CASE
        WHEN {col} LIKE '%.L'  THEN 1   -- LSE
        WHEN {col} LIKE '%.PA' THEN 2   -- Euronext Paris
        WHEN {col} LIKE '%.AS' THEN 3   -- Euronext Amsterdam
        WHEN {col} LIKE '%.MI' THEN 4   -- Borsa Italiana
        WHEN {col} LIKE '%.MC' THEN 5   -- Madrid
        WHEN {col} LIKE '%.BR' THEN 6   -- Brussels
        WHEN {col} LIKE '%.VI' THEN 7   -- Vienna
        WHEN {col} LIKE '%.SW' THEN 8   -- SIX Swiss
        WHEN {col} LIKE '%.OL' THEN 9   -- Oslo
        WHEN {col} LIKE '%.CO' THEN 10  -- Copenhagen
        WHEN {col} LIKE '%.HE' THEN 11  -- Helsinki
        WHEN {col} LIKE '%.F'  THEN 12  -- Frankfurt
        WHEN {col} LIKE '%.LX' THEN 13  -- Luxembourg (deprio)
        ELSE 99
    END
""".strip()


def upgrade() -> None:
    prio_new = _PRIO_CASE.format(col="tm.yahoo_ticker")
    prio_current = _PRIO_CASE.format(col="ef.yahoo_ticker")

    # Step 1: Re-prioritize esma_funds.yahoo_ticker
    op.execute(f"""
        WITH ranked AS (
            SELECT
                fund_lei,
                yahoo_ticker AS new_ticker,
                {prio_new} AS new_prio,
                ROW_NUMBER() OVER (
                    PARTITION BY fund_lei
                    ORDER BY {prio_new}, tm.yahoo_ticker
                ) AS rn
            FROM esma_isin_ticker_map AS tm
            WHERE tm.is_tradeable = true
              AND tm.fund_lei IS NOT NULL
              AND tm.yahoo_ticker IS NOT NULL
        )
        UPDATE esma_funds AS ef
        SET yahoo_ticker = ranked.new_ticker,
            ticker_resolved_at = NOW()
        FROM ranked
        WHERE ef.lei = ranked.fund_lei
          AND ranked.rn = 1
          AND ranked.new_prio < ({prio_current})
    """)

    # Step 2: Propagate to instruments_universe (AUM worker reads this)
    op.execute("""
        UPDATE instruments_universe AS iu
        SET ticker = ef.yahoo_ticker
        FROM esma_isin_ticker_map tm
        JOIN esma_funds ef ON ef.lei = tm.fund_lei
        WHERE iu.attributes->>'fund_subtype' = 'ucits'
          AND iu.ticker = tm.yahoo_ticker
          AND tm.fund_lei IS NOT NULL
          AND iu.ticker IS DISTINCT FROM ef.yahoo_ticker
          AND NOT EXISTS (
            SELECT 1 FROM instruments_universe iu2
            WHERE iu2.ticker = ef.yahoo_ticker
          )
    """)


def downgrade() -> None:
    # Data migration — original tickers not preserved. No-op on downgrade.
    pass
