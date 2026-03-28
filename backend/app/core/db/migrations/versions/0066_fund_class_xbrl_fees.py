"""Add OEF XBRL fee/performance columns to sec_fund_classes.

Sourced from N-CSR inline XBRL filings using the OEF taxonomy.
Each share class has its own expense ratio, returns, and AUM.

Revision ID: 0066_fund_class_xbrl_fees
Revises: 0065_enrich_registered_funds_ncen
Create Date: 2026-03-28
"""

from alembic import op
import sqlalchemy as sa

revision = "0066_fund_class_xbrl_fees"
down_revision = "0065_enrich_registered_funds_ncen"
branch_labels = None
depends_on = None

_NEW_COLUMNS = [
    ("expense_ratio_pct", sa.Numeric(10, 6)),
    ("advisory_fees_paid", sa.Numeric(20, 2)),
    ("expenses_paid", sa.Numeric(12, 2)),
    ("avg_annual_return_pct", sa.Numeric(10, 6)),
    ("net_assets", sa.Numeric(20, 2)),
    ("holdings_count", sa.Integer()),
    ("portfolio_turnover_pct", sa.Numeric(10, 6)),
    ("fund_name", sa.String()),
    ("perf_inception_date", sa.Date()),
    ("xbrl_accession", sa.String()),
    ("xbrl_period_end", sa.Date()),
]


def upgrade() -> None:
    for col_name, col_type in _NEW_COLUMNS:
        op.add_column("sec_fund_classes", sa.Column(col_name, col_type, nullable=True))


def downgrade() -> None:
    for col_name, _ in reversed(_NEW_COLUMNS):
        op.drop_column("sec_fund_classes", col_name)
