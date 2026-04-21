"""Add vintage_year to sec_manager_funds.

Revision ID: 0073_add_vintage_year
Revises: 0072_add_investment_geography
Create Date: 2026-03-30

Back-fills vintage_year by extracting 4-digit years from fund_name via regex.
Matches patterns like "Fund IX 2019", "KKR NA XII (2022)", "Fund III, L.P. - 2018".
"""
import sqlalchemy as sa

from alembic import op

revision = "0073_add_vintage_year"
down_revision = "0072_add_investment_geography"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sec_manager_funds",
        sa.Column("vintage_year", sa.Integer(), nullable=True),
    )
    # Back-fill: extract 4-digit year from fund_name via regex
    op.execute("""
        UPDATE sec_manager_funds
        SET vintage_year = (
            regexp_match(fund_name, '\\b(19[89]\\d|20[012]\\d)\\b')
        )[1]::integer
        WHERE fund_name ~ '\\b(19[89]\\d|20[012]\\d)\\b'
    """)
    # Index for catalog sort/filter
    op.create_index(
        "ix_sec_manager_funds_vintage_year",
        "sec_manager_funds",
        ["vintage_year"],
        postgresql_where=sa.text("vintage_year IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_sec_manager_funds_vintage_year", table_name="sec_manager_funds")
    op.drop_column("sec_manager_funds", "vintage_year")
