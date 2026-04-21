"""Convert verified append-only analytics tables to TimescaleDB hypertables.

Tables: deep_review_validation_runs, eval_runs, periodic_review_reports.

These three tables were deferred in 0032 pending mutability analysis.
Code audit confirmed all three are INSERT-only:

  - deep_review_validation_runs: db.add(row) in validation_runner.py:303.
    All fields populated at creation. No UPDATE code found.
  - eval_runs: db.add(run_row) in eval_runner.py:679.
    status + completed_at set at creation time (report computed before persist).
    No UPDATE code found.
  - periodic_review_reports: db.add(report) in deep_review/portfolio.py:111.
    Each review creates a new row. Latest retrieved via ORDER BY reviewed_at DESC.
    No UPDATE code found.

deep_review_validation_runs and eval_runs are GLOBAL (no org_id, no RLS).
periodic_review_reports is TENANT-SCOPED (has org_id + RLS).

1-month chunk intervals, 3-month compression for all three.

Uses a separate DBAPI connection with autocommit because
create_hypertable() cannot run inside a transaction block.

depends_on: 0032 (hypertable_skip_docs).
"""

import os

import psycopg

from alembic import op

revision = "0034_appendonly_hypertables"
down_revision = "0033_sec_cusip_ticker_map"
branch_labels = None
depends_on = None


def _autocommit_conninfo() -> str:
    """Resolve a psycopg-compatible connection string for autocommit DDL."""
    sync_url = os.getenv("DATABASE_URL_SYNC", "")
    if sync_url:
        return sync_url.replace("+psycopg", "")
    return op.get_bind().connection.dbapi_connection.info.dsn


def _is_hypertable(cursor, table: str) -> bool:
    """Check if table is already a TimescaleDB hypertable (idempotent guard)."""
    cursor.execute(
        "SELECT 1 FROM timescaledb_information.hypertables "
        "WHERE hypertable_name = %s", (table,),
    )
    return cursor.fetchone() is not None


def _ensure_not_null(cursor, table: str, column: str) -> None:
    """Backfill NULLs and set NOT NULL for hypertable partition column."""
    cursor.execute(
        f"UPDATE {table} SET {column} = NOW() WHERE {column} IS NULL",
    )
    cursor.execute(
        f"ALTER TABLE {table} ALTER COLUMN {column} SET NOT NULL",
    )


def upgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        # ═══════════════════════════════════════════════════════════
        #  deep_review_validation_runs → hypertable
        #  PK: id (UUID) → (created_at, id).
        #  GLOBAL table (no org_id, no RLS).
        #  segmentby: none (global, low volume).
        # ═══════════════════════════════════════════════════════════

        if not _is_hypertable(cursor, "deep_review_validation_runs"):
            _ensure_not_null(cursor, "deep_review_validation_runs", "created_at")

            cursor.execute(
                "ALTER TABLE deep_review_validation_runs "
                "DROP CONSTRAINT IF EXISTS deep_review_validation_runs_pkey",
            )
            cursor.execute(
                "DROP INDEX IF EXISTS ix_validation_runs_run_deal",
            )

            cursor.execute(
                "SELECT create_hypertable("
                "  'deep_review_validation_runs', 'created_at',"
                "  chunk_time_interval => INTERVAL '1 month',"
                "  migrate_data => true, if_not_exists => true)",
            )

            cursor.execute(
                "ALTER TABLE deep_review_validation_runs "
                "DROP CONSTRAINT IF EXISTS deep_review_validation_runs_pkey",
            )
            cursor.execute(
                "ALTER TABLE deep_review_validation_runs "
                "ADD CONSTRAINT deep_review_validation_runs_pkey "
                "PRIMARY KEY (created_at, id)",
            )

            cursor.execute(
                "ALTER TABLE deep_review_validation_runs SET ("
                "  timescaledb.compress,"
                "  timescaledb.compress_orderby = 'created_at DESC')",
            )

            cursor.execute(
                "SELECT add_compression_policy("
                "  'deep_review_validation_runs', INTERVAL '3 months',"
                "  if_not_exists => true)",
            )

            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_validation_runs_run_deal "
                "ON deep_review_validation_runs (run_id, deal_id, created_at DESC)",
            )

        # ═══════════════════════════════════════════════════════════
        #  eval_runs → hypertable
        #  PK: id (UUID) → (started_at, id).
        #  Time column: started_at (NOT NULL).
        #  GLOBAL table (no org_id, no RLS).
        #  Unique: run_id → must include partition col.
        #  segmentby: none (global, low volume).
        # ═══════════════════════════════════════════════════════════

        if not _is_hypertable(cursor, "eval_runs"):
            cursor.execute(
                "ALTER TABLE eval_runs "
                "DROP CONSTRAINT IF EXISTS eval_runs_pkey",
            )
            # Drop unique index on run_id (needs partition column)
            cursor.execute("DROP INDEX IF EXISTS ix_eval_runs_run_id")
            cursor.execute("DROP INDEX IF EXISTS ix_eval_runs_fund_started")

            cursor.execute(
                "SELECT create_hypertable("
                "  'eval_runs', 'started_at',"
                "  chunk_time_interval => INTERVAL '1 month',"
                "  migrate_data => true, if_not_exists => true)",
            )

            cursor.execute(
                "ALTER TABLE eval_runs "
                "DROP CONSTRAINT IF EXISTS eval_runs_pkey",
            )
            cursor.execute(
                "ALTER TABLE eval_runs "
                "ADD CONSTRAINT eval_runs_pkey "
                "PRIMARY KEY (started_at, id)",
            )

            # Recreate unique index with partition column
            cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_eval_runs_run_id "
                "ON eval_runs (started_at, run_id)",
            )

            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_eval_runs_fund_started "
                "ON eval_runs (fund_id, started_at DESC)",
            )

            cursor.execute(
                "ALTER TABLE eval_runs SET ("
                "  timescaledb.compress,"
                "  timescaledb.compress_orderby = 'started_at DESC')",
            )

            cursor.execute(
                "SELECT add_compression_policy("
                "  'eval_runs', INTERVAL '3 months',"
                "  if_not_exists => true)",
            )

        # ═══════════════════════════════════════════════════════════
        #  periodic_review_reports → hypertable
        #  PK: id (UUID) → (created_at, id).
        #  TENANT-SCOPED (has org_id + RLS) → drop RLS before DML.
        #  segmentby: fund_id
        # ═══════════════════════════════════════════════════════════

        if not _is_hypertable(cursor, "periodic_review_reports"):
            # Drop RLS before any DML (policy references app.current_organization_id)
            cursor.execute("DROP POLICY IF EXISTS org_isolation ON periodic_review_reports")
            cursor.execute("ALTER TABLE periodic_review_reports NO FORCE ROW LEVEL SECURITY")
            cursor.execute("ALTER TABLE periodic_review_reports DISABLE ROW LEVEL SECURITY")

            _ensure_not_null(cursor, "periodic_review_reports", "created_at")

            cursor.execute(
                "ALTER TABLE periodic_review_reports "
                "DROP CONSTRAINT IF EXISTS periodic_review_reports_pkey",
            )
            cursor.execute(
                "DROP INDEX IF EXISTS ix_periodic_reviews_fund_investment",
            )

            cursor.execute(
                "SELECT create_hypertable("
                "  'periodic_review_reports', 'created_at',"
                "  chunk_time_interval => INTERVAL '1 month',"
                "  migrate_data => true, if_not_exists => true)",
            )

            cursor.execute(
                "ALTER TABLE periodic_review_reports "
                "DROP CONSTRAINT IF EXISTS periodic_review_reports_pkey",
            )
            cursor.execute(
                "ALTER TABLE periodic_review_reports "
                "ADD CONSTRAINT periodic_review_reports_pkey "
                "PRIMARY KEY (created_at, id)",
            )

            cursor.execute(
                "ALTER TABLE periodic_review_reports SET ("
                "  timescaledb.compress,"
                "  timescaledb.compress_orderby = 'created_at DESC',"
                "  timescaledb.compress_segmentby = 'fund_id')",
            )

            cursor.execute(
                "SELECT add_compression_policy("
                "  'periodic_review_reports', INTERVAL '3 months',"
                "  if_not_exists => true)",
            )

            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_periodic_reviews_fund_investment "
                "ON periodic_review_reports (fund_id, investment_id, created_at DESC)",
            )

        cursor.close()


def downgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        for table in (
            "deep_review_validation_runs", "eval_runs",
            "periodic_review_reports",
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

        # NOTE: Tables remain hypertables. Full revert requires drop + recreate.

        # Restore original PKs
        for table in (
            "deep_review_validation_runs", "eval_runs",
            "periodic_review_reports",
        ):
            cursor.execute(
                f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_pkey",
            )
            cursor.execute(
                f"ALTER TABLE {table} ADD CONSTRAINT {table}_pkey PRIMARY KEY (id)",
            )

        # Restore eval_runs unique index on run_id (without partition col)
        cursor.execute("DROP INDEX IF EXISTS idx_eval_runs_run_id")
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_eval_runs_run_id "
            "ON eval_runs (run_id)",
        )

        # Restore original indexes
        cursor.execute("DROP INDEX IF EXISTS idx_validation_runs_run_deal")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_validation_runs_run_deal "
            "ON deep_review_validation_runs (run_id, deal_id)",
        )

        cursor.execute("DROP INDEX IF EXISTS idx_eval_runs_fund_started")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_eval_runs_fund_started "
            "ON eval_runs (fund_id, started_at)",
        )

        cursor.execute("DROP INDEX IF EXISTS idx_periodic_reviews_fund_investment")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_periodic_reviews_fund_investment "
            "ON periodic_review_reports (fund_id, investment_id)",
        )

        cursor.close()
