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

import sqlalchemy as sa
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
    # Dual-mode rollback to handle two deployment scenarios:
    # (a) DB passed through 0189 → marker present → narrow undo (preserves
    #     pre-existing edge cases — see PR-Q82 PR body for the 3 known cases).
    # (b) DB never reached 0189 (e.g. environment at 0186-0188 rolling back
    #     to 0184) → marker absent → broad undo (original 0185 behavior).
    # The marker check is idempotent: 0189.upgrade() is conservative and tags
    # all UCITS rows with structure='UCITS', so presence/absence is a reliable
    # signal of whether 0189 was ever applied to this database.
    bind = op.get_bind()
    has_marker = bind.execute(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM instruments_universe "
            "WHERE attributes ? '_q77_added_structure')"
        )
    ).scalar()

    if has_marker:
        # Step 1 — narrow undo: only rows still at original 'UCITS' value.
        # If structure was deliberately corrected post-0185 (e.g. to 'SICAV'
        # by a future enrichment process or manual edit), the corrected
        # value is preserved — only the now-stale marker is cleaned up in
        # step 2 below.
        op.execute(
            """
            UPDATE instruments_universe
            SET attributes = (attributes - 'structure' - '_q77_added_structure')
            WHERE (attributes->>'_q77_added_structure')::bool = true
              AND attributes->>'structure' = 'UCITS'
            """
        )
        # Step 2 — cleanup stale markers from rows whose structure was
        # corrected post-0185. Marker tracked the original backfill; once
        # the value diverges from 'UCITS', the marker is no longer relevant.
        op.execute(
            """
            UPDATE instruments_universe
            SET attributes = attributes - '_q77_added_structure'
            WHERE attributes ? '_q77_added_structure'
            """
        )
    else:
        # Broad fallback — original 0185 downgrade. Safe in pre-0189
        # environments where no Q82 marker semantics exist yet.
        op.execute(
            """
            UPDATE instruments_universe
            SET attributes = attributes - 'structure'
            WHERE attributes->>'fund_subtype' = 'ucits'
              AND attributes->>'structure' = 'UCITS'
            """
        )
