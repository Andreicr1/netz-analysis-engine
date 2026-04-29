"""PR-Q128: Add partial unique index for pending drift_rebalance events.

Prevents duplicate pending RebalanceEvent rows per (org, profile, event_type).
Mirrors PortfolioAlert dedupe_key pattern.

Revision ID: 0196_q128_rebalance_pending_dedupe
Revises: 0195_q92_audit_events_global
Create Date: 2026-04-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0196_q128_rebalance_pending_dedupe"
down_revision: str | None = "0195_q92_audit_events_global"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_rebalance_event_pending_per_profile",
        "rebalance_events",
        ["organization_id", "profile", "event_type"],
        unique=True,
        postgresql_where="status = 'pending'",
    )


def downgrade() -> None:
    op.drop_index("uq_rebalance_event_pending_per_profile", "rebalance_events")
