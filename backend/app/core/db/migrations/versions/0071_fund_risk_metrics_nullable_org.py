"""fund_risk_metrics: make organization_id nullable for global risk metrics

Revision ID: 0071_fund_risk_metrics_nullable_org
Revises: 0070_global_instruments_sync
Create Date: 2026-03-29

Global risk metrics worker (run_global_risk_metrics) computes CVaR, Sharpe,
volatility, momentum for ALL active instruments — writes with org_id = NULL.
Org-scoped run_risk_calc can later overwrite specific rows with org_id + DTW.
"""

from alembic import op

revision = "0071_fund_risk_metrics_nullable_org"
down_revision = "0070_global_instruments_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "fund_risk_metrics",
        "organization_id",
        nullable=True,
    )


def downgrade() -> None:
    op.execute("UPDATE fund_risk_metrics SET organization_id = '00000000-0000-0000-0000-000000000000' WHERE organization_id IS NULL")
    op.alter_column(
        "fund_risk_metrics",
        "organization_id",
        nullable=False,
    )
