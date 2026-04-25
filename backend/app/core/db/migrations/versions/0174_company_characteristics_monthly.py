"""company_characteristics_monthly — stock-level fundamentals from XBRL.

Layer 1 of the Option B fund characteristics pipeline (issue #289).
CIK-keyed table storing 8 raw components + 3 derived Kelly-Pruitt-Su
fundamentals-only chars per fiscal period. Layer 2 (PR-Q8A-v3)
aggregates these via N-PORT holdings to produce fund-level chars in
``equity_characteristics_monthly``.

Price-dependent chars (size, B/M, momentum) are NOT stored here — they
are computed at the fund layer using N-PORT value_usd + fund NAV.

Revision ID: 0174_company_characteristics_monthly
Revises: 0173_factor_model_fits
Create Date: 2026-04-25

"""
import sqlalchemy as sa
from alembic import op

revision = '0174_company_characteristics_monthly'
down_revision = '0173_factor_model_fits'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'company_characteristics_monthly',
        sa.Column('cik', sa.BigInteger(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('fp', sa.Text(), nullable=True),
        # Raw components
        sa.Column('book_equity', sa.Numeric(), nullable=True),
        sa.Column('total_assets', sa.Numeric(), nullable=True),
        sa.Column('net_income_ttm', sa.Numeric(), nullable=True),
        sa.Column('revenue', sa.Numeric(), nullable=True),
        sa.Column('cost_of_revenue', sa.Numeric(), nullable=True),
        sa.Column('gross_profit', sa.Numeric(), nullable=True),
        sa.Column('capex_ttm', sa.Numeric(), nullable=True),
        sa.Column('ppe_prior', sa.Numeric(), nullable=True),
        sa.Column('shares_outstanding', sa.Numeric(), nullable=True),
        # Derived characteristics (fundamentals-only)
        sa.Column('quality_roa', sa.Numeric(), nullable=True),
        sa.Column('investment_growth', sa.Numeric(), nullable=True),
        sa.Column('profitability_gross', sa.Numeric(), nullable=True),
        # Audit
        sa.Column('source_filing_date', sa.Date(), nullable=True),
        sa.Column('source_accn', sa.Text(), nullable=True),
        sa.Column('computed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('cik', 'period_end'),
    )

    # Convert to hypertable
    op.execute("""
        SELECT create_hypertable(
            'company_characteristics_monthly',
            'period_end',
            chunk_time_interval => INTERVAL '1 year',
            if_not_exists => TRUE
        );
    """)

    # Indexes
    op.create_index(
        'idx_ccm_period_end',
        'company_characteristics_monthly',
        [sa.text('period_end DESC')],
    )
    op.create_index(
        'idx_ccm_cik',
        'company_characteristics_monthly',
        ['cik'],
    )


def downgrade() -> None:
    op.drop_index('idx_ccm_cik', table_name='company_characteristics_monthly')
    op.drop_index('idx_ccm_period_end', table_name='company_characteristics_monthly')
    op.drop_table('company_characteristics_monthly')
