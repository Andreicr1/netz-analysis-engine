"""Add status/decision check constraints for Wealth enums.

Revision ID: 0022_wealth_status
Revises: 0021_dd_approval
Create Date: 2026-03-19 23:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0022_wealth_status"
down_revision: Union[str, None] = "0021_dd_approval"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_dd_reports_status",
        "dd_reports",
        "status IN ('draft', 'generating', 'pending_approval', 'approved', 'rejected', 'failed')",
    )
    op.create_check_constraint(
        "ck_universe_approvals_decision",
        "universe_approvals",
        "decision IN ('pending', 'approved', 'watchlist', 'rejected')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_universe_approvals_decision", "universe_approvals", type_="check")
    op.drop_constraint("ck_dd_reports_status", "dd_reports", type_="check")
