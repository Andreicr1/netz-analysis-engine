"""Add storage_path and pdf_language to dd_reports

Revision ID: 0077_dd_report_storage_path
Revises: 0076_wealth_generated_reports
Create Date: 2026-04-01 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0077_dd_report_storage_path"
down_revision: str | None = "0076_wealth_generated_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("dd_reports", sa.Column("storage_path", sa.String(800), nullable=True))
    op.add_column("dd_reports", sa.Column("pdf_language", sa.String(5), nullable=True))


def downgrade() -> None:
    op.drop_column("dd_reports", "pdf_language")
    op.drop_column("dd_reports", "storage_path")
