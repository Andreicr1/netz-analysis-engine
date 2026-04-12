"""fund risk audit columns

Revision ID: 0109
Revises: 0108_terminal_oms_hardening
Create Date: 2026-04-10 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0109'
down_revision: Union[str, None] = '0108_terminal_oms_hardening'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('fund_risk_metrics', sa.Column('vol_model', sa.String(length=50), nullable=True))
    op.add_column('fund_risk_metrics', sa.Column('data_quality_flags', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=True))


def downgrade() -> None:
    op.drop_column('fund_risk_metrics', 'data_quality_flags')
    op.drop_column('fund_risk_metrics', 'vol_model')
