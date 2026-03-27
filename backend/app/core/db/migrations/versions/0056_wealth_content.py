"""Create wealth_content table for investment outlooks, flash reports, spotlights.

ORG-SCOPED: has organization_id + RLS.
"""

revision = "0056_wealth_content"
down_revision = "0055_model_portfolio_nav"

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID


def upgrade() -> None:
    op.create_table(
        "wealth_content",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("content_type", sa.String(30), nullable=False, index=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("language", sa.String(5), nullable=False, server_default="pt"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("content_md", sa.Text),
        sa.Column("content_data", JSONB),
        sa.Column("storage_path", sa.String(500)),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("approved_by", sa.String(128)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # RLS policy
    op.execute("""
        ALTER TABLE wealth_content ENABLE ROW LEVEL SECURITY;
    """)
    op.execute("""
        CREATE POLICY wealth_content_org_isolation ON wealth_content
        USING (organization_id = (SELECT current_setting('app.current_organization_id')::uuid));
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS wealth_content_org_isolation ON wealth_content;")
    op.execute("ALTER TABLE wealth_content DISABLE ROW LEVEL SECURITY;")
    op.drop_table("wealth_content")
