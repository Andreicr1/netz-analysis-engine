"""Convert NAV & portfolio snapshot tables to TimescaleDB hypertables.

Tables: nav_snapshots, asset_valuation_snapshots, portfolio_snapshots.

All three are TENANT-SCOPED tables with RLS.

nav_snapshots is a FK target for:
  - monthly_report_packs.nav_snapshot_id
  - asset_valuation_snapshots.nav_snapshot_id
These FKs must be dropped before conversion because TimescaleDB requires
the partition column in all unique constraints — UNIQUE(id) alone is not
possible, so FK references to nav_snapshots.id cannot be maintained.
Application layer handles referential integrity post-conversion.

portfolio_snapshots has UNIQUE(organization_id, profile, snapshot_date) —
snapshot_date IS the partition column, so this constraint is already
TimescaleDB-compatible.

Uses a separate DBAPI connection with autocommit because
create_hypertable() cannot run inside a transaction block.

depends_on: 0026 (macro_market_hypertables).
"""

import os

import psycopg

from alembic import op

revision = "0027_nav_portfolio_hypertables"
down_revision = "0026_macro_market_hypertables"
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
        #  nav_snapshots → hypertable
        #  PK: id (UUID) → restructure to (created_at, id).
        #  Time column: created_at (from _audit()).
        #  FK targets: monthly_report_packs, asset_valuation_snapshots
        #    — must be dropped before conversion.
        #  segmentby: fund_id
        # ═══════════════════════════════════════════════════════════

        # Step 1: Drop inbound FKs (hypertable PK will be (created_at, id),
        # so UNIQUE(id) alone is impossible — FK references to id break).
        cursor.execute(
            "ALTER TABLE monthly_report_packs "
            "DROP CONSTRAINT IF EXISTS monthly_report_packs_nav_snapshot_id_fkey",
        )
        cursor.execute(
            "ALTER TABLE asset_valuation_snapshots "
            "DROP CONSTRAINT IF EXISTS asset_valuation_snapshots_nav_snapshot_id_fkey",
        )

        # Step 2: Drop RLS BEFORE any DML (policy references app.current_organization_id)
        cursor.execute("DROP POLICY IF EXISTS org_isolation ON nav_snapshots")
        cursor.execute("ALTER TABLE nav_snapshots NO FORCE ROW LEVEL SECURITY")
        cursor.execute("ALTER TABLE nav_snapshots DISABLE ROW LEVEL SECURITY")

        # Step 3: Ensure time column NOT NULL
        cursor.execute(
            "UPDATE nav_snapshots SET created_at = NOW() WHERE created_at IS NULL",
        )
        cursor.execute(
            "ALTER TABLE nav_snapshots ALTER COLUMN created_at SET NOT NULL",
        )

        # Step 4: Drop PK and existing indexes that will be recreated
        cursor.execute(
            "ALTER TABLE nav_snapshots DROP CONSTRAINT IF EXISTS nav_snapshots_pkey",
        )
        cursor.execute("DROP INDEX IF EXISTS ix_nav_snapshots_fund_period")
        cursor.execute("DROP INDEX IF EXISTS ix_nav_snapshots_fund_status")

        # Step 5: Convert to hypertable
        cursor.execute(
            "SELECT create_hypertable("
            "  'nav_snapshots',"
            "  'created_at',"
            "  chunk_time_interval => INTERVAL '1 month',"
            "  migrate_data => true,"
            "  if_not_exists => true"
            ")",
        )

        # Step 6: New PK with partition column
        cursor.execute(
            "ALTER TABLE nav_snapshots "
            "DROP CONSTRAINT IF EXISTS nav_snapshots_pkey",
        )
        cursor.execute(
            "ALTER TABLE nav_snapshots "
            "ADD CONSTRAINT nav_snapshots_pkey "
            "PRIMARY KEY (created_at, id)",
        )

        cursor.execute(
            "ALTER TABLE nav_snapshots SET ("
            "  timescaledb.compress,"
            "  timescaledb.compress_orderby = 'created_at DESC',"
            "  timescaledb.compress_segmentby = 'fund_id'"
            ")",
        )

        cursor.execute(
            "SELECT add_compression_policy("
            "  'nav_snapshots', INTERVAL '3 months', if_not_exists => true"
            ")",
        )

        # Step 7: Recreate indexes with time column awareness
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_nav_snapshots_fund_period "
            "ON nav_snapshots (fund_id, period_month, created_at DESC)",
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_nav_snapshots_fund_status "
            "ON nav_snapshots (fund_id, status, created_at DESC)",
        )

        # ═══════════════════════════════════════════════════════════
        #  asset_valuation_snapshots → hypertable
        #  PK: id (UUID) → restructure to (created_at, id).
        #  Time column: created_at (from _audit()).
        #  Has FK to nav_snapshots.id (already dropped above),
        #    and FK to documents.id (outbound, fine to keep).
        #  segmentby: fund_id
        # ═══════════════════════════════════════════════════════════

        # Drop RLS before DML
        cursor.execute("DROP POLICY IF EXISTS org_isolation ON asset_valuation_snapshots")
        cursor.execute("ALTER TABLE asset_valuation_snapshots NO FORCE ROW LEVEL SECURITY")
        cursor.execute("ALTER TABLE asset_valuation_snapshots DISABLE ROW LEVEL SECURITY")

        cursor.execute(
            "UPDATE asset_valuation_snapshots SET created_at = NOW() WHERE created_at IS NULL",
        )
        cursor.execute(
            "ALTER TABLE asset_valuation_snapshots ALTER COLUMN created_at SET NOT NULL",
        )

        cursor.execute(
            "ALTER TABLE asset_valuation_snapshots "
            "DROP CONSTRAINT IF EXISTS asset_valuation_snapshots_pkey",
        )
        cursor.execute("DROP INDEX IF EXISTS ix_asset_valuation_snapshots_fund_nav")
        cursor.execute("DROP INDEX IF EXISTS ix_asset_valuation_snapshots_nav_asset")

        cursor.execute(
            "SELECT create_hypertable("
            "  'asset_valuation_snapshots', 'created_at',"
            "  chunk_time_interval => INTERVAL '1 month',"
            "  migrate_data => true, if_not_exists => true)",
        )

        cursor.execute(
            "ALTER TABLE asset_valuation_snapshots "
            "DROP CONSTRAINT IF EXISTS asset_valuation_snapshots_pkey",
        )
        cursor.execute(
            "ALTER TABLE asset_valuation_snapshots "
            "ADD CONSTRAINT asset_valuation_snapshots_pkey "
            "PRIMARY KEY (created_at, id)",
        )

        cursor.execute(
            "ALTER TABLE asset_valuation_snapshots SET ("
            "  timescaledb.compress,"
            "  timescaledb.compress_orderby = 'created_at DESC',"
            "  timescaledb.compress_segmentby = 'fund_id'"
            ")",
        )

        cursor.execute(
            "SELECT add_compression_policy("
            "  'asset_valuation_snapshots', INTERVAL '3 months', if_not_exists => true"
            ")",
        )

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_asset_val_snapshots_fund_nav "
            "ON asset_valuation_snapshots (fund_id, nav_snapshot_id, created_at DESC)",
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_asset_val_snapshots_nav_asset "
            "ON asset_valuation_snapshots (nav_snapshot_id, asset_id, created_at DESC)",
        )

        # ═══════════════════════════════════════════════════════════
        #  portfolio_snapshots → hypertable
        #  PK: snapshot_id (UUID) → restructure to (snapshot_date, snapshot_id).
        #  Time column: snapshot_date (Date, NOT NULL).
        #  Unique: (organization_id, profile, snapshot_date) — already
        #    includes partition column, TimescaleDB-compatible.
        #  segmentby: organization_id
        # ═══════════════════════════════════════════════════════════

        # Drop RLS before DDL (prevent policy evaluation during migrate_data)
        cursor.execute("DROP POLICY IF EXISTS org_isolation ON portfolio_snapshots")
        cursor.execute("ALTER TABLE portfolio_snapshots NO FORCE ROW LEVEL SECURITY")
        cursor.execute("ALTER TABLE portfolio_snapshots DISABLE ROW LEVEL SECURITY")

        cursor.execute(
            "ALTER TABLE portfolio_snapshots "
            "DROP CONSTRAINT IF EXISTS portfolio_snapshots_pkey",
        )
        cursor.execute(
            "DROP INDEX IF EXISTS ix_portfolio_snapshots_org_profile_date",
        )

        cursor.execute(
            "SELECT create_hypertable("
            "  'portfolio_snapshots', 'snapshot_date',"
            "  chunk_time_interval => INTERVAL '1 month',"
            "  migrate_data => true, if_not_exists => true)",
        )

        cursor.execute(
            "ALTER TABLE portfolio_snapshots "
            "DROP CONSTRAINT IF EXISTS portfolio_snapshots_pkey",
        )
        cursor.execute(
            "ALTER TABLE portfolio_snapshots "
            "ADD CONSTRAINT portfolio_snapshots_pkey "
            "PRIMARY KEY (snapshot_date, snapshot_id)",
        )

        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_portfolio_snapshots_org_profile_date "
            "ON portfolio_snapshots (organization_id, profile, snapshot_date)",
        )

        cursor.execute(
            "ALTER TABLE portfolio_snapshots SET ("
            "  timescaledb.compress,"
            "  timescaledb.compress_orderby = 'snapshot_date DESC',"
            "  timescaledb.compress_segmentby = 'organization_id'"
            ")",
        )

        cursor.execute(
            "SELECT add_compression_policy("
            "  'portfolio_snapshots', INTERVAL '3 months', if_not_exists => true"
            ")",
        )

        cursor.close()


def downgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        for table in (
            "nav_snapshots", "asset_valuation_snapshots", "portfolio_snapshots",
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

        # NOTE: Tables remain hypertables after downgrade. Full revert
        # requires drop + recreate (destructive).

        # Restore nav_snapshots original PK
        cursor.execute(
            "ALTER TABLE nav_snapshots DROP CONSTRAINT IF EXISTS nav_snapshots_pkey",
        )
        cursor.execute(
            "ALTER TABLE nav_snapshots "
            "ADD CONSTRAINT nav_snapshots_pkey PRIMARY KEY (id)",
        )

        # Restore FKs to nav_snapshots
        cursor.execute(
            "ALTER TABLE monthly_report_packs "
            "ADD CONSTRAINT monthly_report_packs_nav_snapshot_id_fkey "
            "FOREIGN KEY (nav_snapshot_id) REFERENCES nav_snapshots(id) ON DELETE SET NULL",
        )
        cursor.execute(
            "ALTER TABLE asset_valuation_snapshots "
            "ADD CONSTRAINT asset_valuation_snapshots_nav_snapshot_id_fkey "
            "FOREIGN KEY (nav_snapshot_id) REFERENCES nav_snapshots(id) ON DELETE CASCADE",
        )

        # Restore asset_valuation_snapshots original PK
        cursor.execute(
            "ALTER TABLE asset_valuation_snapshots "
            "DROP CONSTRAINT IF EXISTS asset_valuation_snapshots_pkey",
        )
        cursor.execute(
            "ALTER TABLE asset_valuation_snapshots "
            "ADD CONSTRAINT asset_valuation_snapshots_pkey PRIMARY KEY (id)",
        )

        # Restore portfolio_snapshots original PK
        cursor.execute(
            "ALTER TABLE portfolio_snapshots "
            "DROP CONSTRAINT IF EXISTS portfolio_snapshots_pkey",
        )
        cursor.execute(
            "ALTER TABLE portfolio_snapshots "
            "ADD CONSTRAINT portfolio_snapshots_pkey PRIMARY KEY (snapshot_id)",
        )

        # Drop hypertable-specific indexes
        cursor.execute("DROP INDEX IF EXISTS idx_nav_snapshots_fund_period")
        cursor.execute("DROP INDEX IF EXISTS idx_nav_snapshots_fund_status")
        cursor.execute("DROP INDEX IF EXISTS idx_asset_val_snapshots_fund_nav")
        cursor.execute("DROP INDEX IF EXISTS idx_asset_val_snapshots_nav_asset")

        # Restore original indexes
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_nav_snapshots_fund_period "
            "ON nav_snapshots (fund_id, period_month)",
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_nav_snapshots_fund_status "
            "ON nav_snapshots (fund_id, status)",
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_asset_valuation_snapshots_fund_nav "
            "ON asset_valuation_snapshots (fund_id, nav_snapshot_id)",
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_asset_valuation_snapshots_nav_asset "
            "ON asset_valuation_snapshots (nav_snapshot_id, asset_id)",
        )

        cursor.close()
