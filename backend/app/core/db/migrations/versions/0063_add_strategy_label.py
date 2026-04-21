"""Add strategy_label column to fund tables.

Keyword-based strategy classification (Private Credit, Infrastructure,
Growth Equity, ESG Equity, etc.) derived from fund_name + fund_type.
Applied to all three fund universes:
- sec_manager_funds (private funds): 37 categories
- esma_funds (UCITS): 31 categories
- sec_registered_funds (mutual funds / ETFs): 23 categories

Revision ID: 0063_add_strategy_label
Revises: 0062_no_force_rls_embedding_tables
Create Date: 2026-03-28
"""

import sqlalchemy as sa

from alembic import op

revision = "0063_add_strategy_label"
down_revision = "0062_no_force_rls_embedding_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sec_manager_funds", sa.Column("strategy_label", sa.Text(), nullable=True))
    op.add_column("esma_funds", sa.Column("strategy_label", sa.Text(), nullable=True))
    op.add_column("sec_registered_funds", sa.Column("strategy_label", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sec_manager_funds", "strategy_label")
    op.drop_column("esma_funds", "strategy_label")
    op.drop_column("sec_registered_funds", "strategy_label")
