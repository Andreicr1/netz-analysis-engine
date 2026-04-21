"""Add volatility_garch and cvar_95_conditional to fund_risk_metrics.

BL-9: CVaR conditional on stress regime
BL-11: GARCH(1,1) conditional volatility
"""

revision = "0058"
down_revision = "0057_sec_fund_classes"

import sqlalchemy as sa

from alembic import op


def upgrade() -> None:
    op.add_column(
        "fund_risk_metrics",
        sa.Column("volatility_garch", sa.Numeric(10, 6), nullable=True),
    )
    op.add_column(
        "fund_risk_metrics",
        sa.Column("cvar_95_conditional", sa.Numeric(10, 6), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fund_risk_metrics", "cvar_95_conditional")
    op.drop_column("fund_risk_metrics", "volatility_garch")
