"""default cash override_max per profile (institutional mandate defaults)

Sets `strategic_allocation.override_max` for the cash block on all existing
(org, profile) combos, so the optimizer cannot over-allocate to MMFs in high
short-rate regimes. Defaults reflect institutional wealth practice for
international portfolios (Brazilian offshore structures):

- conservative: 30% max cash — defensive tolerance
- moderate:     20% max cash — balanced tolerance
- growth:       15% max cash — aggressive tolerance

Operator can override via `POST /set-override` at any time (A26.2 flow);
this migration only establishes the default where no override exists.

Idempotent: only touches rows where override_max IS NULL.

Revision ID: 0161_default_cash_caps
Revises: 0160_approve_mmf_for_canonical_org
"""
from __future__ import annotations

from alembic import op

revision = "0161_default_cash_caps"
down_revision = "0160_approve_mmf_for_canonical_org"
branch_labels = None
depends_on = None

DEFAULTS: dict[str, float] = {
    "conservative": 0.30,
    "moderate": 0.20,
    "growth": 0.15,
}


def upgrade() -> None:
    for profile, cap in DEFAULTS.items():
        op.execute(
            f"""
            UPDATE strategic_allocation
               SET override_max = {cap}
             WHERE block_id = 'cash'
               AND profile = '{profile}'
               AND override_max IS NULL;
            """
        )


def downgrade() -> None:
    # Clear only the defaults set by this migration (rows where override_max
    # matches the exact default value and no explicit rationale was recorded).
    for profile, cap in DEFAULTS.items():
        op.execute(
            f"""
            UPDATE strategic_allocation
               SET override_max = NULL
             WHERE block_id = 'cash'
               AND profile = '{profile}'
               AND override_max = {cap};
            """
        )
