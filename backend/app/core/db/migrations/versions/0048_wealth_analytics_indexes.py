"""Add performance indexes for wealth analytics routes.

Covers:
- nav_timeseries: covering index for correlation/attribution, RLS optimization
- fund_risk_metrics: latest metric per instrument, RLS + instrument, scoring ranking
- model_portfolios: live portfolio lookup
- strategic_allocation: temporal range scan for attribution
- benchmark_nav: per-block date range for attribution
- dd_reports: current report lookup
- dd_chapters: chapter listing ordered by report

Hypertable indexes use transaction_per_chunk (requires autocommit connection).
Non-hypertable indexes use standard op.execute().

depends_on: 0047 (screener_redesign_indexes).
"""

import os

import psycopg
from alembic import op

revision = "0048_wealth_analytics_indexes"
down_revision = "0047_screener_redesign_indexes"
branch_labels = None
depends_on = None


def _autocommit_conninfo() -> str:
    """Resolve a psycopg-compatible connection string for autocommit DDL."""
    sync_url = os.getenv("DATABASE_URL_SYNC", "")
    if sync_url:
        return sync_url.replace("+psycopg", "")
    return op.get_bind().connection.dbapi_connection.info.dsn


def upgrade() -> None:
    # ── Non-hypertable indexes (standard transaction) ──────────────

    # model_portfolios: live portfolio lookup (correlation, attribution, track record)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_model_portfolios_profile_live
        ON model_portfolios (profile)
        WHERE status = 'live'
    """)

    # strategic_allocation: temporal range scan for attribution
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_strategic_alloc_profile_dates
        ON strategic_allocation (profile, effective_from, effective_to)
    """)

    # dd_reports: current report lookup (1 row per instrument)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_dd_reports_instrument_current
        ON dd_reports (instrument_id, organization_id)
        WHERE is_current = true
    """)

    # dd_chapters: chapter listing ordered by report
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_dd_chapters_report_order
        ON dd_chapters (dd_report_id, chapter_order)
    """)

    # ── Hypertable indexes (require autocommit for transaction_per_chunk) ──

    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        # nav_timeseries: covering index for correlation/attribution (index-only scan)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS ix_nav_ts_instrument_date_return
            ON nav_timeseries (instrument_id, nav_date)
            INCLUDE (return_1d)
            WITH (timescaledb.transaction_per_chunk)
        """)

        # nav_timeseries: RLS optimization (org_id + instrument for filtered scans)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS ix_nav_ts_org_instrument
            ON nav_timeseries (organization_id, instrument_id)
            WITH (timescaledb.transaction_per_chunk)
        """)

        # fund_risk_metrics: latest metric per instrument (DISTINCT ON optimization)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS ix_fund_risk_instrument_date_desc
            ON fund_risk_metrics (instrument_id, calc_date DESC)
            WITH (timescaledb.transaction_per_chunk)
        """)

        # fund_risk_metrics: RLS + instrument + latest
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS ix_fund_risk_org_instrument_date
            ON fund_risk_metrics (organization_id, instrument_id, calc_date DESC)
            WITH (timescaledb.transaction_per_chunk)
        """)

        # fund_risk_metrics: scoring ranking
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS ix_fund_risk_score
            ON fund_risk_metrics (manager_score DESC NULLS LAST)
            WITH (timescaledb.transaction_per_chunk)
            WHERE manager_score IS NOT NULL
        """)

        # benchmark_nav: per-block date range for attribution
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS ix_benchmark_nav_block_date
            ON benchmark_nav (block_id, nav_date)
            WITH (timescaledb.transaction_per_chunk)
        """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_dd_chapters_report_order")
    op.execute("DROP INDEX IF EXISTS ix_dd_reports_instrument_current")
    op.execute("DROP INDEX IF EXISTS ix_strategic_alloc_profile_dates")
    op.execute("DROP INDEX IF EXISTS ix_model_portfolios_profile_live")

    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()
        cursor.execute("DROP INDEX IF EXISTS ix_benchmark_nav_block_date")
        cursor.execute("DROP INDEX IF EXISTS ix_fund_risk_score")
        cursor.execute("DROP INDEX IF EXISTS ix_fund_risk_org_instrument_date")
        cursor.execute("DROP INDEX IF EXISTS ix_fund_risk_instrument_date_desc")
        cursor.execute("DROP INDEX IF EXISTS ix_nav_ts_org_instrument")
        cursor.execute("DROP INDEX IF EXISTS ix_nav_ts_instrument_date_return")
