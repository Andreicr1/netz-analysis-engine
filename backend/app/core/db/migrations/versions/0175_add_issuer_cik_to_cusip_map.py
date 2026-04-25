"""Add issuer_cik column to sec_cusip_ticker_map.

The column was originally added manually (ad-hoc ALTER TABLE) on the
dev DB to support the CUSIP→CIK lookup chain consumed by PR-Q4.1
holdings enrichment and PR-Q8A-v3 fund characteristics aggregation.
It never made it into an alembic revision, so fresh DBs (CI, new
deployments) lacked the column and the aggregator's JOIN failed with
``UndefinedColumnError`` during integration tests.

This migration formalises the column + its filtered btree index. Live
prod/dev already have both — the IF NOT EXISTS guards make the
migration idempotent there.

Revision ID: 0175_add_issuer_cik_to_cusip_map
Revises: 0174_company_characteristics_monthly
Create Date: 2026-04-25

"""
from alembic import op

revision = '0175_add_issuer_cik_to_cusip_map'
down_revision = '0174_company_characteristics_monthly'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE sec_cusip_ticker_map
        ADD COLUMN IF NOT EXISTS issuer_cik VARCHAR NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_cusip_map_issuer_cik
        ON sec_cusip_ticker_map (issuer_cik)
        WHERE issuer_cik IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_cusip_map_issuer_cik")
    op.execute("ALTER TABLE sec_cusip_ticker_map DROP COLUMN IF EXISTS issuer_cik")
