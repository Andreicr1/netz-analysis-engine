"""add change_summary to prompt_override_versions

Revision ID: f5aca0aa8f32
Revises: 40fbf263e427
Create Date: 2026-03-18 13:41:51.569566
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f5aca0aa8f32"
down_revision: str | None = "40fbf263e427"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "prompt_override_versions",
        sa.Column("change_summary", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("prompt_override_versions", "change_summary")
