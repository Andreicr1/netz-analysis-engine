"""PR-Q128: Add partial unique index for pending drift_rebalance events.

Prevents duplicate pending RebalanceEvent rows per (org, profile, event_type).
Mirrors PortfolioAlert dedupe_key pattern.

Revision ID: 0196_q128_rebalance_pending_dedupe
Revises: 0195_q92_audit_events_global
Create Date: 2026-04-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0196_q128_rebalance_pending_dedupe"
down_revision: str | None = "0195_q92_audit_events_global"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Cleanup: keep latest pending per (organization_id, profile, event_type),
    # delete older duplicates. Required before unique index creation —
    # prod DBs may already have duplicates from pre-Q128 worker behavior.
    op.execute(
        sa.text("""
            DELETE FROM rebalance_events re_old
            USING rebalance_events re_new
            WHERE re_old.organization_id = re_new.organization_id
              AND re_old.profile = re_new.profile
              AND re_old.event_type = re_new.event_type
              AND re_old.status = 'pending'
              AND re_new.status = 'pending'
              AND re_old.event_id != re_new.event_id
              AND (
                  re_old.created_at < re_new.created_at
                  OR (
                      re_old.created_at = re_new.created_at
                      AND re_old.event_id < re_new.event_id
                  )
              )
        """)
    )

    op.create_index(
        "uq_rebalance_event_pending_per_profile",
        "rebalance_events",
        ["organization_id", "profile", "event_type"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_rebalance_event_pending_per_profile", "rebalance_events")
