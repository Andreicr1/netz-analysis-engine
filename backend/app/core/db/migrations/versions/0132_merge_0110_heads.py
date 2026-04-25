"""Merge 0110 (signal_breakdown_macro_regime) and 0131_return_5y_10y heads.

Revision ID: 0132_merge_0110_heads
Revises: 0110, 0131_return_5y_10y
Create Date: 2026-04-14

Context:
    The alembic file-graph had two heads descending from 0109:

      0109 → 0110_signal_breakdown_macro_regime
      0109 → 0110_fund_risk_metrics_compress_segmentby_fix → 0111 → ... → 0131_return_5y_10y

    The second chain is applied in full (0131 is in alembic_version and
    implies all its ancestors including the compress_segmentby_fix). The
    first chain (0110_signal_breakdown_macro_regime) also applied as its
    own head. Both heads are legitimate parallel work that was never
    unified in the migration graph.

    Reconciliation strategy — Option C (stamp + merge):
      1. `scripts/reconcile_0110_heads.py` verifies the physical state
         (TimescaleDB compression already uses segmentby=instrument_id,
          orderby=calc_date DESC) and that alembic_version contains exactly
          the two file-graph heads.
      2. This no-op merge migration collapses the two heads into a single
         descendant so `alembic upgrade head` (singular) works going
         forward without requiring `heads` plural.

    Upgrade and downgrade are deliberately no-ops: no schema change, no
    data change. The migration exists only to reconcile the DAG.

Why not a stamp-only approach:
    A stamp on one of the heads would not collapse the file graph — a
    later migration would still have to choose one parent, leaving the
    other head dangling. A merge migration makes the reconciliation
    explicit and auditable in the migration history.
"""

from __future__ import annotations

import sqlalchemy as sa  # noqa: F401
from alembic import op  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = "0132_merge_0110_heads"
down_revision: tuple[str, str] = ("0110", "0131_return_5y_10y")
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """No-op: graph reconciliation only."""


def downgrade() -> None:
    """No-op: graph reconciliation only."""
