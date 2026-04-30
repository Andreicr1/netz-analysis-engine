"""PR-Q140: extend status CHECK with 'mandate_infeasible'.

Cascade status taxonomy refinement (C-01): separates mandate
infeasibility (Phase 3 CVaR limit unreachable, engine working correctly)
from technical degradation (covariance failure, heuristic fallback).

DROP + ADD inside a single DDL transaction (no table rewrite). Existing
rows remain valid under the new constraint.

Revision ID: 0197_q140_cascade_status_mandate_infeasible
Revises: 0196_q128_rebalance_pending_dedupe
Create Date: 2026-04-29
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0197_q140_cascade_status_mandate_infeasible"
down_revision: str | None = "0196_q128_rebalance_pending_dedupe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE portfolio_construction_runs
        DROP CONSTRAINT portfolio_construction_runs_status_check
        """,
    )
    op.execute(
        """
        ALTER TABLE portfolio_construction_runs
        ADD CONSTRAINT portfolio_construction_runs_status_check
        CHECK (status = ANY (ARRAY[
            'running'::text,
            'succeeded'::text,
            'failed'::text,
            'superseded'::text,
            'cancelled'::text,
            'degraded'::text,
            'mandate_infeasible'::text
        ]))
        """,
    )


def downgrade() -> None:
    # Roll any 'mandate_infeasible' rows back to 'degraded' before
    # tightening — preserves the pre-Q140 semantics where both
    # infeasibility and technical degradation mapped to 'degraded'.
    op.execute(
        """
        UPDATE portfolio_construction_runs
        SET status = 'degraded'
        WHERE status = 'mandate_infeasible'
        """,
    )
    op.execute(
        """
        ALTER TABLE portfolio_construction_runs
        DROP CONSTRAINT portfolio_construction_runs_status_check
        """,
    )
    op.execute(
        """
        ALTER TABLE portfolio_construction_runs
        ADD CONSTRAINT portfolio_construction_runs_status_check
        CHECK (status = ANY (ARRAY[
            'running'::text,
            'succeeded'::text,
            'failed'::text,
            'superseded'::text,
            'cancelled'::text,
            'degraded'::text
        ]))
        """,
    )
