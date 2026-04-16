"""portfolio_construction_runs: extend status CHECK with 'degraded'.

PR-A7 §B — when the optimizer cascade exhausts all four CLARABEL phases
and the run is completed by the proportional heuristic fallback, the
terminal status is ``degraded`` rather than ``succeeded``. The prior
constraint allowed only ``{running, succeeded, failed, superseded,
cancelled}``; this migration adds ``degraded`` as a sixth legal state
so the executor can persist the new signal.

DROP + ADD inside a single DDL transaction (no table rewrite). Existing
rows remain valid under the new constraint.

Revision ID: 0141_portfolio_status_degraded
Revises: 0140_instruments_org_source_override
Create Date: 2026-04-16
"""
from __future__ import annotations

from alembic import op

revision: str = "0141_portfolio_status_degraded"
down_revision: str | None = "0140_instruments_org_source_override"
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
            'cancelled'::text,
            'degraded'::text
        ]))
        """,
    )


def downgrade() -> None:
    # Roll any 'degraded' rows into 'succeeded' before tightening the
    # constraint — the downgrade must not fail on existing data. The
    # optimizer_trace.solver = 'heuristic_fallback' signal on the row
    # remains, so re-upgrading recovers the distinction deterministically.
    op.execute(
        """
        UPDATE portfolio_construction_runs
        SET status = 'succeeded'
        WHERE status = 'degraded'
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
            'cancelled'::text
        ]))
        """,
    )
