"""Convert sec_13f_holdings and sec_13f_diffs to TimescaleDB hypertables.

Full historical depth: EDGAR 13F data available from 1999 (100+ quarters).
With thousands of managers, these tables will grow to hundreds of millions
of rows. Regular PostgreSQL tables are inviable at this scale.

Hypertable partitioning by report_date (holdings) and quarter_to (diffs)
with 3-month chunk intervals aligns with quarterly filing cadence.
Compression segmented by CIK for efficient per-manager queries.

Also creates:
  - sec_13f_latest_quarter: TimescaleDB continuous aggregate for screener
  - sec_13f_manager_sector_latest: plain materialized view for top sector

Uses a separate DBAPI connection with autocommit (same pattern as
c3d4e5f6a7b8_timescaledb_hypertables_compression.py) because
create_hypertable() cannot run inside a transaction block.

NOTE: run during low-traffic window — migrate_data rewrites the entire
table and blocks writes during conversion.

depends_on: 0024 (add_sector_to_sec_13f_holdings).
"""

import os

import psycopg
from alembic import op

revision = "0025_sec_13f_hypertable"
down_revision = "0024_sec_13f_sector"
branch_labels = None
depends_on = None


def _autocommit_conninfo() -> str:
    """Resolve a psycopg-compatible connection string for autocommit DDL.

    Prefers DATABASE_URL_SYNC (explicit sync URL) over extracting DSN from
    the Alembic dbapi connection — the latter can lose SSL/connection params
    when psycopg re-parses the libpq-format DSN string.
    """
    sync_url = os.getenv("DATABASE_URL_SYNC", "")
    if sync_url:
        # Strip SQLAlchemy dialect prefix: postgresql+psycopg:// → postgresql://
        return sync_url.replace("+psycopg", "")
    # Fallback: extract from Alembic's live connection
    return op.get_bind().connection.dbapi_connection.info.dsn


def upgrade() -> None:
    # Escape Alembic's transactional DDL — hypertable conversion cannot
    # run inside a transaction block.
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        # ═══════════════════════════════════════════════════════════
        #  sec_13f_holdings → hypertable
        # ═══════════════════════════════════════════════════════════

        # Step 1: Drop existing PK (UUID-based, incompatible with hypertable
        # partitioning — TimescaleDB requires partition key in all unique
        # constraints). Also drop the unique constraint and old indexes
        # that will be recreated post-conversion.
        cursor.execute(
            "ALTER TABLE sec_13f_holdings DROP CONSTRAINT IF EXISTS sec_13f_holdings_pkey"
        )
        cursor.execute(
            "ALTER TABLE sec_13f_holdings DROP CONSTRAINT IF EXISTS uq_sec_13f_holdings_cik_date_cusip"
        )
        cursor.execute("DROP INDEX IF EXISTS idx_sec_13f_holdings_cik_report_date")
        cursor.execute("DROP INDEX IF EXISTS idx_sec_13f_holdings_cusip_report_date")
        cursor.execute("DROP INDEX IF EXISTS idx_sec_13f_holdings_sector")

        # Drop the id column — natural key (cik, report_date, cusip) is sufficient
        # and hypertable PK must include partition column.
        cursor.execute("ALTER TABLE sec_13f_holdings DROP COLUMN IF EXISTS id")

        # Step 2: Convert to hypertable
        cursor.execute(
            "SELECT create_hypertable("
            "  'sec_13f_holdings',"
            "  'report_date',"
            "  chunk_time_interval => INTERVAL '3 months',"
            "  migrate_data => true,"
            "  if_not_exists => true"
            ")"
        )

        # Step 3: Re-create PK including partition column
        cursor.execute(
            "ALTER TABLE sec_13f_holdings "
            "ADD CONSTRAINT sec_13f_holdings_pkey "
            "PRIMARY KEY (report_date, cik, cusip)"
        )

        # Step 4: Enable compression
        cursor.execute(
            "ALTER TABLE sec_13f_holdings SET ("
            "  timescaledb.compress,"
            "  timescaledb.compress_orderby = 'report_date DESC',"
            "  timescaledb.compress_segmentby = 'cik'"
            ")"
        )

        # Step 5: Auto-compress chunks older than 6 months
        cursor.execute(
            "SELECT add_compression_policy("
            "  'sec_13f_holdings', INTERVAL '6 months', if_not_exists => true"
            ")"
        )

        # Step 6: Re-create indexes optimized for hypertable
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sec_13f_holdings_cik_report_date "
            "ON sec_13f_holdings (cik, report_date DESC)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sec_13f_holdings_cusip_report_date "
            "ON sec_13f_holdings (cusip, report_date DESC) "
            "INCLUDE (cik, shares, market_value)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sec_13f_holdings_sector "
            "ON sec_13f_holdings (cik, report_date DESC, sector)"
        )

        # ═══════════════════════════════════════════════════════════
        #  sec_13f_diffs → hypertable
        # ═══════════════════════════════════════════════════════════

        cursor.execute(
            "ALTER TABLE sec_13f_diffs DROP CONSTRAINT IF EXISTS sec_13f_diffs_pkey"
        )
        cursor.execute(
            "ALTER TABLE sec_13f_diffs DROP CONSTRAINT IF EXISTS uq_sec_13f_diffs_cik_cusip_quarters"
        )
        cursor.execute("DROP INDEX IF EXISTS idx_sec_13f_diffs_cik_quarter_to")
        cursor.execute("DROP INDEX IF EXISTS idx_sec_13f_diffs_cusip_quarter_to")

        # Drop id column — natural key is (cik, cusip, quarter_from, quarter_to)
        cursor.execute("ALTER TABLE sec_13f_diffs DROP COLUMN IF EXISTS id")

        cursor.execute(
            "SELECT create_hypertable("
            "  'sec_13f_diffs',"
            "  'quarter_to',"
            "  chunk_time_interval => INTERVAL '3 months',"
            "  migrate_data => true,"
            "  if_not_exists => true"
            ")"
        )

        # PK must include partition column (quarter_to)
        cursor.execute(
            "ALTER TABLE sec_13f_diffs "
            "ADD CONSTRAINT sec_13f_diffs_pkey "
            "PRIMARY KEY (quarter_to, cik, cusip, quarter_from)"
        )

        cursor.execute(
            "ALTER TABLE sec_13f_diffs SET ("
            "  timescaledb.compress,"
            "  timescaledb.compress_orderby = 'quarter_to DESC',"
            "  timescaledb.compress_segmentby = 'cik'"
            ")"
        )

        cursor.execute(
            "SELECT add_compression_policy("
            "  'sec_13f_diffs', INTERVAL '6 months', if_not_exists => true"
            ")"
        )

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sec_13f_diffs_cik_quarter_to "
            "ON sec_13f_diffs (cik, quarter_to DESC)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sec_13f_diffs_cusip_quarter_to "
            "ON sec_13f_diffs (cusip, quarter_to DESC)"
        )

        # ═══════════════════════════════════════════════════════════
        #  sec_13f_latest_quarter — continuous aggregate for screener
        # ═══════════════════════════════════════════════════════════

        cursor.execute("""
            CREATE MATERIALIZED VIEW IF NOT EXISTS sec_13f_latest_quarter
            WITH (timescaledb.continuous) AS
            SELECT
                cik,
                time_bucket('3 months'::interval, report_date) AS quarter,
                SUM(market_value) FILTER (WHERE asset_class = 'COM')
                    AS total_equity_value,
                COUNT(DISTINCT cusip) FILTER (WHERE asset_class = 'COM')
                    AS position_count
            FROM sec_13f_holdings
            GROUP BY cik, time_bucket('3 months'::interval, report_date)
            WITH NO DATA
        """)

        cursor.execute(
            "SELECT add_continuous_aggregate_policy("
            "  'sec_13f_latest_quarter',"
            "  start_offset => INTERVAL '9 months',"
            "  end_offset => INTERVAL '1 day',"
            "  schedule_interval => INTERVAL '1 day',"
            "  if_not_exists => true"
            ")"
        )

        # ═══════════════════════════════════════════════════════════
        #  sec_13f_manager_sector_latest — plain materialized view
        #  Refresh manually after each 13F ingestion batch.
        # ═══════════════════════════════════════════════════════════

        cursor.execute("""
            CREATE MATERIALIZED VIEW IF NOT EXISTS sec_13f_manager_sector_latest AS
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
                WHERE asset_class = 'COM' AND sector IS NOT NULL
                GROUP BY cik, report_date, sector
            ) agg
            JOIN sec_13f_holdings h ON h.cik = agg.cik AND h.report_date = agg.report_date
            WHERE h.asset_class = 'COM' AND h.sector = agg.sector
            ORDER BY h.cik, agg.report_date DESC, agg.sector_value DESC
        """)

        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sec_13f_manager_sector_latest_cik "
            "ON sec_13f_manager_sector_latest (cik)"
        )

        cursor.close()


def downgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        # Drop materialized views
        cursor.execute("DROP MATERIALIZED VIEW IF EXISTS sec_13f_manager_sector_latest")
        cursor.execute("DROP MATERIALIZED VIEW IF EXISTS sec_13f_latest_quarter")

        # Remove compression policies
        cursor.execute(
            "SELECT remove_compression_policy('sec_13f_holdings', if_exists => true)"
        )
        cursor.execute(
            "SELECT remove_compression_policy('sec_13f_diffs', if_exists => true)"
        )

        # Disable compression (decompress all chunks first)
        for table in ("sec_13f_holdings", "sec_13f_diffs"):
            cursor.execute(
                f"SELECT decompress_chunk(c.chunk_name) "
                f"FROM timescaledb_information.chunks c "
                f"WHERE c.hypertable_name = '{table}' "
                f"AND c.is_compressed = true"
            )
            cursor.execute(
                f"ALTER TABLE {table} SET (timescaledb.compress = false)"
            )

        # NOTE: TimescaleDB does not support reverting a hypertable back to
        # a regular table. Tables remain hypertables after downgrade but
        # without compression. The PK/indexes remain as-is.
        # To fully revert, drop and recreate the tables (destructive).

        # Re-add id column and restore original PK structure
        # sec_13f_holdings
        cursor.execute(
            "ALTER TABLE sec_13f_holdings DROP CONSTRAINT IF EXISTS sec_13f_holdings_pkey"
        )
        cursor.execute(
            "ALTER TABLE sec_13f_holdings "
            "ADD COLUMN id uuid DEFAULT gen_random_uuid() NOT NULL"
        )
        cursor.execute(
            "ALTER TABLE sec_13f_holdings "
            "ADD CONSTRAINT sec_13f_holdings_pkey PRIMARY KEY (id)"
        )
        cursor.execute(
            "ALTER TABLE sec_13f_holdings "
            "ADD CONSTRAINT uq_sec_13f_holdings_cik_date_cusip "
            "UNIQUE (cik, report_date, cusip)"
        )

        # sec_13f_diffs
        cursor.execute(
            "ALTER TABLE sec_13f_diffs DROP CONSTRAINT IF EXISTS sec_13f_diffs_pkey"
        )
        cursor.execute(
            "ALTER TABLE sec_13f_diffs "
            "ADD COLUMN id uuid DEFAULT gen_random_uuid() NOT NULL"
        )
        cursor.execute(
            "ALTER TABLE sec_13f_diffs "
            "ADD CONSTRAINT sec_13f_diffs_pkey PRIMARY KEY (id)"
        )
        cursor.execute(
            "ALTER TABLE sec_13f_diffs "
            "ADD CONSTRAINT uq_sec_13f_diffs_cik_cusip_quarters "
            "UNIQUE (cik, cusip, quarter_from, quarter_to)"
        )

        cursor.close()
