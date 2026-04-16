"""Add source + block_overridden columns to instruments_org.

Supports the universe_auto_import worker (lock 900_103, PR-A6 Section C).

- ``source`` (VARCHAR(40), default 'manual') distinguishes manually-imported
  rows (Screener flow) from worker-imported rows ('universe_auto_import').
  Used by the worker's ``ON CONFLICT`` branch to preserve the origin of
  dual-tracked rows ('manual,auto') so audit trail keeps both signals.
- ``block_overridden`` (BOOLEAN, default false) is set by the Screener UI
  when a user manually edits ``block_id``. The worker respects this flag
  and will not overwrite the block on subsequent runs.

Unique constraint on ``(organization_id, instrument_id)`` already exists
from migration 0068 — the worker's ON CONFLICT target matches it.

CONCURRENTLY is intentionally NOT used — Alembic wraps migrations in a
transaction by default, and the project convention (see 0096, 0113) is
to create indexes synchronously inside the migration. For prod, recreate
the partial index CONCURRENTLY post-deploy if table size becomes a
concern.

Revision ID: 0140_instruments_org_source_override
Revises: 0139_universe_cleanup_pre_autoimport
Create Date: 2026-04-16
"""

from alembic import op

revision = "0140_instruments_org_source_override"
down_revision = "0139_universe_cleanup_pre_autoimport"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE instruments_org
        ADD COLUMN IF NOT EXISTS source VARCHAR(40)
            NOT NULL DEFAULT 'manual'
    """)
    op.execute("""
        ALTER TABLE instruments_org
        ADD COLUMN IF NOT EXISTS block_overridden BOOLEAN
            NOT NULL DEFAULT false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_instruments_org_source_auto
        ON instruments_org (organization_id, source)
        WHERE source = 'universe_auto_import'
           OR source = 'manual,auto'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_instruments_org_source_auto")
    op.execute("ALTER TABLE instruments_org DROP COLUMN IF EXISTS block_overridden")
    op.execute("ALTER TABLE instruments_org DROP COLUMN IF EXISTS source")
