"""Add fund count columns to sec_managers from Form ADV Section 7B."""

import sqlalchemy as sa

from alembic import op

revision = "0051_sec_mgr_fund_cols"
down_revision = "0050_sec_13f_cik_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sec_managers", sa.Column("private_fund_count", sa.Integer))
    op.add_column("sec_managers", sa.Column("hedge_fund_count", sa.Integer))
    op.add_column("sec_managers", sa.Column("pe_fund_count", sa.Integer))
    op.add_column("sec_managers", sa.Column("vc_fund_count", sa.Integer))
    op.add_column("sec_managers", sa.Column("real_estate_fund_count", sa.Integer))
    op.add_column("sec_managers", sa.Column("securitized_fund_count", sa.Integer))
    op.add_column("sec_managers", sa.Column("liquidity_fund_count", sa.Integer))
    op.add_column("sec_managers", sa.Column("other_fund_count", sa.Integer))
    op.add_column("sec_managers", sa.Column("total_private_fund_assets", sa.BigInteger))
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sec_managers_private_fund_count "
        "ON sec_managers (private_fund_count) WHERE private_fund_count > 0",
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sec_managers_registration_status "
        "ON sec_managers (registration_status)",
    )


def downgrade() -> None:
    op.drop_index("idx_sec_managers_private_fund_count", "sec_managers")
    op.drop_index("idx_sec_managers_registration_status", "sec_managers")
    op.drop_column("sec_managers", "total_private_fund_assets")
    op.drop_column("sec_managers", "other_fund_count")
    op.drop_column("sec_managers", "liquidity_fund_count")
    op.drop_column("sec_managers", "securitized_fund_count")
    op.drop_column("sec_managers", "real_estate_fund_count")
    op.drop_column("sec_managers", "vc_fund_count")
    op.drop_column("sec_managers", "pe_fund_count")
    op.drop_column("sec_managers", "hedge_fund_count")
    op.drop_column("sec_managers", "private_fund_count")
