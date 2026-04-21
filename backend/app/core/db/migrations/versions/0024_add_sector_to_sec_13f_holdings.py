"""Add sector column to sec_13f_holdings.

Industry sector (GICS classification) for each holding, resolved via
SIC code mapping, OpenFIGI/yfinance, or issuer_name heuristic.
Replaces the incorrect use of asset_class (COM/CALL/PUT) for sector
aggregation in get_sector_aggregation().

depends_on: 0023 (sec_data_providers_tables).
"""

import sqlalchemy as sa

from alembic import op

revision = "0024_sec_13f_sector"
down_revision = "0023_sec_data_providers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sec_13f_holdings", sa.Column("sector", sa.Text(), nullable=True))
    op.create_index(
        "idx_sec_13f_holdings_sector",
        "sec_13f_holdings",
        ["cik", "report_date", "sector"],
    )


def downgrade() -> None:
    op.drop_index("idx_sec_13f_holdings_sector", table_name="sec_13f_holdings")
    op.drop_column("sec_13f_holdings", "sector")
