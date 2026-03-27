"""merge three heads into single lineage

Revision ID: d1e2f3a4b5c6
Revises: 636e0de04bf7, a1b2c3d4e5f6, c3d4e5f6a7b8
Create Date: 2026-03-18 18:00:00.000000
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "d1e2f3a4b5c6"
down_revision: str | None = ("636e0de04bf7", "a1b2c3d4e5f6", "c3d4e5f6a7b8")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
