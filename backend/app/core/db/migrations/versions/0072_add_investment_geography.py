"""Add investment_geography to instruments_universe

Revision ID: 0072_add_investment_geography
Revises: 0071_fund_risk_metrics_nullable_org
Create Date: 2026-03-31

3-layer classifier populates this column:
  Layer 1: N-PORT ISIN country codes (real allocation data)
  Layer 2: strategy_label + fund_name keyword matching
  Layer 3: Default by fund_type/domicile
"""

import sqlalchemy as sa

from alembic import op

revision = "0072_add_investment_geography"
down_revision = "0071_fund_risk_metrics_nullable_org"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "instruments_universe",
        sa.Column("investment_geography", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_instruments_universe_investment_geography",
        "instruments_universe",
        ["investment_geography"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_instruments_universe_investment_geography",
        table_name="instruments_universe",
    )
    op.drop_column("instruments_universe", "investment_geography")
