"""Matview mv_nport_sector_attribution — holdings-based attribution aggregate.

Cenário A per the 2026-04-20 N-PORT GICS coverage diagnostic:
    sector fill rate 99.91%, no sic_code column on sec_nport_holdings,
    so migration 0133 (sic_gics_mapping) is skipped. COALESCE path uses
    the post-enrichment sector column with asset_class as secondary
    fallback and 'Unclassified' as terminal label.

Column reconciliation (spec → actual sec_nport_holdings):
    filer_cik        → cik
    period_of_report → report_date
    industry_sector  → sector
    issuer_category  → asset_class
    value_usd        → market_value

Matview + UNIQUE INDEX required for REFRESH CONCURRENTLY. Refresh is
triggered from nport_ingestion worker AFTER the advisory lock 900_018
releases (see data-layer spec §3.2).

depends_on: 0162 (Robust Sharpe cols).
"""

from __future__ import annotations

import os

import psycopg

from alembic import op

revision = "0163_mv_nport_sector_attribution"
down_revision = "0162_add_sharpe_cf_cols"
branch_labels = None
depends_on = None


def _autocommit_conninfo() -> str:
    sync_url = os.getenv("DATABASE_URL_SYNC", "")
    if sync_url:
        return sync_url.replace("+psycopg", "")
    return op.get_bind().connection.dbapi_connection.info.dsn


_MV_DDL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_nport_sector_attribution AS
SELECT
    h.cik                                                        AS filer_cik,
    h.report_date                                                AS period_of_report,
    COALESCE(NULLIF(btrim(h.asset_class), ''), 'Unknown')        AS issuer_category,
    COALESCE(
        NULLIF(btrim(h.sector), ''),
        NULLIF(btrim(h.asset_class), ''),
        'Unclassified'
    )                                                            AS industry_sector,
    SUM(h.market_value)::NUMERIC                                 AS aum_usd,
    CASE
        WHEN SUM(SUM(h.market_value)) OVER (
                PARTITION BY h.cik, h.report_date
             ) > 0
        THEN SUM(h.market_value)::NUMERIC
             / NULLIF(SUM(SUM(h.market_value)) OVER (
                    PARTITION BY h.cik, h.report_date
               ), 0)
        ELSE 0
    END                                                          AS weight,
    COUNT(*)                                                     AS holdings_count,
    MAX(h.created_at)                                            AS last_updated_at
FROM sec_nport_holdings h
WHERE h.market_value IS NOT NULL AND h.market_value > 0
GROUP BY 1, 2, 3, 4
WITH NO DATA
"""

_UQ_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_nport_sector_attribution
    ON mv_nport_sector_attribution (filer_cik, period_of_report, issuer_category, industry_sector)
"""

_PERIOD_INDEX = """
CREATE INDEX IF NOT EXISTS ix_mv_nport_sector_attribution_period
    ON mv_nport_sector_attribution (period_of_report DESC)
"""

_CIK_PERIOD_INDEX = """
CREATE INDEX IF NOT EXISTS ix_mv_nport_sector_attribution_cik_period
    ON mv_nport_sector_attribution (filer_cik, period_of_report DESC)
"""


def upgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute(_MV_DDL)
        cur.execute(_UQ_INDEX)
        cur.execute(_PERIOD_INDEX)
        cur.execute(_CIK_PERIOD_INDEX)
        # Initial populate (blocking — first run only; subsequent refreshes
        # are CONCURRENTLY from the ingestion worker).
        cur.execute("REFRESH MATERIALIZED VIEW mv_nport_sector_attribution")
        cur.close()


def downgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute("DROP INDEX IF EXISTS ix_mv_nport_sector_attribution_cik_period")
        cur.execute("DROP INDEX IF EXISTS ix_mv_nport_sector_attribution_period")
        cur.execute("DROP INDEX IF EXISTS ux_mv_nport_sector_attribution")
        cur.execute("DROP MATERIALIZED VIEW IF EXISTS mv_nport_sector_attribution")
        cur.close()
