"""Convert drift & alert signal tables to TimescaleDB hypertables.

Tables: performance_drift_flags, strategy_drift_alerts,
        governance_alerts, pipeline_alerts.

All four are TENANT-SCOPED tables with RLS.
Signal tables that accumulate detected events over time.
1-month chunk intervals, 3-month compression.

strategy_drift_alerts has a partial unique index
(organization_id, instrument_id) WHERE is_current = true —
must be recreated to include the partition column (detected_at).

governance_alerts has a unique index (fund_id, alert_id) —
must be recreated to include the partition column (created_at).

Uses a separate DBAPI connection with autocommit because
create_hypertable() cannot run inside a transaction block.

depends_on: 0028 (sec_institutional_hypertable).
"""

import os

import psycopg
from alembic import op

revision = "0029_drift_alert_hypertables"
down_revision = "0028_sec_inst_hypertable"
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
        "WHERE hypertable_name = %s", (table,)
    )
    return cursor.fetchone() is not None


def _ensure_created_at_not_null(cursor, table: str) -> None:
    """Backfill NULLs and set NOT NULL on created_at for hypertable conversion."""
    cursor.execute(
        f"UPDATE {table} SET created_at = NOW() WHERE created_at IS NULL"
    )
    cursor.execute(
        f"ALTER TABLE {table} ALTER COLUMN created_at SET NOT NULL"
    )


def upgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        # ═══════════════════════════════════════════════════════════
        #  performance_drift_flags → hypertable
        #  PK: id (UUID) → (created_at, id).
        #  segmentby: fund_id
        # ═══════════════════════════════════════════════════════════

        if not _is_hypertable(cursor, "performance_drift_flags"):
            # RLS incompatible with TimescaleDB columnstore — drop policies + disable.
            # Must happen BEFORE any DML (e.g. _ensure_created_at_not_null) because
            # RLS policies reference app.current_organization_id which isn't set during migrations.
            cursor.execute("DROP POLICY IF EXISTS org_isolation ON performance_drift_flags")
            cursor.execute("ALTER TABLE performance_drift_flags NO FORCE ROW LEVEL SECURITY")
            cursor.execute("ALTER TABLE performance_drift_flags DISABLE ROW LEVEL SECURITY")
            _ensure_created_at_not_null(cursor, "performance_drift_flags")
            cursor.execute(
                "ALTER TABLE performance_drift_flags "
                "DROP CONSTRAINT IF EXISTS performance_drift_flags_pkey"
            )
            cursor.execute(
                "DROP INDEX IF EXISTS ix_performance_drift_flags_fund_investment"
            )
            cursor.execute(
                "SELECT create_hypertable("
                "  'performance_drift_flags', 'created_at',"
                "  chunk_time_interval => INTERVAL '1 month',"
                "  migrate_data => true, if_not_exists => true)"
            )
            cursor.execute(
                "ALTER TABLE performance_drift_flags "
                "DROP CONSTRAINT IF EXISTS performance_drift_flags_pkey"
            )
            cursor.execute(
                "ALTER TABLE performance_drift_flags "
                "ADD CONSTRAINT performance_drift_flags_pkey "
                "PRIMARY KEY (created_at, id)"
            )
            cursor.execute(
                "ALTER TABLE performance_drift_flags SET ("
                "  timescaledb.compress,"
                "  timescaledb.compress_orderby = 'created_at DESC',"
                "  timescaledb.compress_segmentby = 'fund_id')"
            )
            cursor.execute(
                "SELECT add_compression_policy("
                "  'performance_drift_flags', INTERVAL '3 months',"
                "  if_not_exists => true)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_perf_drift_flags_fund_investment "
                "ON performance_drift_flags (fund_id, investment_id, created_at DESC)"
            )

        # ═══════════════════════════════════════════════════════════
        #  strategy_drift_alerts → hypertable
        #  PK: id (UUID) → (detected_at, id).
        #  Time column: detected_at (NOT NULL from 0014).
        #  Partial unique: (organization_id, instrument_id) WHERE
        #    is_current = true → must include detected_at.
        #  segmentby: instrument_id
        # ═══════════════════════════════════════════════════════════

        if not _is_hypertable(cursor, "strategy_drift_alerts"):
            # RLS incompatible with TimescaleDB columnstore — drop policies + disable.
            # Must happen BEFORE migrate_data which may trigger RLS evaluation.
            cursor.execute("DROP POLICY IF EXISTS org_isolation ON strategy_drift_alerts")
            cursor.execute("DROP POLICY IF EXISTS strategy_drift_alerts_org_isolation ON strategy_drift_alerts")
            cursor.execute("ALTER TABLE strategy_drift_alerts NO FORCE ROW LEVEL SECURITY")
            cursor.execute("ALTER TABLE strategy_drift_alerts DISABLE ROW LEVEL SECURITY")
            cursor.execute(
                "ALTER TABLE strategy_drift_alerts "
                "DROP CONSTRAINT IF EXISTS strategy_drift_alerts_pkey"
            )
            cursor.execute("DROP INDEX IF EXISTS uq_drift_alerts_current")
            cursor.execute("DROP INDEX IF EXISTS ix_drift_alerts_severity")
            cursor.execute(
                "SELECT create_hypertable("
                "  'strategy_drift_alerts', 'detected_at',"
                "  chunk_time_interval => INTERVAL '1 month',"
                "  migrate_data => true, if_not_exists => true)"
            )
            cursor.execute(
                "ALTER TABLE strategy_drift_alerts "
                "DROP CONSTRAINT IF EXISTS strategy_drift_alerts_pkey"
            )
            cursor.execute(
                "ALTER TABLE strategy_drift_alerts "
                "ADD CONSTRAINT strategy_drift_alerts_pkey "
                "PRIMARY KEY (detected_at, id)"
            )
            cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "idx_strategy_drift_alerts_org_instrument_current "
                "ON strategy_drift_alerts (detected_at, organization_id, instrument_id) "
                "WHERE is_current = true"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS "
                "idx_strategy_drift_alerts_org_severity_current "
                "ON strategy_drift_alerts (organization_id, severity, detected_at DESC) "
                "WHERE is_current = true"
            )
            cursor.execute(
                "ALTER TABLE strategy_drift_alerts SET ("
                "  timescaledb.compress,"
                "  timescaledb.compress_orderby = 'detected_at DESC',"
                "  timescaledb.compress_segmentby = 'instrument_id')"
            )
            cursor.execute(
                "SELECT add_compression_policy("
                "  'strategy_drift_alerts', INTERVAL '3 months',"
                "  if_not_exists => true)"
            )

        # ═══════════════════════════════════════════════════════════
        #  governance_alerts → hypertable
        # ═══════════════════════════════════════════════════════════

        if not _is_hypertable(cursor, "governance_alerts"):
            # RLS incompatible with TimescaleDB columnstore — drop policies + disable.
            # Must happen BEFORE any DML (e.g. _ensure_created_at_not_null) because
            # RLS policies reference app.current_organization_id which isn't set during migrations.
            cursor.execute("DROP POLICY IF EXISTS org_isolation ON governance_alerts")
            cursor.execute("ALTER TABLE governance_alerts NO FORCE ROW LEVEL SECURITY")
            cursor.execute("ALTER TABLE governance_alerts DISABLE ROW LEVEL SECURITY")
            _ensure_created_at_not_null(cursor, "governance_alerts")
            cursor.execute(
                "ALTER TABLE governance_alerts "
                "DROP CONSTRAINT IF EXISTS governance_alerts_pkey"
            )
            cursor.execute("DROP INDEX IF EXISTS ix_governance_alerts_fund_alert_id")
            cursor.execute(
                "SELECT create_hypertable("
                "  'governance_alerts', 'created_at',"
                "  chunk_time_interval => INTERVAL '1 month',"
                "  migrate_data => true, if_not_exists => true)"
            )
            cursor.execute(
                "ALTER TABLE governance_alerts "
                "DROP CONSTRAINT IF EXISTS governance_alerts_pkey"
            )
            cursor.execute(
                "ALTER TABLE governance_alerts "
                "ADD CONSTRAINT governance_alerts_pkey "
                "PRIMARY KEY (created_at, id)"
            )
            cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_governance_alerts_fund_alert "
                "ON governance_alerts (created_at, fund_id, alert_id)"
            )
            cursor.execute(
                "ALTER TABLE governance_alerts SET ("
                "  timescaledb.compress,"
                "  timescaledb.compress_orderby = 'created_at DESC',"
                "  timescaledb.compress_segmentby = 'organization_id')"
            )
            cursor.execute(
                "SELECT add_compression_policy("
                "  'governance_alerts', INTERVAL '3 months',"
                "  if_not_exists => true)"
            )

        # ═══════════════════════════════════════════════════════════
        #  pipeline_alerts → hypertable
        #  PK: id (UUID) → (created_at, id).
        #  segmentby: organization_id
        # ═══════════════════════════════════════════════════════════

        if not _is_hypertable(cursor, "pipeline_alerts"):
            # RLS incompatible with TimescaleDB columnstore — drop policies + disable.
            # Must happen BEFORE any DML (e.g. _ensure_created_at_not_null) because
            # RLS policies reference app.current_organization_id which isn't set during migrations.
            cursor.execute("DROP POLICY IF EXISTS org_isolation ON pipeline_alerts")
            cursor.execute("ALTER TABLE pipeline_alerts NO FORCE ROW LEVEL SECURITY")
            cursor.execute("ALTER TABLE pipeline_alerts DISABLE ROW LEVEL SECURITY")
            _ensure_created_at_not_null(cursor, "pipeline_alerts")
            cursor.execute(
                "ALTER TABLE pipeline_alerts "
                "DROP CONSTRAINT IF EXISTS pipeline_alerts_pkey"
            )
            cursor.execute("DROP INDEX IF EXISTS ix_pipeline_alerts_fund_deal")
            cursor.execute(
                "SELECT create_hypertable("
                "  'pipeline_alerts', 'created_at',"
                "  chunk_time_interval => INTERVAL '1 month',"
                "  migrate_data => true, if_not_exists => true)"
            )
            cursor.execute(
                "ALTER TABLE pipeline_alerts "
                "DROP CONSTRAINT IF EXISTS pipeline_alerts_pkey"
            )
            cursor.execute(
                "ALTER TABLE pipeline_alerts "
                "ADD CONSTRAINT pipeline_alerts_pkey "
                "PRIMARY KEY (created_at, id)"
            )
            cursor.execute(
                "ALTER TABLE pipeline_alerts SET ("
                "  timescaledb.compress,"
                "  timescaledb.compress_orderby = 'created_at DESC',"
                "  timescaledb.compress_segmentby = 'organization_id')"
            )
            cursor.execute(
                "SELECT add_compression_policy("
                "  'pipeline_alerts', INTERVAL '3 months',"
                "  if_not_exists => true)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_pipeline_alerts_fund_deal "
                "ON pipeline_alerts (fund_id, deal_id, created_at DESC)"
            )

        cursor.close()


def downgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        for table in (
            "performance_drift_flags", "strategy_drift_alerts",
            "governance_alerts", "pipeline_alerts",
        ):
            cursor.execute(
                f"SELECT remove_compression_policy('{table}', if_exists => true)"
            )
            cursor.execute(
                f"SELECT decompress_chunk(c.chunk_name) "
                f"FROM timescaledb_information.chunks c "
                f"WHERE c.hypertable_name = '{table}' "
                f"AND c.is_compressed = true"
            )
            cursor.execute(
                f"ALTER TABLE {table} SET (timescaledb.compress = false)"
            )

        # NOTE: Tables remain hypertables. Full revert requires drop + recreate.

        # Restore original PKs
        for table in (
            "performance_drift_flags", "governance_alerts", "pipeline_alerts",
        ):
            cursor.execute(
                f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_pkey"
            )
            cursor.execute(
                f"ALTER TABLE {table} ADD CONSTRAINT {table}_pkey PRIMARY KEY (id)"
            )

        # strategy_drift_alerts uses detected_at
        cursor.execute(
            "ALTER TABLE strategy_drift_alerts "
            "DROP CONSTRAINT IF EXISTS strategy_drift_alerts_pkey"
        )
        cursor.execute(
            "ALTER TABLE strategy_drift_alerts "
            "ADD CONSTRAINT strategy_drift_alerts_pkey PRIMARY KEY (id)"
        )

        # Restore original indexes
        cursor.execute("DROP INDEX IF EXISTS idx_perf_drift_flags_fund_investment")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_performance_drift_flags_fund_investment "
            "ON performance_drift_flags (fund_id, investment_id)"
        )

        cursor.execute("DROP INDEX IF EXISTS idx_strategy_drift_alerts_org_instrument_current")
        cursor.execute("DROP INDEX IF EXISTS idx_strategy_drift_alerts_org_severity_current")
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "ix_strategy_drift_alerts_org_instrument_current "
            "ON strategy_drift_alerts (organization_id, instrument_id) "
            "WHERE is_current = true"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS "
            "ix_strategy_drift_alerts_org_severity_current "
            "ON strategy_drift_alerts (organization_id, severity) "
            "WHERE is_current = true"
        )

        cursor.execute("DROP INDEX IF EXISTS idx_governance_alerts_fund_alert")
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_governance_alerts_fund_alert_id "
            "ON governance_alerts (fund_id, alert_id)"
        )

        cursor.execute("DROP INDEX IF EXISTS idx_pipeline_alerts_fund_deal")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_pipeline_alerts_fund_deal "
            "ON pipeline_alerts (fund_id, deal_id)"
        )

        cursor.close()
