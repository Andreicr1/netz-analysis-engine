"""Add strategy_label column to sec_manager_funds.

Keyword-based strategy classification (Private Credit, Infrastructure,
Growth Equity, etc.) derived from fund_name + fund_type. More granular
than SEC Form ADV's 7 fund_type categories.

Revision ID: 0063_add_strategy_label
Revises: 0062_no_force_rls_embedding_tables
Create Date: 2026-03-28
"""

from alembic import op
import sqlalchemy as sa

revision = "0063_add_strategy_label"
down_revision = "0062_no_force_rls_embedding_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sec_manager_funds", sa.Column("strategy_label", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sec_manager_funds", "strategy_label")
