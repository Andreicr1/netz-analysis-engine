"""Tiingo default source label on benchmark_nav and nav_timeseries.

Revision ID: 0121_tiingo_default_source
Revises: 0120_portfolio_construction_runs_cancelled_status
Create Date: 2026-04-12

Only the DEFAULT is changed. Existing rows keep source='yfinance' as a
historical record of which provider ingested them. Future rows written
after this migration carry source='tiingo'.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0121_tiingo_default_source"
down_revision = "0120_portfolio_construction_runs_cancelled_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "benchmark_nav",
        "source",
        server_default=sa.text("'tiingo'"),
    )
    op.alter_column(
        "nav_timeseries",
        "source",
        server_default=sa.text("'tiingo'"),
    )


def downgrade() -> None:
    op.alter_column(
        "benchmark_nav",
        "source",
        server_default=sa.text("'yfinance'"),
    )
    op.alter_column(
        "nav_timeseries",
        "source",
        server_default=sa.text("'yfinance'"),
    )
