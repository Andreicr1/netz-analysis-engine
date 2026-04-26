"""esma_funds — additive LEI compatibility column.

PR-Q11B Phase 1.1. The ``esma_funds`` table historically stores LEI values
in the ``isin`` column (per ``register_service.py:200`` design note).
This migration adds a proper ``lei`` column populated from ``isin``,
with a CHECK constraint for 20-char LEI format and a unique index.

The column is additive — the old ``isin`` PK is untouched here.
Migration 0182 rotates the PK once all callsites are updated.

Revision ID: 0180_esma_funds_lei_compat
Revises: 0179_sec_nport_cik_padded_generated_column
Create Date: 2026-04-26
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0180_esma_funds_lei_compat"
down_revision: str | None = "0179_sec_nport_cik_padded_generated_column"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE esma_funds ADD COLUMN lei text")
    op.execute("UPDATE esma_funds SET lei = isin WHERE lei IS NULL")
    op.execute("ALTER TABLE esma_funds ALTER COLUMN lei SET NOT NULL")
    op.execute(
        "ALTER TABLE esma_funds ADD CONSTRAINT chk_esma_funds_lei "
        "CHECK (lei ~ '^[A-Z0-9]{20}$')"
    )
    op.execute("CREATE UNIQUE INDEX uq_esma_funds_lei ON esma_funds(lei)")
    op.execute(
        "CREATE INDEX idx_esma_funds_lei_manager ON esma_funds(lei, esma_manager_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_esma_funds_lei_manager")
    op.execute("DROP INDEX IF EXISTS uq_esma_funds_lei")
    op.execute("ALTER TABLE esma_funds DROP CONSTRAINT IF EXISTS chk_esma_funds_lei")
    op.execute("ALTER TABLE esma_funds DROP COLUMN IF EXISTS lei")
