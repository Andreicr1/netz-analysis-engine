"""Add momentum signal columns to fund_risk_metrics.

Pre-computed by risk_calc worker: RSI(14), Bollinger position,
NAV momentum, flow momentum, and blended score.
Removes in-request momentum computation from /funds/scoring route.

Revision ID: 0035_fund_risk_metrics_momentum
Revises: 0034_appendonly_hypertables
"""

import sqlalchemy as sa
from alembic import op

revision = "0035_fund_risk_metrics_momentum"
down_revision = "0034_appendonly_hypertables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fund_risk_metrics", sa.Column("rsi_14", sa.Numeric(5, 2), nullable=True))
    op.add_column("fund_risk_metrics", sa.Column("bb_position", sa.Numeric(5, 2), nullable=True))
    op.add_column("fund_risk_metrics", sa.Column("nav_momentum_score", sa.Numeric(5, 2), nullable=True))
    op.add_column("fund_risk_metrics", sa.Column("flow_momentum_score", sa.Numeric(5, 2), nullable=True))
    op.add_column("fund_risk_metrics", sa.Column("blended_momentum_score", sa.Numeric(5, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("fund_risk_metrics", "blended_momentum_score")
    op.drop_column("fund_risk_metrics", "flow_momentum_score")
    op.drop_column("fund_risk_metrics", "nav_momentum_score")
    op.drop_column("fund_risk_metrics", "bb_position")
    op.drop_column("fund_risk_metrics", "rsi_14")
