"""Add CVaR EVT columns to fund_risk_metrics.

Adds cvar_99_evt, cvar_999_evt, and evt_xi_shape to fund_risk_metrics.
Reference: PR-Q6 and EDHEC Spec §4.
"""

import sqlalchemy as sa
from alembic import op

revision = "0169_add_cvar_evt_cols"
down_revision = "0168_expand_canonical_map_fsds_q1_2025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fund_risk_metrics",
        sa.Column("cvar_99_evt", sa.Numeric(precision=12, scale=6), nullable=True),
    )
    op.add_column(
        "fund_risk_metrics",
        sa.Column("cvar_999_evt", sa.Numeric(precision=12, scale=6), nullable=True),
    )
    op.add_column(
        "fund_risk_metrics",
        sa.Column("evt_xi_shape", sa.Numeric(precision=12, scale=6), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fund_risk_metrics", "evt_xi_shape")
    op.drop_column("fund_risk_metrics", "cvar_999_evt")
    op.drop_column("fund_risk_metrics", "cvar_99_evt")
