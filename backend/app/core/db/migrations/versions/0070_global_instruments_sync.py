"""sync_global_instruments_nport_prospectus

Revision ID: 0070_global_instruments_sync
Revises: 0069_globalize_instruments_nav
Create Date: 2026-03-29

NOTE: Tables instruments_org, sec_fund_prospectus_returns,
sec_fund_prospectus_stats and column sec_nport_holdings.series_id
were created directly via Tiger CLI (Timescale Cloud console).
This migration is a stub to keep the Alembic chain consistent.
The actual CREATE TABLE / CREATE INDEX / ALTER TABLE were already
executed on Timescale Cloud.
"""

revision = "0070_global_instruments_sync"
down_revision = "0069_globalize_instruments_nav"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tables already exist — created directly on Timescale Cloud.
    pass


def downgrade() -> None:
    # No-op — tables remain.
    pass
