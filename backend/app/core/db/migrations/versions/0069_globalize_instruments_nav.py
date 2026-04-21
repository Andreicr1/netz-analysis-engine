"""Globalize instruments_universe and nav_timeseries.

Removes organization_id, block_id, approval_status from instruments_universe.
Removes organization_id from nav_timeseries.
Drops RLS policies from both tables.
Rebuilds nav_monthly_returns_agg continuous aggregate without organization_id.

Revision ID: 0069
Revises: 0068_instruments_org
"""

import os

import psycopg

from alembic import op

revision = "0069_globalize_instruments_nav"
down_revision = "0068_instruments_org"
branch_labels = None
depends_on = None


def _autocommit_conninfo() -> str:
    """Resolve a psycopg-compatible connection string for autocommit DDL."""
    sync_url = os.getenv("DATABASE_URL_SYNC", "")
    if sync_url:
        return sync_url.replace("+psycopg", "")
    return op.get_bind().connection.dbapi_connection.info.dsn


def upgrade() -> None:
    # ── instruments_universe: remove org-scoped columns + RLS ──────────

    # Drop RLS policy and disable
    op.execute("DROP POLICY IF EXISTS instruments_universe_rls ON instruments_universe")
    op.execute("DROP POLICY IF EXISTS instruments_universe_isolation ON instruments_universe")
    op.execute("ALTER TABLE instruments_universe DISABLE ROW LEVEL SECURITY")

    # Deduplicate: if same ticker exists for multiple orgs, keep first
    # (instruments_org already has the org links from migration 0068)
    op.execute("""
        DELETE FROM instruments_universe a
        USING instruments_universe b
        WHERE a.instrument_id > b.instrument_id
          AND a.ticker IS NOT NULL
          AND a.ticker = b.ticker
    """)

    # Drop org-scoped columns (CASCADE drops dependent indexes/constraints)
    op.execute("DROP INDEX IF EXISTS ix_instruments_universe_organization_id")
    op.execute("ALTER TABLE instruments_universe DROP COLUMN IF EXISTS organization_id CASCADE")
    op.execute("ALTER TABLE instruments_universe DROP COLUMN IF EXISTS block_id CASCADE")
    op.execute("ALTER TABLE instruments_universe DROP COLUMN IF EXISTS approval_status CASCADE")

    # ── nav_timeseries: remove organization_id ─────────────────────────

    # 1. Drop the continuous aggregate that references organization_id
    #    (nav_monthly_returns_agg was created in migration 0049 with GROUP BY organization_id)
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        # Remove continuous aggregate policy + view (with retry for scheduler race)
        for _attempt in range(3):
            try:
                cursor.execute("""
                    SELECT remove_continuous_aggregate_policy('nav_monthly_returns_agg', if_exists => true)
                """)
                cursor.execute("DROP MATERIALIZED VIEW IF EXISTS nav_monthly_returns_agg CASCADE")
                break
            except psycopg.errors.InternalError_:
                import time
                time.sleep(1)

    # 2. Disable compression on the hypertable before ALTER TABLE ops
    op.execute("""
        DO $$
        BEGIN
            PERFORM remove_compression_policy('nav_timeseries', if_exists => true);
        EXCEPTION WHEN OTHERS THEN
            NULL;
        END $$
    """)
    op.execute("""
        DO $$
        BEGIN
            PERFORM decompress_chunk(c, if_compressed => true)
            FROM show_chunks('nav_timeseries') c;
        EXCEPTION WHEN OTHERS THEN
            NULL;
        END $$
    """)
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE nav_timeseries SET (timescaledb.compress = false);
        EXCEPTION WHEN OTHERS THEN
            NULL;
        END $$
    """)

    # 3. Drop RLS
    op.execute("DROP POLICY IF EXISTS nav_timeseries_rls ON nav_timeseries")
    op.execute("DROP POLICY IF EXISTS nav_timeseries_isolation ON nav_timeseries")
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE nav_timeseries DISABLE ROW LEVEL SECURITY;
        EXCEPTION WHEN OTHERS THEN
            NULL;
        END $$
    """)

    # 4. Drop organization_id column (no CASCADE needed — continuous agg already dropped)
    op.execute("DROP INDEX IF EXISTS ix_nav_timeseries_organization_id")
    op.execute("ALTER TABLE nav_timeseries DROP COLUMN IF EXISTS organization_id")

    # 5. Re-enable compression with instrument_id as segmentby
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE nav_timeseries SET (
                timescaledb.compress,
                timescaledb.compress_segmentby = 'instrument_id'
            );
        EXCEPTION WHEN OTHERS THEN
            NULL;
        END $$
    """)
    op.execute("""
        DO $$
        BEGIN
            PERFORM add_compression_policy('nav_timeseries', INTERVAL '3 months', if_not_exists => true);
        EXCEPTION WHEN OTHERS THEN
            NULL;
        END $$
    """)

    # 6. Recreate nav_monthly_returns_agg WITHOUT organization_id
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "CREATE MATERIALIZED VIEW IF NOT EXISTS nav_monthly_returns_agg "
            "WITH (timescaledb.continuous) AS "
            "SELECT "
            "  instrument_id, "
            "  time_bucket('1 month', nav_date) AS month, "
            "  SUM(return_1d) AS compound_log_return, "
            "  (EXP(SUM(return_1d)) - 1) AS compound_return, "
            "  COUNT(*) AS trading_days, "
            "  MIN(nav) AS min_nav, "
            "  MAX(nav) AS max_nav "
            "FROM nav_timeseries "
            "WHERE return_1d IS NOT NULL "
            "GROUP BY instrument_id, "
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


def downgrade() -> None:
    raise NotImplementedError("Downgrade not supported — data loss risk")
