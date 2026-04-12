"""Seed na_equity_large allocation block for SPY benchmark.

The alternatives analytics pass fetches SPY returns via
``benchmark_nav WHERE block_id = 'na_equity_large'``.  This block
was defined in blocks.yaml but never seeded into allocation_blocks,
so benchmark_ingest never downloaded SPY NAV data and all alt-specific
metrics (correlation, capture, crisis alpha) returned NULL.

Revision ID: 0126_seed_na_equity_large_block
Revises: 0125_add_alternatives_risk_metrics
Create Date: 2026-04-12
"""
from __future__ import annotations

from alembic import op

revision = "0126_seed_na_equity_large_block"
down_revision = "0125_add_alternatives_risk_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO allocation_blocks
            (block_id, geography, asset_class, display_name, benchmark_ticker)
        VALUES
            ('na_equity_large', 'north_america', 'equity',
             'North America Large Cap Equity', 'SPY')
        ON CONFLICT (block_id) DO NOTHING
    """)


def downgrade() -> None:
    op.execute(
        "DELETE FROM allocation_blocks WHERE block_id = 'na_equity_large'"
    )
