"""esma_securities — FIRDS share-class identity table.

PR-Q11B Phase 1.2. Creates ``esma_securities`` with real ISINs from FIRDS
FULINS_C, linked to ``esma_funds`` via ``fund_lei``. One fund LEI → many
share-class ISINs.

Q11B minimal shape: no OpenFIGI fields, no Tiingo fields, no provider-symbol
storage. Q11C will ALTER TABLE ADD COLUMN to extend.

Optional seed from ``esma_isin_ticker_map`` if it exists with real ISINs.

Revision ID: 0181_create_esma_securities
Revises: 0180_esma_funds_lei_compat
Create Date: 2026-04-26
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0181_create_esma_securities"
down_revision: str | None = "0180_esma_funds_lei_compat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE esma_securities (
            isin                    text PRIMARY KEY,
            fund_lei                text NOT NULL REFERENCES esma_funds(lei) ON DELETE CASCADE,
            full_name               text NOT NULL,
            cfi_code                text,
            currency                text,
            mic                     text,
            firds_file_url          text,
            firds_publication_date  date,
            first_seen_at           timestamptz NOT NULL DEFAULT now(),
            last_seen_at            timestamptz NOT NULL DEFAULT now(),
            data_fetched_at         timestamptz NOT NULL DEFAULT now(),
            is_active               boolean NOT NULL DEFAULT TRUE,
            CHECK (isin ~ '^[A-Z]{2}[A-Z0-9]{9}[0-9]$'),
            CHECK (fund_lei ~ '^[A-Z0-9]{20}$')
        )
    """)
    op.execute("CREATE INDEX idx_esma_securities_fund_lei ON esma_securities(fund_lei)")
    op.execute(
        "CREATE INDEX idx_esma_securities_fund_lei_isin "
        "ON esma_securities(fund_lei, isin)"
    )
    op.execute(
        "CREATE INDEX idx_esma_securities_active_fund "
        "ON esma_securities(fund_lei) WHERE is_active"
    )

    # Optional seed from esma_isin_ticker_map — only rows with valid ISINs
    op.execute("""
        INSERT INTO esma_securities(isin, fund_lei, full_name, is_active)
        SELECT m.isin, m.fund_lei, f.fund_name, true
        FROM esma_isin_ticker_map m
        JOIN esma_funds f ON f.lei = m.fund_lei
        WHERE m.isin ~ '^[A-Z]{2}[A-Z0-9]{9}[0-9]$'
          AND m.fund_lei IS NOT NULL
        ON CONFLICT (isin) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS esma_securities")
