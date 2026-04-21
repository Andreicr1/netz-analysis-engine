"""Convert audit & event log tables to TimescaleDB hypertables.

Tables: audit_events, deal_events, pipeline_deal_stage_history,
        deal_conversion_events, cash_impact_flags.

All five are TENANT-SCOPED, append-only event logs.
1-week chunk intervals for high write frequency + recent-window queries.
1-month compression (events are immutable after creation).

audit_events (from 0019) is the highest-volume table — all entity CRUD
operations across all modules. 1-week chunks ensure chunk pruning for
the common "last 7/30/90 days" query patterns.

Uses a separate DBAPI connection with autocommit because
create_hypertable() cannot run inside a transaction block.

depends_on: 0029 (drift_alert_hypertables).
"""

import os

import psycopg

from alembic import op

revision = "0030_audit_event_hypertables"
down_revision = "0029_drift_alert_hypertables"
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
        #  audit_events → hypertable
        #  PK: id (UUID) → (created_at, id).
        #  Composite index: (organization_id, entity_type, created_at)
        #    — already includes partition column.
        #  segmentby: organization_id
        # ═══════════════════════════════════════════════════════════
        if not _is_hypertable(cursor, "audit_events"):
            # RLS incompatible with TimescaleDB columnstore — drop policies + disable.
            # Must happen BEFORE any DML (e.g. _ensure_created_at_not_null) because
            # RLS policies reference app.current_organization_id which isn't set during migrations.
            cursor.execute("DROP POLICY IF EXISTS org_isolation ON audit_events")
            cursor.execute("ALTER TABLE audit_events NO FORCE ROW LEVEL SECURITY")
            cursor.execute("ALTER TABLE audit_events DISABLE ROW LEVEL SECURITY")
            _ensure_created_at_not_null(cursor, "audit_events")

            cursor.execute(
                "ALTER TABLE audit_events DROP CONSTRAINT IF EXISTS audit_events_pkey",
            )
            # Drop composite index — will be recreated post-conversion
            cursor.execute(
                "DROP INDEX IF EXISTS ix_audit_events_org_entity_created",
            )

            cursor.execute(
                "SELECT create_hypertable("
                "  'audit_events',"
                "  'created_at',"
                "  chunk_time_interval => INTERVAL '1 week',"
                "  migrate_data => true,"
                "  if_not_exists => true"
                ")",
            )

            cursor.execute(
                "ALTER TABLE audit_events "
                "ADD CONSTRAINT audit_events_pkey "
                "PRIMARY KEY (created_at, id)",
            )

            cursor.execute(
                "ALTER TABLE audit_events SET ("
                "  timescaledb.compress,"
                "  timescaledb.compress_orderby = 'created_at DESC',"
                "  timescaledb.compress_segmentby = 'organization_id'"
                ")",
            )

            cursor.execute(
                "SELECT add_compression_policy("
                "  'audit_events', INTERVAL '1 month', if_not_exists => true"
                ")",
            )

            # Recreate composite index (already TimescaleDB-compatible)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_events_org_entity_created "
                "ON audit_events (organization_id, entity_type, created_at DESC)",
            )

        # ═══════════════════════════════════════════════════════════
        #  deal_events → hypertable
        #  PK: id (UUID) → (created_at, id).
        #  segmentby: fund_id (always NOT NULL, more selective than org)
        # ═══════════════════════════════════════════════════════════
        if not _is_hypertable(cursor, "deal_events"):
            # RLS incompatible with TimescaleDB columnstore — drop policies + disable.
            # Must happen BEFORE any DML (e.g. _ensure_created_at_not_null) because
            # RLS policies reference app.current_organization_id which isn't set during migrations.
            cursor.execute("DROP POLICY IF EXISTS org_isolation ON deal_events")
            cursor.execute("ALTER TABLE deal_events NO FORCE ROW LEVEL SECURITY")
            cursor.execute("ALTER TABLE deal_events DISABLE ROW LEVEL SECURITY")
            _ensure_created_at_not_null(cursor, "deal_events")

            cursor.execute(
                "ALTER TABLE deal_events DROP CONSTRAINT IF EXISTS deal_events_pkey",
            )
            cursor.execute("DROP INDEX IF EXISTS ix_deal_events_fund_type")
            cursor.execute("DROP INDEX IF EXISTS ix_deal_events_created")

            cursor.execute(
                "SELECT create_hypertable("
                "  'deal_events',"
                "  'created_at',"
                "  chunk_time_interval => INTERVAL '1 week',"
                "  migrate_data => true,"
                "  if_not_exists => true"
                ")",
            )

            cursor.execute(
                "ALTER TABLE deal_events "
                "ADD CONSTRAINT deal_events_pkey "
                "PRIMARY KEY (created_at, id)",
            )

            cursor.execute(
                "ALTER TABLE deal_events SET ("
                "  timescaledb.compress,"
                "  timescaledb.compress_orderby = 'created_at DESC',"
                "  timescaledb.compress_segmentby = 'fund_id'"
                ")",
            )

            cursor.execute(
                "SELECT add_compression_policy("
                "  'deal_events', INTERVAL '1 month', if_not_exists => true"
                ")",
            )

            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_deal_events_fund_type "
                "ON deal_events (fund_id, event_type, created_at DESC)",
            )

        # ═══════════════════════════════════════════════════════════
        #  pipeline_deal_stage_history → hypertable
        #  PK: id (UUID) → (changed_at, id).
        #  Time column: changed_at (NOT NULL, server_default now()).
        #  segmentby: deal_id
        # ═══════════════════════════════════════════════════════════
        if not _is_hypertable(cursor, "pipeline_deal_stage_history"):
            # RLS incompatible with TimescaleDB columnstore — drop policies + disable.
            # Must happen BEFORE migrate_data which may trigger RLS evaluation.
            cursor.execute("DROP POLICY IF EXISTS org_isolation ON pipeline_deal_stage_history")
            cursor.execute("ALTER TABLE pipeline_deal_stage_history NO FORCE ROW LEVEL SECURITY")
            cursor.execute("ALTER TABLE pipeline_deal_stage_history DISABLE ROW LEVEL SECURITY")
            cursor.execute(
                "ALTER TABLE pipeline_deal_stage_history "
                "DROP CONSTRAINT IF EXISTS pipeline_deal_stage_history_pkey",
            )

            cursor.execute(
                "SELECT create_hypertable("
                "  'pipeline_deal_stage_history',"
                "  'changed_at',"
                "  chunk_time_interval => INTERVAL '1 week',"
                "  migrate_data => true,"
                "  if_not_exists => true"
                ")",
            )

            cursor.execute(
                "ALTER TABLE pipeline_deal_stage_history "
                "ADD CONSTRAINT pipeline_deal_stage_history_pkey "
                "PRIMARY KEY (changed_at, id)",
            )

            cursor.execute(
                "ALTER TABLE pipeline_deal_stage_history SET ("
                "  timescaledb.compress,"
                "  timescaledb.compress_orderby = 'changed_at DESC',"
                "  timescaledb.compress_segmentby = 'deal_id'"
                ")",
            )

            cursor.execute(
                "SELECT add_compression_policy("
                "  'pipeline_deal_stage_history', INTERVAL '1 month',"
                "  if_not_exists => true"
                ")",
            )

            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_pipeline_stage_history_deal "
                "ON pipeline_deal_stage_history (deal_id, changed_at DESC)",
            )

        # ═══════════════════════════════════════════════════════════
        #  deal_conversion_events → hypertable
        #  PK: id (UUID) → (created_at, id).
        #  segmentby: fund_id
        # ═══════════════════════════════════════════════════════════
        if not _is_hypertable(cursor, "deal_conversion_events"):
            # RLS incompatible with TimescaleDB columnstore — drop policies + disable.
            # Must happen BEFORE any DML (e.g. _ensure_created_at_not_null) because
            # RLS policies reference app.current_organization_id which isn't set during migrations.
            cursor.execute("DROP POLICY IF EXISTS org_isolation ON deal_conversion_events")
            cursor.execute("ALTER TABLE deal_conversion_events NO FORCE ROW LEVEL SECURITY")
            cursor.execute("ALTER TABLE deal_conversion_events DISABLE ROW LEVEL SECURITY")
            _ensure_created_at_not_null(cursor, "deal_conversion_events")

            cursor.execute(
                "ALTER TABLE deal_conversion_events "
                "DROP CONSTRAINT IF EXISTS deal_conversion_events_pkey",
            )
            cursor.execute(
                "DROP INDEX IF EXISTS ix_deal_conversion_events_fund_created",
            )

            cursor.execute(
                "SELECT create_hypertable("
                "  'deal_conversion_events',"
                "  'created_at',"
                "  chunk_time_interval => INTERVAL '1 week',"
                "  migrate_data => true,"
                "  if_not_exists => true"
                ")",
            )

            cursor.execute(
                "ALTER TABLE deal_conversion_events "
                "ADD CONSTRAINT deal_conversion_events_pkey "
                "PRIMARY KEY (created_at, id)",
            )

            cursor.execute(
                "ALTER TABLE deal_conversion_events SET ("
                "  timescaledb.compress,"
                "  timescaledb.compress_orderby = 'created_at DESC',"
                "  timescaledb.compress_segmentby = 'fund_id'"
                ")",
            )

            cursor.execute(
                "SELECT add_compression_policy("
                "  'deal_conversion_events', INTERVAL '1 month',"
                "  if_not_exists => true"
                ")",
            )

            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_deal_conversion_events_fund "
                "ON deal_conversion_events (fund_id, created_at DESC)",
            )

        # ═══════════════════════════════════════════════════════════
        #  cash_impact_flags → hypertable
        #  PK: id (UUID) → (created_at, id).
        #  segmentby: investment_id
        # ═══════════════════════════════════════════════════════════
        if not _is_hypertable(cursor, "cash_impact_flags"):
            # RLS incompatible with TimescaleDB columnstore — drop policies + disable.
            # Must happen BEFORE any DML (e.g. _ensure_created_at_not_null) because
            # RLS policies reference app.current_organization_id which isn't set during migrations.
            cursor.execute("DROP POLICY IF EXISTS org_isolation ON cash_impact_flags")
            cursor.execute("ALTER TABLE cash_impact_flags NO FORCE ROW LEVEL SECURITY")
            cursor.execute("ALTER TABLE cash_impact_flags DISABLE ROW LEVEL SECURITY")
            _ensure_created_at_not_null(cursor, "cash_impact_flags")

            cursor.execute(
                "ALTER TABLE cash_impact_flags "
                "DROP CONSTRAINT IF EXISTS cash_impact_flags_pkey",
            )
            cursor.execute(
                "DROP INDEX IF EXISTS ix_cash_impact_flags_fund_investment",
            )

            cursor.execute(
                "SELECT create_hypertable("
                "  'cash_impact_flags',"
                "  'created_at',"
                "  chunk_time_interval => INTERVAL '1 week',"
                "  migrate_data => true,"
                "  if_not_exists => true"
                ")",
            )

            cursor.execute(
                "ALTER TABLE cash_impact_flags "
                "ADD CONSTRAINT cash_impact_flags_pkey "
                "PRIMARY KEY (created_at, id)",
            )

            cursor.execute(
                "ALTER TABLE cash_impact_flags SET ("
                "  timescaledb.compress,"
                "  timescaledb.compress_orderby = 'created_at DESC',"
                "  timescaledb.compress_segmentby = 'investment_id'"
                ")",
            )

            cursor.execute(
                "SELECT add_compression_policy("
                "  'cash_impact_flags', INTERVAL '1 month', if_not_exists => true"
                ")",
            )

            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_cash_impact_flags_fund_investment "
                "ON cash_impact_flags (fund_id, investment_id, created_at DESC)",
            )

        cursor.close()


def downgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        tables = [
            "audit_events", "deal_events", "pipeline_deal_stage_history",
            "deal_conversion_events", "cash_impact_flags",
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
        for table in (
            "audit_events", "deal_events", "deal_conversion_events",
            "cash_impact_flags",
        ):
            cursor.execute(
                f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_pkey",
            )
            cursor.execute(
                f"ALTER TABLE {table} ADD CONSTRAINT {table}_pkey PRIMARY KEY (id)",
            )

        # pipeline_deal_stage_history uses changed_at
        cursor.execute(
            "ALTER TABLE pipeline_deal_stage_history "
            "DROP CONSTRAINT IF EXISTS pipeline_deal_stage_history_pkey",
        )
        cursor.execute(
            "ALTER TABLE pipeline_deal_stage_history "
            "ADD CONSTRAINT pipeline_deal_stage_history_pkey PRIMARY KEY (id)",
        )

        # Drop hypertable-specific indexes and restore originals
        cursor.execute("DROP INDEX IF EXISTS idx_audit_events_org_entity_created")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_audit_events_org_entity_created "
            "ON audit_events (organization_id, entity_type, created_at)",
        )

        cursor.execute("DROP INDEX IF EXISTS idx_deal_events_fund_type")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_deal_events_fund_type "
            "ON deal_events (fund_id, event_type)",
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_deal_events_created "
            "ON deal_events (created_at)",
        )

        cursor.execute("DROP INDEX IF EXISTS idx_pipeline_stage_history_deal")

        cursor.execute("DROP INDEX IF EXISTS idx_deal_conversion_events_fund")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_deal_conversion_events_fund_created "
            "ON deal_conversion_events (fund_id, created_at)",
        )

        cursor.execute("DROP INDEX IF EXISTS idx_cash_impact_flags_fund_investment")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_cash_impact_flags_fund_investment "
            "ON cash_impact_flags (fund_id, investment_id)",
        )

        cursor.close()
