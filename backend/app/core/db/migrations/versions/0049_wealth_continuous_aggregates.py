"""Wealth continuous aggregates for pre-computed monthly returns.

Creates two TimescaleDB continuous aggregates:
  - nav_monthly_returns_agg: compound monthly returns per instrument/org
  - benchmark_monthly_returns_agg: compound monthly returns per benchmark block

Uses a separate DBAPI connection with autocommit because
continuous aggregate DDL cannot run inside a transaction block.

depends_on: 0048 (wealth_analytics_indexes).
"""

import os

import psycopg

from alembic import op

revision = "0049_wealth_continuous_aggregates"
down_revision = "0048_wealth_analytics_indexes"
branch_labels = None
depends_on = None


def _autocommit_conninfo() -> str:
    """Resolve a psycopg-compatible connection string for autocommit DDL."""
    sync_url = os.getenv("DATABASE_URL_SYNC", "")
    if sync_url:
        return sync_url.replace("+psycopg", "")
    return op.get_bind().connection.dbapi_connection.info.dsn


def upgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        # ── nav_monthly_returns_agg ───────────────────────────────
        cursor.execute(
            "CREATE MATERIALIZED VIEW IF NOT EXISTS nav_monthly_returns_agg "
            "WITH (timescaledb.continuous) AS "
            "SELECT "
            "  instrument_id, "
            "  organization_id, "
            "  time_bucket('1 month', nav_date) AS month, "
            "  SUM(return_1d) AS compound_log_return, "
            "  (EXP(SUM(return_1d)) - 1) AS compound_return, "
            "  COUNT(*) AS trading_days, "
            "  MIN(nav) AS min_nav, "
            "  MAX(nav) AS max_nav "
            "FROM nav_timeseries "
            "WHERE return_1d IS NOT NULL "
            "GROUP BY instrument_id, organization_id, "
            "  time_bucket('1 month', nav_date) "
            "WITH NO DATA",
        )

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_nav_monthly_returns_agg_inst_month "
            "ON nav_monthly_returns_agg (instrument_id, month DESC)",
        )

        cursor.execute(
            "SELECT add_continuous_aggregate_policy("
            "  'nav_monthly_returns_agg', "
            "  start_offset => INTERVAL '3 months', "
            "  end_offset => INTERVAL '1 day', "
            "  schedule_interval => INTERVAL '1 day', "
            "  if_not_exists => true"
            ")",
        )

        # ── benchmark_monthly_returns_agg ─────────────────────────
        cursor.execute(
            "CREATE MATERIALIZED VIEW IF NOT EXISTS benchmark_monthly_returns_agg "
            "WITH (timescaledb.continuous) AS "
            "SELECT "
            "  block_id, "
            "  time_bucket('1 month', nav_date) AS month, "
            "  SUM(return_1d) AS compound_log_return, "
            "  (EXP(SUM(return_1d)) - 1) AS compound_return, "
            "  COUNT(*) AS trading_days "
            "FROM benchmark_nav "
            "WHERE return_1d IS NOT NULL "
            "GROUP BY block_id, "
            "  time_bucket('1 month', nav_date) "
            "WITH NO DATA",
        )

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_benchmark_monthly_returns_agg_block_month "
            "ON benchmark_monthly_returns_agg (block_id, month DESC)",
        )

        cursor.execute(
            "SELECT add_continuous_aggregate_policy("
            "  'benchmark_monthly_returns_agg', "
            "  start_offset => INTERVAL '3 months', "
            "  end_offset => INTERVAL '1 day', "
            "  schedule_interval => INTERVAL '1 day', "
            "  if_not_exists => true"
            ")",
        )

        # ── Seed initial data ─────────────────────────────────────
        cursor.execute(
            "CALL refresh_continuous_aggregate("
            "  'nav_monthly_returns_agg', NULL, NULL"
            ")",
        )
        cursor.execute(
            "CALL refresh_continuous_aggregate("
            "  'benchmark_monthly_returns_agg', NULL, NULL"
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
            "  'benchmark_monthly_returns_agg', if_not_exists => true"
            ")",
        )
        cursor.execute(
            "SELECT remove_continuous_aggregate_policy("
            "  'nav_monthly_returns_agg', if_not_exists => true"
            ")",
        )

        cursor.execute(
            "DROP MATERIALIZED VIEW IF EXISTS benchmark_monthly_returns_agg CASCADE",
        )
        cursor.execute(
            "DROP MATERIALIZED VIEW IF EXISTS nav_monthly_returns_agg CASCADE",
        )

        cursor.close()
