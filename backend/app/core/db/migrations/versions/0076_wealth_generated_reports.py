"""wealth_generated_reports — persistent PDF report registry

Revision ID: 0076_wealth_generated_reports
Revises: 0075_peer_percentile
Create Date: 2026-04-01 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0076_wealth_generated_reports"
down_revision: str | None = "0075_peer_percentile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wealth_generated_reports",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("portfolio_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("report_type", sa.String(50), nullable=False, index=True),
        sa.Column("job_id", sa.String(128), nullable=False, unique=True),
        sa.Column("storage_path", sa.String(800), nullable=False),
        sa.Column("display_filename", sa.String(300), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("generated_by", sa.String(128), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="completed"),
    )
    op.create_index(
        "ix_wealth_gen_reports_org_portfolio",
        "wealth_generated_reports",
        ["organization_id", "portfolio_id"],
    )
    op.create_index(
        "ix_wealth_gen_reports_org_type",
        "wealth_generated_reports",
        ["organization_id", "report_type", "generated_at"],
    )


def downgrade() -> None:
    op.drop_table("wealth_generated_reports")
