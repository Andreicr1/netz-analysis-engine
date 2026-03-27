"""Add portfolio_views table for Black-Litterman IC views.

Revision ID: a1b2c3d4e5f6
Revises: f5aca0aa8f32
Create Date: 2026-03-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "a1b2c3d4e5f6"
down_revision = "f5aca0aa8f32"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolio_views",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("portfolio_id", UUID(as_uuid=True), sa.ForeignKey("model_portfolios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_instrument_id", UUID(as_uuid=True), nullable=True),
        sa.Column("peer_instrument_id", UUID(as_uuid=True), nullable=True),
        sa.Column("view_type", sa.String(20), nullable=False),
        sa.Column("expected_return", sa.Numeric(8, 6), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("rationale", sa.Text, nullable=True),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_to", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_portfolio_views_portfolio_id", "portfolio_views", ["portfolio_id"])
    op.create_index("ix_portfolio_views_active", "portfolio_views", ["portfolio_id", "effective_from"])

    # RLS policy
    op.execute("""
        ALTER TABLE portfolio_views ENABLE ROW LEVEL SECURITY;
    """)
    op.execute("""
        CREATE POLICY portfolio_views_org_isolation ON portfolio_views
        USING (organization_id = (SELECT current_setting('app.current_organization_id')::uuid));
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS portfolio_views_org_isolation ON portfolio_views")
    op.execute("ALTER TABLE portfolio_views DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_portfolio_views_active", table_name="portfolio_views")
    op.drop_index("ix_portfolio_views_portfolio_id", table_name="portfolio_views")
    op.drop_table("portfolio_views")
