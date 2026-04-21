"""Fix sec_13f_manager_sector_latest MV (was never populated) and add
_cusip_resolve_queue indexes for the new cusip_resolution worker.

The MV was created in 0025 with IF NOT EXISTS but the initial data load
produced an empty view. DROP + CREATE with data fixes the stale state.
REFRESH CONCURRENTLY then works correctly for ongoing maintenance.

Revision ID: 0085_fix_13f_sector_mv_and_cusip_queue
Revises: 0084_fund_type_indexes_crd_linkage
Create Date: 2026-04-05 14:00:00.000000
"""
from collections.abc import Sequence

import psycopg

from alembic import op

revision: str = "0085_fix_13f_sector_mv_and_cusip_queue"
down_revision: str | None = "0084_fund_type_indexes_crd_linkage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _autocommit_conninfo() -> str:
    """Get a conninfo string for direct psycopg connection (MV ops need autocommit)."""
    bind = op.get_bind()
    url = bind.engine.url
    return (
        f"host={url.host} port={url.port or 5432} "
        f"dbname={url.database} user={url.username} "
        f"password={url.password}"
    )


def upgrade() -> None:
    # MV operations require autocommit (cannot run inside Alembic transaction)
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        # ── 1. Recreate sec_13f_manager_sector_latest with data ──
        cursor.execute(
            "DROP MATERIALIZED VIEW IF EXISTS sec_13f_manager_sector_latest"
        )

        cursor.execute("""
            CREATE MATERIALIZED VIEW sec_13f_manager_sector_latest AS
            SELECT DISTINCT ON (h.cik)
                h.cik,
                h.report_date,
                h.sector,
                agg.sector_value,
                agg.sector_weight
            FROM (
                SELECT
                    cik,
                    report_date,
                    sector,
                    SUM(market_value) AS sector_value,
                    SUM(market_value)::float /
                        NULLIF(SUM(SUM(market_value)) OVER (PARTITION BY cik, report_date), 0)
                        AS sector_weight
                FROM sec_13f_holdings
                WHERE asset_class = 'Shares' AND sector IS NOT NULL
                GROUP BY cik, report_date, sector
            ) agg
            JOIN sec_13f_holdings h
                ON h.cik = agg.cik
                AND h.report_date = agg.report_date
            WHERE h.asset_class = 'Shares'
              AND h.sector = agg.sector
            ORDER BY h.cik, agg.report_date DESC, agg.sector_value DESC
        """)

        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "idx_sec_13f_manager_sector_latest_cik "
            "ON sec_13f_manager_sector_latest (cik)"
        )

        cursor.close()

    # ── 2. Ensure _cusip_resolve_queue has proper indexes ──
    # The queue table is created lazily by the cusip_resolution worker
    # the first time it runs; on a fresh CI database the table does not
    # yet exist, so the bare CREATE INDEX would fail with UndefinedTable.
    # Wrap in a DO block that only creates the index when the table is
    # already there. Idempotent and safe across both fresh and live DBs.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_tables
                WHERE tablename = '_cusip_resolve_queue'
            ) THEN
                CREATE INDEX IF NOT EXISTS idx_cusip_resolve_queue_issuer
                ON _cusip_resolve_queue (issuer_name)
                WHERE issuer_name IS NOT NULL;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_cusip_resolve_queue_issuer")
    # MV will be left as-is (non-destructive downgrade)
