"""strategy_drift_alerts — add acknowledged_at + acknowledged_by columns

Phase 7 of `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`
(re-scoped sprint — Alerts Unification).

Per DL15 the inbox read/unread state must persist via the backend API,
not localStorage. The portfolio_alerts table (migration 0103) already
has acknowledged_at + acknowledged_by columns; this migration brings
the strategy_drift_alerts table to parity so the UnifiedAlert
aggregator can write the same ``ack`` operation to either source.

The columns are nullable. NULL = unread; a non-null timestamp = the
moment the actor acknowledged the alert via the GlobalAlertInbox bell
icon dropdown. The acknowledged_by column is the actor_id from the
Clerk JWT.

No indexes are added — the inbox query filters in the application
layer because the volume is small (a few thousand drift alerts per
org max). If/when the volume grows, a partial index on
``(organization_id, acknowledged_at) WHERE acknowledged_at IS NULL``
can land in a follow-up migration.

Revision ID: 0106_strategy_drift_alerts_acknowledged
Revises: 0105_portfolio_calibration_fk_on_construction_runs
Create Date: 2026-04-08
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0106_strategy_drift_alerts_acknowledged"
down_revision: str | None = "0105_portfolio_calibration_fk_on_construction_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE strategy_drift_alerts
            ADD COLUMN acknowledged_at timestamptz NULL,
            ADD COLUMN acknowledged_by text NULL;
        """,
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE strategy_drift_alerts
            DROP COLUMN acknowledged_by,
            DROP COLUMN acknowledged_at;
        """,
    )
