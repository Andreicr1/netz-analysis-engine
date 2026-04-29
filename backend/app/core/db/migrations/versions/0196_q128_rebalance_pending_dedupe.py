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
    # Bypass RLS for cleanup DELETE — migration runs as superuser
    # and needs to deduplicate across ALL orgs.  rebalance_events has
    # FORCE ROW LEVEL SECURITY (migration 0003) with policy on
    # current_setting('app.current_organization_id').  Without org
    # context the policy filters all rows → DELETE deletes 0.
    op.execute(sa.text("ALTER TABLE rebalance_events DISABLE ROW LEVEL SECURITY"))

    try:
        # Cleanup: keep latest pending drift_rebalance per (organization_id, profile),
        # delete older duplicates. Scoped to event_type='drift_rebalance' only —
        # manual/scheduled pending events must NOT be touched.
        op.execute(
            sa.text("""
                DELETE FROM rebalance_events re_old
                USING rebalance_events re_new
                WHERE re_old.organization_id = re_new.organization_id
                  AND re_old.profile = re_new.profile
                  AND re_old.event_type = 'drift_rebalance'
                  AND re_new.event_type = 'drift_rebalance'
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
            "uq_rebalance_event_pending_drift_per_profile",
            "rebalance_events",
            ["organization_id", "profile"],
            unique=True,
            postgresql_where=sa.text(
                "status = 'pending' AND event_type = 'drift_rebalance'"
            ),
        )
    finally:
        # Restore RLS to pre-migration state (ENABLE + FORCE from migration 0003)
        op.execute(sa.text("ALTER TABLE rebalance_events ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text("ALTER TABLE rebalance_events FORCE ROW LEVEL SECURITY"))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE rebalance_events DISABLE ROW LEVEL SECURITY"))
    try:
        op.drop_index("uq_rebalance_event_pending_drift_per_profile", "rebalance_events")
    finally:
        op.execute(sa.text("ALTER TABLE rebalance_events ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text("ALTER TABLE rebalance_events FORCE ROW LEVEL SECURITY"))
