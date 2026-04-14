"""add signal_breakdown to macro_regime_snapshot

Revision ID: 0110
Revises: 0109
Create Date: 2026-04-14 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0110'
down_revision: Union[str, None] = '0109'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'macro_regime_snapshot',
        sa.Column('signal_breakdown', postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('macro_regime_snapshot', 'signal_breakdown')
