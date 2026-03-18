"""merge heads 0011 and 0019

Revision ID: 40fbf263e427
Revises: 0011, 0019
Create Date: 2026-03-18 13:41:13.224181
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '40fbf263e427'
down_revision: Union[str, None] = ('0011', '0019')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
