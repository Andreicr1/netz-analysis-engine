"""sync_global_instruments_nport_prospectus

Revision ID: 0070_global_instruments_sync
Revises: 0069_globalize_instruments_nav
Create Date: 2026-03-29

NOTE: Tables instruments_org, sec_fund_prospectus_returns,
sec_fund_prospectus_stats and column sec_nport_holdings.series_id
were originally created via Tiger CLI (Timescale Cloud console).
This migration now creates them via DDL so CI and fresh databases
work correctly. IF NOT EXISTS makes it idempotent for production.
"""

from alembic import op

revision = "0070_global_instruments_sync"
down_revision = "0069_globalize_instruments_nav"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── instruments_org (tenant-scoped selection from global catalog) ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS instruments_org (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id TEXT NOT NULL,
            instrument_id UUID NOT NULL REFERENCES instruments_universe(instrument_id) ON DELETE CASCADE,
            block_id VARCHAR(80) REFERENCES allocation_blocks(block_id),
            approval_status VARCHAR(20) NOT NULL DEFAULT 'pending',
            selected_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_instruments_org_instrument_id
        ON instruments_org (instrument_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_instruments_org_block_id
        ON instruments_org (block_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_instruments_org_organization_id
        ON instruments_org (organization_id)
    """)

    # RLS on instruments_org
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE instruments_org ENABLE ROW LEVEL SECURITY;
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'instruments_org' AND policyname = 'instruments_org_rls'
            ) THEN
                CREATE POLICY instruments_org_rls ON instruments_org
                    USING (organization_id = (SELECT current_setting('app.current_organization_id', true)));
            END IF;
        EXCEPTION WHEN OTHERS THEN NULL;
        END $$
    """)

    # ── sec_fund_prospectus_returns (global, no RLS) ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS sec_fund_prospectus_returns (
            series_id TEXT NOT NULL,
            year SMALLINT NOT NULL,
            annual_return_pct NUMERIC(10, 6) NOT NULL,
            filing_date DATE,
            created_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (series_id, year)
        )
    """)

    # ── sec_fund_prospectus_stats (global, no RLS) ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS sec_fund_prospectus_stats (
            series_id TEXT NOT NULL,
            class_id TEXT NOT NULL DEFAULT '',
            filing_date DATE,
            management_fee_pct NUMERIC(8, 6),
            expense_ratio_pct NUMERIC(8, 6),
            net_expense_ratio_pct NUMERIC(8, 6),
            fee_waiver_pct NUMERIC(8, 6),
            distribution_12b1_pct NUMERIC(8, 6),
            acquired_fund_fees_pct NUMERIC(8, 6),
            other_expenses_pct NUMERIC(8, 6),
            portfolio_turnover_pct NUMERIC,
            expense_example_1y NUMERIC,
            expense_example_3y NUMERIC,
            expense_example_5y NUMERIC,
            expense_example_10y NUMERIC,
            bar_chart_best_qtr_pct NUMERIC(10, 6),
            bar_chart_worst_qtr_pct NUMERIC(10, 6),
            bar_chart_ytd_pct NUMERIC(10, 6),
            avg_annual_return_1y NUMERIC(10, 6),
            avg_annual_return_5y NUMERIC(10, 6),
            avg_annual_return_10y NUMERIC(10, 6),
            created_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (series_id, class_id)
        )
    """)

    # ── sec_nport_holdings.series_id column (if missing) ──
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE sec_nport_holdings ADD COLUMN IF NOT EXISTS series_id TEXT;
        EXCEPTION WHEN OTHERS THEN NULL;
        END $$
    """)


def downgrade() -> None:
    # No-op — tables remain for safety.
    pass
