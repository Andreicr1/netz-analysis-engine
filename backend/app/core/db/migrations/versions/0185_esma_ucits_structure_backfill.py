"""Backfill structure='UCITS' for ESMA-origin funds in instruments_universe.

Revision ID: 0185_esma_ucits_structure_backfill
Revises: 0184_factor_source_blocks
Create Date: 2026-04-28

PR-Q77 — Screener Layer 1 rejected 100% of 2,932 UCITS funds at
allowed_structure because instruments_universe.attributes.structure was
never populated for ESMA-origin funds. universe_sync.py Phase 4 wrote
domicile and fund_subtype but omitted structure.

ESMA Register is exclusively UCITS by regulatory design (esma_funds.fund_type
has single value 'UCITS' across all rows). Hard-coding structure='UCITS' is
the deterministic mapping. SICAV refinement is backlog.

Idempotent: WHERE clause filters rows already populated.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0185_esma_ucits_structure_backfill"
down_revision: str | None = "0184_factor_source_blocks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE instruments_universe
        SET attributes = attributes || jsonb_build_object('structure', 'UCITS')
        WHERE attributes->>'fund_subtype' = 'ucits'
          AND (attributes->>'structure' IS NULL OR attributes->>'structure' = '')
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE instruments_universe
        SET attributes = attributes - 'structure'
        WHERE attributes->>'fund_subtype' = 'ucits'
          AND attributes->>'structure' = 'UCITS'
    """)
