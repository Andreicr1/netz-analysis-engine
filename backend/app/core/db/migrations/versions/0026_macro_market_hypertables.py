"""Convert macro & market data tables to TimescaleDB hypertables.

Tables: macro_data, macro_snapshots, macro_regional_snapshots, benchmark_nav.

All four are GLOBAL tables (no organization_id, no RLS).
Pure time-series data: daily FRED observations, regional macro snapshots,
and benchmark NAV series. 1-month chunk intervals, 3-month compression.

macro_data and benchmark_nav already have time columns in their PKs —
minimal restructuring needed. macro_snapshots and macro_regional_snapshots
have UUID PKs that must be restructured to include the time column.

Uses a separate DBAPI connection with autocommit because
create_hypertable() cannot run inside a transaction block.

depends_on: 0025 (sec_13f_hypertable).
"""

import os

import psycopg

from alembic import op

revision = "0026_macro_market_hypertables"
down_revision = "0025_sec_13f_hypertable"
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
        #  macro_data → hypertable
        #  PK: (series_id, obs_date) — obs_date already in PK.
        #  segmentby: series_id (one segment per FRED series).
        # ═══════════════════════════════════════════════════════════

        cursor.execute(
            "SELECT create_hypertable("
            "  'macro_data',"
            "  'obs_date',"
            "  chunk_time_interval => INTERVAL '1 month',"
            "  migrate_data => true,"
            "  if_not_exists => true"
            ")",
        )

        cursor.execute(
            "ALTER TABLE macro_data SET ("
            "  timescaledb.compress,"
            "  timescaledb.compress_orderby = 'obs_date DESC',"
            "  timescaledb.compress_segmentby = 'series_id'"
            ")",
        )

        cursor.execute(
            "SELECT add_compression_policy("
            "  'macro_data', INTERVAL '3 months', if_not_exists => true"
            ")",
        )

        # Index for querying a specific series by date range
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_macro_data_series_obs_date "
            "ON macro_data (series_id, obs_date DESC)",
        )

        # ═══════════════════════════════════════════════════════════
        #  macro_snapshots → hypertable
        #  PK: id (UUID) → restructure to (as_of_date, id).
        #  Unique: as_of_date (one snapshot per day).
        #  segmentby: none (global, ~1 row/day, no good segment col).
        # ═══════════════════════════════════════════════════════════

        # Ensure created_at NOT NULL (from _audit(), no explicit NOT NULL)
        cursor.execute(
            "UPDATE macro_snapshots SET created_at = NOW() WHERE created_at IS NULL",
        )
        cursor.execute(
            "ALTER TABLE macro_snapshots ALTER COLUMN created_at SET NOT NULL",
        )

        # Drop UUID PK — TimescaleDB requires partition key in all unique constraints
        cursor.execute(
            "ALTER TABLE macro_snapshots DROP CONSTRAINT IF EXISTS macro_snapshots_pkey",
        )

        # Drop unique on as_of_date (will be recreated — it's OK since as_of_date
        # IS the partition column so single-column unique is allowed)
        cursor.execute(
            "ALTER TABLE macro_snapshots "
            "DROP CONSTRAINT IF EXISTS macro_snapshots_as_of_date_key",
        )
        cursor.execute(
            "DROP INDEX IF EXISTS ix_macro_snapshots_as_of_date",
        )

        cursor.execute(
            "SELECT create_hypertable("
            "  'macro_snapshots',"
            "  'as_of_date',"
            "  chunk_time_interval => INTERVAL '1 month',"
            "  migrate_data => true,"
            "  if_not_exists => true"
            ")",
        )

        # New PK with partition column first (idempotent: drop first)
        cursor.execute(
            "ALTER TABLE macro_snapshots "
            "DROP CONSTRAINT IF EXISTS macro_snapshots_pkey",
        )
        cursor.execute(
            "ALTER TABLE macro_snapshots "
            "ADD CONSTRAINT macro_snapshots_pkey "
            "PRIMARY KEY (as_of_date, id)",
        )

        # Restore unique on as_of_date (partition column — allowed as single-col unique)
        cursor.execute(
            "ALTER TABLE macro_snapshots "
            "DROP CONSTRAINT IF EXISTS uq_macro_snapshots_as_of_date",
        )
        cursor.execute(
            "ALTER TABLE macro_snapshots "
            "ADD CONSTRAINT uq_macro_snapshots_as_of_date UNIQUE (as_of_date)",
        )

        cursor.execute(
            "ALTER TABLE macro_snapshots SET ("
            "  timescaledb.compress,"
            "  timescaledb.compress_orderby = 'as_of_date DESC'"
            ")",
        )

        cursor.execute(
            "SELECT add_compression_policy("
            "  'macro_snapshots', INTERVAL '3 months', if_not_exists => true"
            ")",
        )

        # ═══════════════════════════════════════════════════════════
        #  macro_regional_snapshots → hypertable
        #  PK: id (UUID) → restructure to (as_of_date, id).
        #  Unique: as_of_date (one snapshot per day).
        #  FK target: macro_reviews.snapshot_id → must be dropped.
        #  segmentby: none (global, ~1 row/day).
        # ═══════════════════════════════════════════════════════════

        # Drop inbound FK from macro_reviews (SET NULL on delete)
        cursor.execute(
            "ALTER TABLE macro_reviews "
            "DROP CONSTRAINT IF EXISTS macro_reviews_snapshot_id_fkey",
        )

        # Ensure created_at NOT NULL
        cursor.execute(
            "UPDATE macro_regional_snapshots SET created_at = NOW() WHERE created_at IS NULL",
        )
        cursor.execute(
            "ALTER TABLE macro_regional_snapshots ALTER COLUMN created_at SET NOT NULL",
        )

        cursor.execute(
            "ALTER TABLE macro_regional_snapshots "
            "DROP CONSTRAINT IF EXISTS macro_regional_snapshots_pkey",
        )
        cursor.execute(
            "ALTER TABLE macro_regional_snapshots "
            "DROP CONSTRAINT IF EXISTS macro_regional_snapshots_as_of_date_key",
        )
        cursor.execute(
            "DROP INDEX IF EXISTS ix_macro_regional_snapshots_as_of_date",
        )

        cursor.execute(
            "SELECT create_hypertable("
            "  'macro_regional_snapshots',"
            "  'as_of_date',"
            "  chunk_time_interval => INTERVAL '1 month',"
            "  migrate_data => true,"
            "  if_not_exists => true"
            ")",
        )

        cursor.execute(
            "ALTER TABLE macro_regional_snapshots "
            "DROP CONSTRAINT IF EXISTS macro_regional_snapshots_pkey",
        )
        cursor.execute(
            "ALTER TABLE macro_regional_snapshots "
            "ADD CONSTRAINT macro_regional_snapshots_pkey "
            "PRIMARY KEY (as_of_date, id)",
        )

        cursor.execute(
            "ALTER TABLE macro_regional_snapshots "
            "DROP CONSTRAINT IF EXISTS uq_macro_regional_snapshots_as_of_date",
        )
        cursor.execute(
            "ALTER TABLE macro_regional_snapshots "
            "ADD CONSTRAINT uq_macro_regional_snapshots_as_of_date "
            "UNIQUE (as_of_date)",
        )

        cursor.execute(
            "ALTER TABLE macro_regional_snapshots SET ("
            "  timescaledb.compress,"
            "  timescaledb.compress_orderby = 'as_of_date DESC'"
            ")",
        )

        cursor.execute(
            "SELECT add_compression_policy("
            "  'macro_regional_snapshots', INTERVAL '3 months', if_not_exists => true"
            ")",
        )

        # ═══════════════════════════════════════════════════════════
        #  benchmark_nav → hypertable
        #  PK: (block_id, nav_date) — nav_date already in PK.
        #  segmentby: block_id (one segment per allocation block).
        # ═══════════════════════════════════════════════════════════

        cursor.execute(
            "SELECT create_hypertable("
            "  'benchmark_nav',"
            "  'nav_date',"
            "  chunk_time_interval => INTERVAL '1 month',"
            "  migrate_data => true,"
            "  if_not_exists => true"
            ")",
        )

        cursor.execute(
            "ALTER TABLE benchmark_nav SET ("
            "  timescaledb.compress,"
            "  timescaledb.compress_orderby = 'nav_date DESC',"
            "  timescaledb.compress_segmentby = 'block_id'"
            ")",
        )

        cursor.execute(
            "SELECT add_compression_policy("
            "  'benchmark_nav', INTERVAL '3 months', if_not_exists => true"
            ")",
        )

        # Index for querying a specific block by date range
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_benchmark_nav_block_date "
            "ON benchmark_nav (block_id, nav_date DESC)",
        )

        cursor.close()


def downgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        for table in (
            "macro_data", "macro_snapshots",
            "macro_regional_snapshots", "benchmark_nav",
        ):
            cursor.execute(
                f"SELECT remove_compression_policy('{table}', if_exists => true)",
            )
            cursor.execute(
                f"SELECT decompress_chunk(c.chunk_name) "
                f"FROM timescaledb_information.chunks c "
                f"WHERE c.hypertable_name = '{table}' "
                f"AND c.is_compressed = true",
            )
            cursor.execute(
                f"ALTER TABLE {table} SET (timescaledb.compress = false)",
            )

        # NOTE: TimescaleDB does not support reverting hypertables to regular
        # tables. Tables remain hypertables after downgrade but without
        # compression. To fully revert, drop and recreate (destructive).

        # Restore macro_snapshots original PK structure
        cursor.execute(
            "ALTER TABLE macro_snapshots "
            "DROP CONSTRAINT IF EXISTS uq_macro_snapshots_as_of_date",
        )
        cursor.execute(
            "ALTER TABLE macro_snapshots DROP CONSTRAINT IF EXISTS macro_snapshots_pkey",
        )
        cursor.execute(
            "ALTER TABLE macro_snapshots "
            "ADD CONSTRAINT macro_snapshots_pkey PRIMARY KEY (id)",
        )
        cursor.execute(
            "ALTER TABLE macro_snapshots "
            "ADD CONSTRAINT macro_snapshots_as_of_date_key UNIQUE (as_of_date)",
        )

        # Restore macro_regional_snapshots original PK structure
        cursor.execute(
            "ALTER TABLE macro_regional_snapshots "
            "DROP CONSTRAINT IF EXISTS uq_macro_regional_snapshots_as_of_date",
        )
        cursor.execute(
            "ALTER TABLE macro_regional_snapshots "
            "DROP CONSTRAINT IF EXISTS macro_regional_snapshots_pkey",
        )
        cursor.execute(
            "ALTER TABLE macro_regional_snapshots "
            "ADD CONSTRAINT macro_regional_snapshots_pkey PRIMARY KEY (id)",
        )
        cursor.execute(
            "ALTER TABLE macro_regional_snapshots "
            "ADD CONSTRAINT macro_regional_snapshots_as_of_date_key UNIQUE (as_of_date)",
        )

        # Restore macro_reviews FK to macro_regional_snapshots
        cursor.execute(
            "ALTER TABLE macro_reviews "
            "ADD CONSTRAINT macro_reviews_snapshot_id_fkey "
            "FOREIGN KEY (snapshot_id) REFERENCES macro_regional_snapshots(id) "
            "ON DELETE SET NULL",
        )

        # Drop hypertable-specific indexes
        cursor.execute("DROP INDEX IF EXISTS idx_macro_data_series_obs_date")
        cursor.execute("DROP INDEX IF EXISTS idx_benchmark_nav_block_date")

        cursor.close()
