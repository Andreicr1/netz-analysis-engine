"""add approved_by, approved_at, rejection_reason to dd_reports

Revision ID: 0021_dd_approval
Revises: 0020_wealth_docs
Create Date: 2026-03-19 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_dd_approval"
down_revision: str | None = "0020_wealth_docs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("dd_reports", sa.Column("approved_by", sa.String(255), nullable=True))
    op.add_column("dd_reports", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("dd_reports", sa.Column("rejection_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("dd_reports", "rejection_reason")
    op.drop_column("dd_reports", "approved_at")
    op.drop_column("dd_reports", "approved_by")
