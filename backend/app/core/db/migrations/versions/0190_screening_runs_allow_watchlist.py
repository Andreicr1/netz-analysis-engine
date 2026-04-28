"""Expand chk_run_type to include 'watchlist' run type.

The watchlist_batch worker (Q65/Q83) inserts run_type='watchlist' but the
CHECK constraint from migration 0012 only allowed 'batch' | 'on_demand'.
This made watchlist_batch a silent dead worker — always failing on the
first screening_run INSERT. Discovered by PR-Q86 CI smoke test suite.

Revision ID: 0190_screening_runs_allow_watchlist
Revises: 0189_q77_downgrade_marker
Create Date: 2026-04-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0190_screening_runs_allow_watchlist"
down_revision: str | None = "0189_q77_downgrade_marker"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE screening_runs DROP CONSTRAINT IF EXISTS chk_run_type")
    op.execute("""
        ALTER TABLE screening_runs
        ADD CONSTRAINT chk_run_type
        CHECK (run_type IN ('batch', 'on_demand', 'watchlist'))
    """)


def downgrade() -> None:
    # Remap watchlist rows to 'batch' (closest semantic equivalent) before
    # re-adding narrow constraint — preserves audit trail vs DELETE.
    op.execute("UPDATE screening_runs SET run_type = 'batch' WHERE run_type = 'watchlist'")
    op.execute("ALTER TABLE screening_runs DROP CONSTRAINT IF EXISTS chk_run_type")
    op.execute("""
        ALTER TABLE screening_runs
        ADD CONSTRAINT chk_run_type
        CHECK (run_type IN ('batch', 'on_demand'))
    """)
