"""Enrich sec_registered_funds with N-CEN operational data.

Adds classification flags, fees, performance, AUM/NAV, and operational
columns from EDGAR N-CEN filings. Applies to mutual_fund + closed_end only
(ETF/BDC/MMF migrated to dedicated tables in 0064).

Revision ID: 0065_enrich_registered_funds_ncen
Revises: 0064_etf_bdc_mmf_tables
Create Date: 2026-03-28
"""

from alembic import op
import sqlalchemy as sa

revision = "0065_enrich_registered_funds_ncen"
down_revision = "0064_etf_bdc_mmf_tables"
branch_labels = None
depends_on = None

_NEW_COLUMNS = [
    # Classification flags
    ("is_index", sa.Boolean()),
    ("is_non_diversified", sa.Boolean()),
    ("is_target_date", sa.Boolean()),
    ("is_fund_of_fund", sa.Boolean()),
    ("is_master_feeder", sa.Boolean()),
    ("lei", sa.String()),
    # Costs
    ("management_fee", sa.Numeric(8, 4)),
    ("net_operating_expenses", sa.Numeric(8, 4)),
    ("has_expense_limit", sa.Boolean()),
    ("has_expense_waived", sa.Boolean()),
    # Performance
    ("return_before_fees", sa.Numeric(8, 4)),
    ("return_after_fees", sa.Numeric(8, 4)),
    ("return_stdv_before_fees", sa.Numeric(8, 4)),
    ("return_stdv_after_fees", sa.Numeric(8, 4)),
    # AUM & NAV
    ("monthly_avg_net_assets", sa.Numeric(20, 2)),
    ("daily_avg_net_assets", sa.Numeric(20, 2)),
    ("nav_per_share", sa.Numeric(12, 4)),
    ("market_price_per_share", sa.Numeric(12, 4)),
    # Operational
    ("is_sec_lending_authorized", sa.Boolean()),
    ("did_lend_securities", sa.Boolean()),
    ("has_line_of_credit", sa.Boolean()),
    ("has_interfund_borrowing", sa.Boolean()),
    ("has_swing_pricing", sa.Boolean()),
    ("did_pay_broker_research", sa.Boolean()),
    # N-CEN metadata
    ("ncen_accession_number", sa.String()),
    ("ncen_report_date", sa.Date()),
    ("ncen_fund_id", sa.String()),
]


def upgrade() -> None:
    for col_name, col_type in _NEW_COLUMNS:
        op.add_column("sec_registered_funds", sa.Column(col_name, col_type, nullable=True))


def downgrade() -> None:
    for col_name, _ in reversed(_NEW_COLUMNS):
        op.drop_column("sec_registered_funds", col_name)
