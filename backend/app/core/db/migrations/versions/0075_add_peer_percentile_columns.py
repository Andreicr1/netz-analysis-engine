"""Add peer percentile columns to fund_risk_metrics.

Revision ID: 0075_peer_percentile
Revises: 0074_widen_audit_action
Create Date: 2026-04-01

Pre-compute peer rankings in risk_calc worker so peer queries are instant-read.
Columns: peer_strategy_label, peer_sharpe_pctl, peer_sortino_pctl,
peer_return_pctl, peer_drawdown_pctl, peer_count.
"""
import sqlalchemy as sa

from alembic import op

revision = "0075_peer_percentile"
down_revision = "0074_widen_audit_action"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fund_risk_metrics",
        sa.Column("peer_strategy_label", sa.Text(), nullable=True),
    )
    op.add_column(
        "fund_risk_metrics",
        sa.Column("peer_sharpe_pctl", sa.Numeric(5, 2), nullable=True),
    )
    op.add_column(
        "fund_risk_metrics",
        sa.Column("peer_sortino_pctl", sa.Numeric(5, 2), nullable=True),
    )
    op.add_column(
        "fund_risk_metrics",
        sa.Column("peer_return_pctl", sa.Numeric(5, 2), nullable=True),
    )
    op.add_column(
        "fund_risk_metrics",
        sa.Column("peer_drawdown_pctl", sa.Numeric(5, 2), nullable=True),
    )
    op.add_column(
        "fund_risk_metrics",
        sa.Column("peer_count", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fund_risk_metrics", "peer_count")
    op.drop_column("fund_risk_metrics", "peer_drawdown_pctl")
    op.drop_column("fund_risk_metrics", "peer_return_pctl")
    op.drop_column("fund_risk_metrics", "peer_sortino_pctl")
    op.drop_column("fund_risk_metrics", "peer_sharpe_pctl")
    op.drop_column("fund_risk_metrics", "peer_strategy_label")
