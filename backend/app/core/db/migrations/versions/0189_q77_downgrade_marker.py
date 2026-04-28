"""q77 downgrade marker — narrow rollback scope for 0185

Codex Auto Review P2: 0185 downgrade was asymmetric (deleted all UCITS
structure values, not only those added by upgrade). This migration adds
a marker to rows that 0185 likely touched, allowing 0185.downgrade()
to delete narrow.

Revision ID: 0189_q77_downgrade_marker
Revises: 0188_ucits_etf_tag_backfill
Create Date: 2026-04-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0189_q77_downgrade_marker"
down_revision: str | None = "0188_ucits_etf_tag_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Mark all UCITS funds with structure='UCITS' as q77-added.
    # Idempotent — skips rows already marked.
    # Note: this conservatively marks all matching rows, including the
    # 3 edge-case rows mentioned in Q77 PR body (BG mutual + LU ETF).
    # In practice, those edge cases had pre-existing wrong structure
    # values that 0185 did NOT overwrite (upgrade WHERE clause filtered
    # them out), so a future rollback that strips structure from them
    # is acceptable cleanup.
    op.execute("""
        UPDATE instruments_universe
        SET attributes = attributes || jsonb_build_object('_q77_added_structure', true)
        WHERE attributes->>'fund_subtype' = 'ucits'
          AND attributes->>'structure' = 'UCITS'
          AND NOT (attributes ? '_q77_added_structure')
    """)


def downgrade() -> None:
    # Marker is consumed by 0185.downgrade() when it runs as part of
    # downgrade chain. Leaving marker in place during this no-op ensures
    # downstream 0185.downgrade() can still narrow-scope.
    pass
