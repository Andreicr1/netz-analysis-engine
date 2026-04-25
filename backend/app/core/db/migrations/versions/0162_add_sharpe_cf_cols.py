"""Add Cornish-Fisher robust Sharpe columns to fund_risk_metrics.

Adds five nullable NUMERIC columns populated by the `global_risk_metrics`
worker (lock 900_071) once PR-Q1 (G1 Robust Sharpe) ships. Values are read
by `scoring_service.risk_adjusted_return` only when the
`wealth.scoring.use_robust_sharpe` ConfigService flag is flipped ON.

Flag default stays `false` at merge; columns can stay NULL safely —
scoring falls back to `sharpe_1y`.

Revision ID: 0162_add_sharpe_cf_cols
Revises: 0161_default_cash_caps
Create Date: 2026-04-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0162_add_sharpe_cf_cols"
down_revision = "0161_default_cash_caps"
branch_labels = None
depends_on = None


_NEW_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("sharpe_cf", sa.Numeric(10, 6)),
    ("sharpe_cf_skew", sa.Numeric(10, 6)),
    ("sharpe_cf_kurt", sa.Numeric(10, 6)),
    ("sharpe_cf_ci_lower", sa.Numeric(10, 6)),
    ("sharpe_cf_ci_upper", sa.Numeric(10, 6)),
)


def upgrade() -> None:
    for name, type_ in _NEW_COLUMNS:
        op.add_column(
            "fund_risk_metrics",
            sa.Column(name, type_, nullable=True),
        )


def downgrade() -> None:
    for name, _ in reversed(_NEW_COLUMNS):
        op.drop_column("fund_risk_metrics", name)
