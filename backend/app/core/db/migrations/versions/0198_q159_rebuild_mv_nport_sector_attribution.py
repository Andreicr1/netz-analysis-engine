"""Rebuild mv_nport_sector_attribution on cik_padded for consistent 10-digit joins.

WMJ-006: original matview projected h.cik (mixed-length 4-10 digits), causing
join failures with instrument_identity.cik_padded. This migration rebuilds
the matview using h.cik_padded (trigger-maintained 10-digit) from migration 0179.

depends_on: 0197_q140_cascade_status_mandate_infeasible
"""
from __future__ import annotations

import os

import psycopg
from alembic import op

revision = "0198_q159_rebuild_mv_nport_sector_attribution"
down_revision = "0197_q140_cascade_status_mandate_infeasible"
branch_labels = None
depends_on = None


def _autocommit_conninfo() -> str:
    sync_url = os.getenv("DATABASE_URL_SYNC", "")
    if sync_url:
        return sync_url.replace("+psycopg", "")
    return op.get_bind().connection.dbapi_connection.info.dsn


_DROP_OLD = """
DROP INDEX IF EXISTS ix_mv_nport_sector_attribution_cik_period;
DROP INDEX IF EXISTS ix_mv_nport_sector_attribution_period;
DROP INDEX IF EXISTS ux_mv_nport_sector_attribution;
DROP MATERIALIZED VIEW IF EXISTS mv_nport_sector_attribution;
"""

_MV_DDL = """
CREATE MATERIALIZED VIEW mv_nport_sector_attribution AS
SELECT
    h.cik_padded                                                 AS filer_cik,
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
                PARTITION BY h.cik_padded, h.report_date
             ) > 0
        THEN SUM(h.market_value)::NUMERIC
             / NULLIF(SUM(SUM(h.market_value)) OVER (
                    PARTITION BY h.cik_padded, h.report_date
               ), 0)
        ELSE 0
    END                                                          AS weight,
    COUNT(*)                                                     AS holdings_count,
    MAX(h.created_at)                                            AS last_updated_at
FROM sec_nport_holdings h
WHERE h.market_value IS NOT NULL
  AND h.market_value > 0
  AND h.cik_padded IS NOT NULL
GROUP BY 1, 2, 3, 4
WITH DATA
"""

_UQ_INDEX = """
CREATE UNIQUE INDEX ux_mv_nport_sector_attribution
    ON mv_nport_sector_attribution (filer_cik, period_of_report, issuer_category, industry_sector)
"""

_PERIOD_INDEX = """
CREATE INDEX ix_mv_nport_sector_attribution_period
    ON mv_nport_sector_attribution (period_of_report DESC)
"""

_CIK_PERIOD_INDEX = """
CREATE INDEX ix_mv_nport_sector_attribution_cik_period
    ON mv_nport_sector_attribution (filer_cik, period_of_report DESC)
"""

# Downgrade: rebuild original unpadded version
_MV_DDL_OLD = """
CREATE MATERIALIZED VIEW mv_nport_sector_attribution AS
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
WITH DATA
"""


def upgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute(_DROP_OLD)
        cur.execute(_MV_DDL)
        cur.execute(_UQ_INDEX)
        cur.execute(_PERIOD_INDEX)
        cur.execute(_CIK_PERIOD_INDEX)
        cur.close()


def downgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute(_DROP_OLD)
        cur.execute(_MV_DDL_OLD)
        cur.execute(_UQ_INDEX)
        cur.execute(_PERIOD_INDEX)
        cur.execute(_CIK_PERIOD_INDEX)
        cur.close()
