"""Convert sec_institutional_allocations to TimescaleDB hypertable.

sec_13f_holdings and sec_13f_diffs were already converted to hypertables
in migration 0025 (sec_13f_hypertable), along with the continuous
aggregate sec_13f_latest_quarter and materialized view
sec_13f_manager_sector_latest. This migration only converts the
remaining SEC time-series table.

sec_institutional_allocations: 13F reverse lookup (who holds what).
GLOBAL table — no organization_id, no RLS.
Partitioned by report_date (quarterly filings), 3-month chunks,
6-month compression segmented by filer_cik.

Uses a separate DBAPI connection with autocommit because
create_hypertable() cannot run inside a transaction block.

depends_on: 0027 (nav_portfolio_hypertables).
"""

import os

import psycopg
from alembic import op

revision = "0028_sec_inst_hypertable"
down_revision = "0027_nav_portfolio_hypertables"
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

        # ═══════════════════════════════════════════════════════════
        #  sec_institutional_allocations → hypertable
        #  PK: id (UUID) → restructure to (report_date, id).
        #  Unique: (filer_cik, report_date, target_cusip) — already
        #    includes report_date (partition column).
        #  segmentby: filer_cik
        # ═══════════════════════════════════════════════════════════

        # Step 1: Drop UUID PK
        cursor.execute(
            "ALTER TABLE sec_institutional_allocations "
            "DROP CONSTRAINT IF EXISTS sec_institutional_allocations_pkey"
        )

        # Step 2: Drop unique constraint (will be recreated — already
        # includes report_date, so it's TimescaleDB-compatible)
        cursor.execute(
            "ALTER TABLE sec_institutional_allocations "
            "DROP CONSTRAINT IF EXISTS uq_sec_institutional_allocations_filer_date_cusip"
        )

        # Step 3: Drop existing indexes that will be recreated
        cursor.execute(
            "DROP INDEX IF EXISTS idx_sec_institutional_allocations_target"
        )
        cursor.execute(
            "DROP INDEX IF EXISTS idx_sec_institutional_allocations_filer"
        )

        # Step 4: Drop id column — natural key is sufficient
        cursor.execute(
            "ALTER TABLE sec_institutional_allocations DROP COLUMN IF EXISTS id"
        )

        # Step 5: Convert to hypertable
        cursor.execute(
            "SELECT create_hypertable("
            "  'sec_institutional_allocations',"
            "  'report_date',"
            "  chunk_time_interval => INTERVAL '3 months',"
            "  migrate_data => true,"
            "  if_not_exists => true"
            ")"
        )

        # Step 6: New PK with partition column
        cursor.execute(
            "ALTER TABLE sec_institutional_allocations "
            "ADD CONSTRAINT sec_institutional_allocations_pkey "
            "PRIMARY KEY (report_date, filer_cik, target_cusip)"
        )

        # Step 7: Enable compression
        cursor.execute(
            "ALTER TABLE sec_institutional_allocations SET ("
            "  timescaledb.compress,"
            "  timescaledb.compress_orderby = 'report_date DESC',"
            "  timescaledb.compress_segmentby = 'filer_cik'"
            ")"
        )

        cursor.execute(
            "SELECT add_compression_policy("
            "  'sec_institutional_allocations', INTERVAL '6 months',"
            "  if_not_exists => true"
            ")"
        )

        # Step 8: Recreate indexes optimized for hypertable
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sec_inst_alloc_target_report "
            "ON sec_institutional_allocations (target_cusip, report_date DESC) "
            "INCLUDE (filer_cik, filer_name, filer_type, market_value, shares)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sec_inst_alloc_filer_report "
            "ON sec_institutional_allocations (filer_cik, report_date DESC)"
        )

        cursor.close()


def downgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        # Remove compression
        cursor.execute(
            "SELECT remove_compression_policy("
            "  'sec_institutional_allocations', if_exists => true"
            ")"
        )
        cursor.execute(
            "SELECT decompress_chunk(c.chunk_name) "
            "FROM timescaledb_information.chunks c "
            "WHERE c.hypertable_name = 'sec_institutional_allocations' "
            "AND c.is_compressed = true"
        )
        cursor.execute(
            "ALTER TABLE sec_institutional_allocations "
            "SET (timescaledb.compress = false)"
        )

        # NOTE: Table remains hypertable. Full revert requires drop + recreate.

        # Restore id column and original PK structure
        cursor.execute(
            "ALTER TABLE sec_institutional_allocations "
            "DROP CONSTRAINT IF EXISTS sec_institutional_allocations_pkey"
        )
        cursor.execute(
            "ALTER TABLE sec_institutional_allocations "
            "ADD COLUMN id uuid DEFAULT gen_random_uuid() NOT NULL"
        )
        cursor.execute(
            "ALTER TABLE sec_institutional_allocations "
            "ADD CONSTRAINT sec_institutional_allocations_pkey PRIMARY KEY (id)"
        )
        cursor.execute(
            "ALTER TABLE sec_institutional_allocations "
            "ADD CONSTRAINT uq_sec_institutional_allocations_filer_date_cusip "
            "UNIQUE (filer_cik, report_date, target_cusip)"
        )

        # Drop hypertable-specific indexes
        cursor.execute("DROP INDEX IF EXISTS idx_sec_inst_alloc_target_report")
        cursor.execute("DROP INDEX IF EXISTS idx_sec_inst_alloc_filer_report")

        # Restore original indexes
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sec_institutional_allocations_target "
            "ON sec_institutional_allocations "
            "(target_cusip, report_date DESC) "
            "INCLUDE (filer_cik, filer_name, filer_type, market_value, shares)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sec_institutional_allocations_filer "
            "ON sec_institutional_allocations (filer_cik, report_date)"
        )

        cursor.close()
