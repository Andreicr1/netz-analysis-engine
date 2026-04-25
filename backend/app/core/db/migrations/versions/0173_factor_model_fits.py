"""factor_model_fits — table for IPCA / Kelly-Pruitt-Su fit results.

Output table for the ``ipca_estimation`` worker (lock 900_092). Stores
per-fit metadata (engine, universe_hash, k_factors), the resulting
gamma_loadings + factor_returns JSONB, plus convergence diagnostics
(converged, n_iterations, oos_r_squared). Consumed downstream by the
quant cascade for factor exposures and risk decomposition.

History
-------
Originally authored 2026-04-20 in the wrong path
(``backend/alembic/versions/``) with ``revision = '0172_factor_model_fits'``,
which collided with the legitimate ``0172_add_intraday_market_ticks``
(both declared ``down_revision = '0171_equity_characteristics_monthly'``).
The orphan never executed because alembic's ``script_location`` points
at ``app/core/db/migrations/versions/``. Renumbered to 0173 and moved
into the canonical path on 2026-04-24 — see commit history for details.

Revision ID: 0173_factor_model_fits
Revises: 0172_add_intraday_market_ticks
Create Date: 2026-04-20

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0173_factor_model_fits'
down_revision = '0172_add_intraday_market_ticks'
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
