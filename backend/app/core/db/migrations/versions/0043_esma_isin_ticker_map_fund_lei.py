"""Add fund_lei column to esma_isin_ticker_map.

Links real ISINs (from FIRDS FULINS_C) back to the fund LEI
stored in esma_funds.isin, enabling the Phase 2 ticker resolution
to work with real ISINs instead of LEIs.

depends_on: 0042 (bis_imf_hypertables).
"""

import sqlalchemy as sa

from alembic import op

revision = "0043_esma_isin_ticker_fund_lei"
down_revision = "0042_bis_imf_hypertables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "esma_isin_ticker_map",
        sa.Column("fund_lei", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_esma_isin_ticker_map_fund_lei",
        "esma_isin_ticker_map",
        ["fund_lei"],
    )


def downgrade() -> None:
    op.drop_index("ix_esma_isin_ticker_map_fund_lei", table_name="esma_isin_ticker_map")
    op.drop_column("esma_isin_ticker_map", "fund_lei")
