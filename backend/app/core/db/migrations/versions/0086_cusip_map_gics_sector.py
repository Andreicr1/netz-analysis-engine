"""Add gics_sector column to sec_cusip_ticker_map and backfill from 13F holdings.

Maps GICS sector labels (Technology, Healthcare, etc.) from sec_13f_holdings
to the CUSIP ticker map, enabling granular sector display for equity holdings
in N-PORT fact sheets instead of generic "Equity" issuerCat labels.

Backfill uses the most recent report_date per CUSIP-9 from sec_13f_holdings.

Revision ID: 0086_cusip_map_gics_sector
Revises: 0085_fix_13f_sector_mv_and_cusip_queue
Create Date: 2026-04-05 18:00:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0086_cusip_map_gics_sector"
down_revision: str | None = "0085_fix_13f_sector_mv_and_cusip_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add nullable gics_sector column
    op.execute("""
        ALTER TABLE sec_cusip_ticker_map
        ADD COLUMN IF NOT EXISTS gics_sector VARCHAR(50) NULL
    """)

    # Partial index for non-null sectors
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_cusip_map_gics_sector
        ON sec_cusip_ticker_map (gics_sector)
        WHERE gics_sector IS NOT NULL
    """)

    # Backfill from sec_13f_holdings (most recent sector per CUSIP-9)
    op.execute("""
        UPDATE sec_cusip_ticker_map m
        SET gics_sector = sub.sector
        FROM (
            SELECT DISTINCT ON (SUBSTRING(cusip FROM 1 FOR 9))
                SUBSTRING(cusip FROM 1 FOR 9) AS cusip9,
                sector
            FROM sec_13f_holdings
            WHERE sector IS NOT NULL AND sector != ''
            ORDER BY SUBSTRING(cusip FROM 1 FOR 9), report_date DESC
        ) sub
        WHERE m.cusip = sub.cusip9
          AND m.gics_sector IS NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_cusip_map_gics_sector")
    op.execute("ALTER TABLE sec_cusip_ticker_map DROP COLUMN IF EXISTS gics_sector")
