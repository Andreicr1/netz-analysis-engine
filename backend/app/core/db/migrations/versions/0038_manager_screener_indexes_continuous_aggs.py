"""Manager Screener indexes + continuous aggregates.

Adds indexes on sec_managers for AUM-sorted queries and compliance filtering.
Creates two TimescaleDB continuous aggregates for pre-computed quarterly data:
  - sec_13f_holdings_agg: sector allocation + position count per CIK/quarter
  - sec_13f_drift_agg: churn count + total changes per CIK/quarter

GLOBAL TABLES: No organization_id, no RLS.
Continuous aggregates use materialized_only=true (SEC 13F data is quarterly).
Refresh policies run daily to capture new filings.

Uses a separate DBAPI connection with autocommit because
continuous aggregate DDL cannot run inside a transaction block.

depends_on: 0037 (ofr_hedge_fund_hypertable).
"""

import os

import psycopg

from alembic import op

revision = "0038_mgr_screener_idx_aggs"
down_revision = "0037_ofr_hedge_fund_hypertable"
branch_labels = None
depends_on = None


def _autocommit_conninfo() -> str:
    """Resolve a psycopg-compatible connection string for autocommit DDL."""
    sync_url = os.getenv("DATABASE_URL_SYNC", "")
    if sync_url:
        return sync_url.replace("+psycopg", "")
    return op.get_bind().connection.dbapi_connection.info.dsn


def upgrade() -> None:
    # ── 1. Indexes on sec_managers ──────────────────────────────
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sec_managers_aum "
        "ON sec_managers (aum_total DESC)",
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sec_managers_compliance_aum "
        "ON sec_managers (compliance_disclosures, aum_total DESC)",
    )

    # ── 2. Continuous aggregates (require autocommit) ───────────
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        # ── sec_13f_holdings_agg ────────────────────────────────
        cursor.execute(
            "CREATE MATERIALIZED VIEW IF NOT EXISTS sec_13f_holdings_agg "
            "WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS "
            "SELECT cik, "
            "  time_bucket('3 months'::interval, report_date) AS quarter, "
            "  sector, "
            "  SUM(market_value) AS sector_value, "
            "  COUNT(DISTINCT cusip) AS position_count "
            "FROM sec_13f_holdings "
            "WHERE asset_class = 'Shares' "
            "GROUP BY cik, time_bucket('3 months'::interval, report_date), sector "
            "WITH NO DATA",
        )

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sec_13f_holdings_agg_cik_quarter "
            "ON sec_13f_holdings_agg (cik, quarter DESC)",
        )

        cursor.execute(
            "SELECT add_continuous_aggregate_policy("
            "  'sec_13f_holdings_agg', "
            "  start_offset => INTERVAL '2 years', "
            "  end_offset => INTERVAL '1 day', "
            "  schedule_interval => INTERVAL '1 day', "
            "  if_not_exists => true"
            ")",
        )

        # ── sec_13f_drift_agg ───────────────────────────────────
        cursor.execute(
            "CREATE MATERIALIZED VIEW IF NOT EXISTS sec_13f_drift_agg "
            "WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS "
            "SELECT cik, "
            "  time_bucket('3 months'::interval, quarter_to) AS quarter, "
            "  COUNT(*) FILTER (WHERE action IN ('NEW_POSITION','EXITED')) AS churn_count, "
            "  COUNT(*) AS total_changes "
            "FROM sec_13f_diffs "
            "GROUP BY cik, time_bucket('3 months'::interval, quarter_to) "
            "WITH NO DATA",
        )

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sec_13f_drift_agg_cik_quarter "
            "ON sec_13f_drift_agg (cik, quarter DESC)",
        )

        cursor.execute(
            "SELECT add_continuous_aggregate_policy("
            "  'sec_13f_drift_agg', "
            "  start_offset => INTERVAL '2 years', "
            "  end_offset => INTERVAL '1 day', "
            "  schedule_interval => INTERVAL '1 day', "
            "  if_not_exists => true"
            ")",
        )

        # ── 3. Seed initial data ────────────────────────────────
        cursor.execute(
            "CALL refresh_continuous_aggregate("
            "  'sec_13f_holdings_agg', NULL, NULL"
            ")",
        )
        cursor.execute(
            "CALL refresh_continuous_aggregate("
            "  'sec_13f_drift_agg', NULL, NULL"
            ")",
        )

        cursor.close()


def downgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        # Remove refresh policies before dropping views
        cursor.execute(
            "SELECT remove_continuous_aggregate_policy("
            "  'sec_13f_drift_agg', if_not_exists => true"
            ")",
        )
        cursor.execute(
            "SELECT remove_continuous_aggregate_policy("
            "  'sec_13f_holdings_agg', if_not_exists => true"
            ")",
        )

        cursor.execute("DROP MATERIALIZED VIEW IF EXISTS sec_13f_drift_agg CASCADE")
        cursor.execute("DROP MATERIALIZED VIEW IF EXISTS sec_13f_holdings_agg CASCADE")

        cursor.close()

    op.execute("DROP INDEX IF EXISTS idx_sec_managers_compliance_aum")
    op.execute("DROP INDEX IF EXISTS idx_sec_managers_aum")
