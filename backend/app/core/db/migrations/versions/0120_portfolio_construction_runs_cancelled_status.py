"""portfolio_construction_runs: extend status CHECK with 'cancelled'.

Phase 2 Session C commit 3 — the cooperative cancellation pattern
introduced by ``DELETE /jobs/{job_id}`` lets the
``construction_run_executor`` exit gracefully when a client aborts
a long-running optimiser cascade. The existing CHECK constraint
only allows ``{running, succeeded, failed, superseded}``; this
migration adds ``cancelled`` as a fifth legal state so the executor
can persist the run's terminal status.

The rewrite is atomic (DROP + ADD inside a single DDL transaction)
and fast — there is no table rewrite since the column type is
unchanged. Existing rows remain valid under the new constraint.

Revision ID: 0120_portfolio_construction_runs_cancelled_status
Revises: 0119_mv_drift_heatmap_weekly
Create Date: 2026-04-11
"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0120_portfolio_construction_runs_cancelled_status"
down_revision: str | None = "0119_mv_drift_heatmap_weekly"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


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
            'cancelled'::text
        ]))
        """,
    )


def downgrade() -> None:
    # Roll any existing 'cancelled' rows into 'failed' before
    # tightening the constraint so the downgrade cannot fail on data.
    op.execute(
        """
        UPDATE portfolio_construction_runs
        SET status = 'failed',
            failure_reason = COALESCE(failure_reason, '') || ' (was cancelled)'
        WHERE status = 'cancelled'
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
            'superseded'::text
        ]))
        """,
    )
