"""add financial term fields to deals

Revision ID: 636e0de04bf7
Revises: f5aca0aa8f32
Create Date: 2026-03-18

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "636e0de04bf7"
down_revision = "f5aca0aa8f32"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deals", sa.Column("tenor_months", sa.Integer(), nullable=True))
    op.add_column("deals", sa.Column("spread_bps", sa.Integer(), nullable=True))
    op.add_column("deals", sa.Column("covenant_type", sa.String(length=100), nullable=True))
    op.add_column("deals", sa.Column("covenant_frequency", sa.String(length=50), nullable=True))
    op.add_column("deals", sa.Column("collateral_description", sa.Text(), nullable=True))
    op.add_column("deals", sa.Column("ltv_ratio", sa.Numeric(precision=5, scale=4), nullable=True))
    op.add_column("deals", sa.Column("agreement_language", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("deals", "agreement_language")
    op.drop_column("deals", "ltv_ratio")
    op.drop_column("deals", "collateral_description")
    op.drop_column("deals", "covenant_frequency")
    op.drop_column("deals", "covenant_type")
    op.drop_column("deals", "spread_bps")
    op.drop_column("deals", "tenor_months")
