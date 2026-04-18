"""PR-A20 Section A — canonical catalog backfill for 4 missing tickers.

PR-A19.1 migration 0146 backfilled only 6 of 10 canonical liquid-beta
tickers into ``instruments_org`` because the other 4 (IVV, BND, TLT,
SHY) were absent from the upstream ``instruments_universe`` catalog.
Universe sync populates the catalog from SEC filings, and these four
happen to be outside that discovery path (direct issuer ETFs not
indexed by the current sec_etfs/sec_registered_funds joins).

This migration inserts the 4 missing tickers directly with attribute
metadata sufficient to satisfy the ``chk_fund_attrs`` CHECK and the
downstream optimizer pipeline. Source is flagged ``pr_a20_backfill``
for audit.

NAV history (required by the optimizer) is NOT populated here — the
``instrument_ingestion`` worker (lock 900_010) pulls OHLC from the
configured provider for every active ticker in ``instruments_universe``
on its daily schedule. A one-off trigger script lives at
``backend/scripts/pr_a20_trigger_canonical_ingestion.py``.

Idempotent: ``WHERE NOT EXISTS`` guards each row, so re-running the
migration is a no-op.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0147_canonical_catalog_backfill"
down_revision = "0146_canonical_liquid_beta_backfill"
branch_labels = None
depends_on = None


# Seed rows for tickers that universe_sync does not reliably discover.
# inception_date and manager_name are required by chk_fund_attrs on
# instruments_universe (fund type). aum_usd is seeded at a conservative
# floor — the next universe_sync run will overwrite these attributes
# once upstream SEC catalogs index the ticker.
_CANONICAL_SEED: list[dict[str, str]] = [
    {
        "ticker": "IVV",
        "name": "iShares Core S&P 500 ETF",
        "asset_class": "equity",
        "manager_name": "BlackRock Fund Advisors",
        "inception_date": "2000-05-15",
    },
    {
        "ticker": "BND",
        "name": "Vanguard Total Bond Market ETF",
        "asset_class": "fixed_income",
        "manager_name": "Vanguard Group",
        "inception_date": "2007-04-03",
    },
    {
        "ticker": "TLT",
        "name": "iShares 20+ Year Treasury Bond ETF",
        "asset_class": "fixed_income",
        "manager_name": "BlackRock Fund Advisors",
        "inception_date": "2002-07-22",
    },
    {
        "ticker": "SHY",
        "name": "iShares 1-3 Year Treasury Bond ETF",
        "asset_class": "fixed_income",
        "manager_name": "BlackRock Fund Advisors",
        "inception_date": "2002-07-22",
    },
]


def upgrade() -> None:
    conn = op.get_bind()

    insert_sql = sa.text(
        """
        INSERT INTO instruments_universe (
            instrument_id, instrument_type, name, ticker,
            asset_class, geography, currency, is_active, attributes
        )
        SELECT
            gen_random_uuid(),
            'fund',
            :name,
            :ticker,
            :asset_class,
            'north_america',
            'USD',
            true,
            jsonb_build_object(
                'manager_name', :manager_name,
                'inception_date', :inception_date,
                'aum_usd', 0,
                'sec_universe', 'etf',
                'fund_subtype', 'etf',
                'source', 'pr_a20_backfill'
            )
        WHERE NOT EXISTS (
            SELECT 1 FROM instruments_universe iu
            WHERE iu.ticker = :ticker
        )
        """
    )

    for row in _CANONICAL_SEED:
        conn.execute(insert_sql, row)


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM instruments_universe
        WHERE attributes->>'source' = 'pr_a20_backfill'
        """
    )
