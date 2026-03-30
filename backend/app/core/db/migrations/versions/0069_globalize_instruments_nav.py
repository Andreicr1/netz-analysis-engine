"""Globalize instruments_universe and nav_timeseries.

Removes organization_id, block_id, approval_status from instruments_universe.
Removes organization_id from nav_timeseries.
Drops RLS policies from both tables.

Revision ID: 0069
Revises: 0068_instruments_org
"""

revision = "0069_globalize_instruments_nav"
down_revision = "0068_instruments_org"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    # ── instruments_universe: remove org-scoped columns + RLS ──────────

    # Drop RLS policy and disable
    op.execute("DROP POLICY IF EXISTS instruments_universe_rls ON instruments_universe")
    op.execute("DROP POLICY IF EXISTS instruments_universe_isolation ON instruments_universe")
    op.execute("ALTER TABLE instruments_universe DISABLE ROW LEVEL SECURITY")

    # Deduplicate: if same ticker exists for multiple orgs, keep first
    # (instruments_org already has the org links from migration 0068)
    op.execute("""
        DELETE FROM instruments_universe a
        USING instruments_universe b
        WHERE a.instrument_id > b.instrument_id
          AND a.ticker IS NOT NULL
          AND a.ticker = b.ticker
    """)

    # Drop org-scoped columns (CASCADE drops dependent indexes/constraints)
    op.execute("DROP INDEX IF EXISTS ix_instruments_universe_organization_id")
    op.execute("ALTER TABLE instruments_universe DROP COLUMN IF EXISTS organization_id CASCADE")
    op.execute("ALTER TABLE instruments_universe DROP COLUMN IF EXISTS block_id CASCADE")
    op.execute("ALTER TABLE instruments_universe DROP COLUMN IF EXISTS approval_status CASCADE")

    # ── nav_timeseries: remove organization_id ─────────────────────────

    # nav_timeseries is a TimescaleDB hypertable — handle compression first
    # Disable compression policy if exists (ignore error if not set)
    op.execute("""
        DO $$
        BEGIN
            PERFORM remove_compression_policy('nav_timeseries', if_exists => true);
        EXCEPTION WHEN OTHERS THEN
            NULL;
        END $$
    """)

    # Decompress all chunks before altering
    op.execute("""
        DO $$
        BEGIN
            PERFORM decompress_chunk(c, if_compressed => true)
            FROM show_chunks('nav_timeseries') c;
        EXCEPTION WHEN OTHERS THEN
            NULL;
        END $$
    """)

    # Drop RLS
    op.execute("DROP POLICY IF EXISTS nav_timeseries_rls ON nav_timeseries")
    op.execute("DROP POLICY IF EXISTS nav_timeseries_isolation ON nav_timeseries")
    op.execute("ALTER TABLE nav_timeseries DISABLE ROW LEVEL SECURITY")

    # Drop organization_id column
    op.execute("DROP INDEX IF EXISTS ix_nav_timeseries_organization_id")
    op.execute("ALTER TABLE nav_timeseries DROP COLUMN IF EXISTS organization_id")

    # Re-enable compression with instrument_id as segmentby
    op.execute("""
        DO $$
        BEGIN
            PERFORM set_integer_now_func('nav_timeseries', 'unix_now', replace_if_exists => true);
        EXCEPTION WHEN OTHERS THEN
            NULL;
        END $$
    """)
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE nav_timeseries SET (
                timescaledb.compress,
                timescaledb.compress_segmentby = 'instrument_id'
            );
        EXCEPTION WHEN OTHERS THEN
            NULL;
        END $$
    """)
    op.execute("""
        DO $$
        BEGIN
            PERFORM add_compression_policy('nav_timeseries', INTERVAL '3 months', if_not_exists => true);
        EXCEPTION WHEN OTHERS THEN
            NULL;
        END $$
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrade not supported — data loss risk")
