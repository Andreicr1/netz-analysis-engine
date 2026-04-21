"""factor_model_fits

Revision ID: 0172_factor_model_fits
Revises: 0171_equity_characteristics_monthly
Create Date: 2026-04-20

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0172_factor_model_fits'
down_revision = '0171_equity_characteristics_monthly'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table('factor_model_fits',
        sa.Column('fit_id', sa.UUID(), nullable=False),
        sa.Column('engine', sa.String(length=32), nullable=False),
        sa.Column('fit_date', sa.Date(), nullable=False),
        sa.Column('universe_hash', sa.String(length=64), nullable=False),
        sa.Column('k_factors', sa.Integer(), nullable=False),
        sa.Column('gamma_loadings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('factor_returns', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('oos_r_squared', sa.Numeric(), nullable=True),
        sa.Column('converged', sa.Boolean(), nullable=False),
        sa.Column('n_iterations', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('fit_id')
    )
    
    # Indexes for queries
    op.create_index(
        'ix_factor_model_fits_lookup',
        'factor_model_fits',
        ['engine', 'universe_hash', 'converged', 'fit_date'],
        unique=False
    )

def downgrade() -> None:
    op.drop_index('ix_factor_model_fits_lookup', table_name='factor_model_fits')
    op.drop_table('factor_model_fits')
