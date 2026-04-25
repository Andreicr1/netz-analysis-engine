"""Convert risk & covenant register tables to TimescaleDB hypertables.

Tables: covenant_status_register, investment_risk_registry, deal_risk_flags.

All three are TENANT-SCOPED tables with RLS.
Risk assessment records that accumulate over time.
1-month chunk intervals, 3-month compression.

Uses a separate DBAPI connection with autocommit because
create_hypertable() cannot run inside a transaction block.

depends_on: 0030 (audit_event_hypertables).
"""

import os

import psycopg
from alembic import op

revision = "0031_risk_covenant_hypertables"
down_revision = "0030_audit_event_hypertables"
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


def _ensure_created_at_not_null(cursor, table: str) -> None:
    """Backfill NULLs and set NOT NULL on created_at for hypertable conversion."""
    cursor.execute(
        f"UPDATE {table} SET created_at = NOW() WHERE created_at IS NULL",
    )
    cursor.execute(
        f"ALTER TABLE {table} ALTER COLUMN created_at SET NOT NULL",
    )


def upgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        # ═══════════════════════════════════════════════════════════
        #  covenant_status_register → hypertable
        #  PK: id (UUID) → (created_at, id).
        #  segmentby: investment_id
        # ═══════════════════════════════════════════════════════════
        if not _is_hypertable(cursor, "covenant_status_register"):
            # RLS incompatible with TimescaleDB columnstore — drop policies + disable.
            # Must happen BEFORE any DML (e.g. _ensure_created_at_not_null) because
            # RLS policies reference app.current_organization_id which isn't set during migrations.
            cursor.execute("DROP POLICY IF EXISTS org_isolation ON covenant_status_register")
            cursor.execute("ALTER TABLE covenant_status_register NO FORCE ROW LEVEL SECURITY")
            cursor.execute("ALTER TABLE covenant_status_register DISABLE ROW LEVEL SECURITY")
            _ensure_created_at_not_null(cursor, "covenant_status_register")

            cursor.execute(
                "ALTER TABLE covenant_status_register "
                "DROP CONSTRAINT IF EXISTS covenant_status_register_pkey",
            )
            cursor.execute(
                "DROP INDEX IF EXISTS ix_covenant_status_register_fund_investment",
            )

            cursor.execute(
                "SELECT create_hypertable("
                "  'covenant_status_register',"
                "  'created_at',"
                "  chunk_time_interval => INTERVAL '1 month',"
                "  migrate_data => true,"
                "  if_not_exists => true"
                ")",
            )

            cursor.execute(
                "ALTER TABLE covenant_status_register "
                "ADD CONSTRAINT covenant_status_register_pkey "
                "PRIMARY KEY (created_at, id)",
            )

            cursor.execute(
                "ALTER TABLE covenant_status_register SET ("
                "  timescaledb.compress,"
                "  timescaledb.compress_orderby = 'created_at DESC',"
                "  timescaledb.compress_segmentby = 'investment_id'"
                ")",
            )

            cursor.execute(
                "SELECT add_compression_policy("
                "  'covenant_status_register', INTERVAL '3 months',"
                "  if_not_exists => true"
                ")",
            )

            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_covenant_status_fund_investment "
                "ON covenant_status_register (fund_id, investment_id, created_at DESC)",
            )

        # ═══════════════════════════════════════════════════════════
        #  investment_risk_registry → hypertable
        #  PK: id (UUID) → (created_at, id).
        #  segmentby: investment_id
        # ═══════════════════════════════════════════════════════════
        if not _is_hypertable(cursor, "investment_risk_registry"):
            # RLS incompatible with TimescaleDB columnstore — drop policies + disable.
            # Must happen BEFORE any DML (e.g. _ensure_created_at_not_null) because
            # RLS policies reference app.current_organization_id which isn't set during migrations.
            cursor.execute("DROP POLICY IF EXISTS org_isolation ON investment_risk_registry")
            cursor.execute("ALTER TABLE investment_risk_registry NO FORCE ROW LEVEL SECURITY")
            cursor.execute("ALTER TABLE investment_risk_registry DISABLE ROW LEVEL SECURITY")
            _ensure_created_at_not_null(cursor, "investment_risk_registry")

            cursor.execute(
                "ALTER TABLE investment_risk_registry "
                "DROP CONSTRAINT IF EXISTS investment_risk_registry_pkey",
            )
            cursor.execute(
                "DROP INDEX IF EXISTS ix_investment_risk_registry_fund_investment",
            )

            cursor.execute(
                "SELECT create_hypertable("
                "  'investment_risk_registry',"
                "  'created_at',"
                "  chunk_time_interval => INTERVAL '1 month',"
                "  migrate_data => true,"
                "  if_not_exists => true"
                ")",
            )

            cursor.execute(
                "ALTER TABLE investment_risk_registry "
                "ADD CONSTRAINT investment_risk_registry_pkey "
                "PRIMARY KEY (created_at, id)",
            )

            cursor.execute(
                "ALTER TABLE investment_risk_registry SET ("
                "  timescaledb.compress,"
                "  timescaledb.compress_orderby = 'created_at DESC',"
                "  timescaledb.compress_segmentby = 'investment_id'"
                ")",
            )

            cursor.execute(
                "SELECT add_compression_policy("
                "  'investment_risk_registry', INTERVAL '3 months',"
                "  if_not_exists => true"
                ")",
            )

            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_investment_risk_fund_investment "
                "ON investment_risk_registry (fund_id, investment_id, created_at DESC)",
            )

        # ═══════════════════════════════════════════════════════════
        #  deal_risk_flags → hypertable
        #  PK: id (UUID) → (created_at, id).
        #  segmentby: deal_id
        # ═══════════════════════════════════════════════════════════
        if not _is_hypertable(cursor, "deal_risk_flags"):
            # RLS incompatible with TimescaleDB columnstore — drop policies + disable.
            # Must happen BEFORE any DML (e.g. _ensure_created_at_not_null) because
            # RLS policies reference app.current_organization_id which isn't set during migrations.
            cursor.execute("DROP POLICY IF EXISTS org_isolation ON deal_risk_flags")
            cursor.execute("ALTER TABLE deal_risk_flags NO FORCE ROW LEVEL SECURITY")
            cursor.execute("ALTER TABLE deal_risk_flags DISABLE ROW LEVEL SECURITY")
            _ensure_created_at_not_null(cursor, "deal_risk_flags")

            cursor.execute(
                "ALTER TABLE deal_risk_flags "
                "DROP CONSTRAINT IF EXISTS deal_risk_flags_pkey",
            )
            cursor.execute("DROP INDEX IF EXISTS ix_deal_risk_flags_fund_deal")

            cursor.execute(
                "SELECT create_hypertable("
                "  'deal_risk_flags',"
                "  'created_at',"
                "  chunk_time_interval => INTERVAL '1 month',"
                "  migrate_data => true,"
                "  if_not_exists => true"
                ")",
            )

            cursor.execute(
                "ALTER TABLE deal_risk_flags "
                "ADD CONSTRAINT deal_risk_flags_pkey "
                "PRIMARY KEY (created_at, id)",
            )

            cursor.execute(
                "ALTER TABLE deal_risk_flags SET ("
                "  timescaledb.compress,"
                "  timescaledb.compress_orderby = 'created_at DESC',"
                "  timescaledb.compress_segmentby = 'deal_id'"
                ")",
            )

            cursor.execute(
                "SELECT add_compression_policy("
                "  'deal_risk_flags', INTERVAL '3 months', if_not_exists => true"
                ")",
            )

            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_deal_risk_flags_fund_deal "
                "ON deal_risk_flags (fund_id, deal_id, created_at DESC)",
            )

        cursor.close()


def downgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        tables = [
            "covenant_status_register", "investment_risk_registry",
            "deal_risk_flags",
        ]

        for table in tables:
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
        for table in tables:
            cursor.execute(
                f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_pkey",
            )
            cursor.execute(
                f"ALTER TABLE {table} ADD CONSTRAINT {table}_pkey PRIMARY KEY (id)",
            )

        # Drop hypertable-specific indexes and restore originals
        cursor.execute("DROP INDEX IF EXISTS idx_covenant_status_fund_investment")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_covenant_status_register_fund_investment "
            "ON covenant_status_register (fund_id, investment_id)",
        )

        cursor.execute("DROP INDEX IF EXISTS idx_investment_risk_fund_investment")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_investment_risk_registry_fund_investment "
            "ON investment_risk_registry (fund_id, investment_id)",
        )

        cursor.execute("DROP INDEX IF EXISTS idx_deal_risk_flags_fund_deal")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_deal_risk_flags_fund_deal "
            "ON deal_risk_flags (fund_id, deal_id)",
        )

        cursor.close()
