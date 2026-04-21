"""Add backtest_result and stress_result JSONB columns to model_portfolios.

Stores latest backtest/stress computation results on the portfolio row.
Read by PK only — no JSONB index needed.

Revision ID: 0081_model_portfolio_results
Revises: 0080_fix_mv_unified_funds_manager
Create Date: 2026-04-02 20:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0081_model_portfolio_results"
down_revision: str | None = "0080_fix_mv_unified_funds_manager"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_portfolios",
        sa.Column("backtest_result", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "model_portfolios",
        sa.Column("stress_result", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_portfolios", "stress_result")
    op.drop_column("model_portfolios", "backtest_result")
