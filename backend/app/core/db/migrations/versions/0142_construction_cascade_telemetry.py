"""Add cascade_telemetry column to portfolio_construction_runs.

PR-A11 — per-phase optimizer cascade audit trail + operator signal.

The column carries the full cascade trace (``phase_attempts`` array,
``cascade_summary`` enum, ``phase2_max_var``, ``min_achievable_variance``,
``feasibility_gap_pct``, ``operator_signal``) so operators can distinguish
a genuine risk-adjusted optimum from a Phase 3 min-variance fallback
forced by an infeasible CVaR budget. ``binding_constraints`` is left
untouched (Option B) — it keeps its existing list-of-strings semantics.

Partial expression index on ``cascade_summary`` keeps the operator
dashboard query ("which portfolios degraded to fallback?") cheap.

Revision ID: 0142_construction_cascade_telemetry
Revises: 0141_portfolio_status_degraded
Create Date: 2026-04-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0142_construction_cascade_telemetry"
down_revision: str | None = "0141_portfolio_status_degraded"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "portfolio_construction_runs",
        sa.Column(
            "cascade_telemetry",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.execute(
        """
        CREATE INDEX ix_pcr_cascade_summary
        ON portfolio_construction_runs
            ((cascade_telemetry->>'cascade_summary'), requested_at DESC)
        WHERE cascade_telemetry->>'cascade_summary'
            IN ('phase_3_fallback', 'heuristic_fallback')
        """,
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_pcr_cascade_summary")
    op.drop_column("portfolio_construction_runs", "cascade_telemetry")
