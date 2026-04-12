"""Seed 7 Fixed Income allocation blocks with benchmark tickers.

Revision ID: 0122_add_fi_benchmark_blocks
Revises: 0121_tiingo_default_source
Create Date: 2026-04-12

These blocks enable the benchmark_ingest worker to download FI index NAV
data (via Tiingo) for the empirical duration and credit beta regressions
in the upcoming FI Quant Engine. ON CONFLICT DO NOTHING avoids duplicates
if blocks were already created manually.
"""
from __future__ import annotations

from alembic import op

revision = "0122_add_fi_benchmark_blocks"
down_revision = "0121_tiingo_default_source"
branch_labels = None
depends_on = None

_FI_BLOCKS = [
    ("fi_aggregate", "us", "fixed_income", "US Aggregate Bond", "AGG"),
    ("fi_ig_corporate", "us", "fixed_income", "Investment Grade Corporate", "LQD"),
    ("fi_high_yield", "us", "fixed_income", "High Yield Corporate", "HYG"),
    ("fi_tips", "us", "fixed_income", "Treasury Inflation-Protected", "TIP"),
    ("fi_govt", "us", "fixed_income", "US Government Bond", "GOVT"),
    ("fi_em_debt", "em", "fixed_income", "Emerging Market Debt", "EMB"),
    ("fi_short_term", "us", "fixed_income", "1-3 Year Treasury", "SHY"),
]


def upgrade() -> None:
    for block_id, geo, asset_class, display, ticker in _FI_BLOCKS:
        op.execute(
            f"""
            INSERT INTO allocation_blocks
                (block_id, geography, asset_class, display_name, benchmark_ticker)
            VALUES
                ('{block_id}', '{geo}', '{asset_class}', '{display}', '{ticker}')
            ON CONFLICT (block_id) DO NOTHING
            """
        )


def downgrade() -> None:
    block_ids = ", ".join(f"'{b[0]}'" for b in _FI_BLOCKS)
    op.execute(f"DELETE FROM allocation_blocks WHERE block_id IN ({block_ids})")
