"""Exclude phantom sec_fund_classes rows from mv_unified_funds.

sec_fund_classes contains ~10k rows where class_id = series_id —
these are seed artifacts with no ticker, no real class data. They
pollute the catalog with duplicate entries showing no ticker for
well-known funds (e.g. Vanguard Wellington shows 3 rows: 2 real
share classes with tickers + 1 phantom without).

Fix: add WHERE clause to Branch 1 excluding phantom rows.

Revision ID: 0083_mv_unified_funds_exclude_phantoms
Revises: 0082_screening_l1_us_only
Create Date: 2026-04-04 14:00:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0083_mv_unified_funds_exclude_phantoms"
down_revision: str | None = "0082_screening_l1_us_only"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_unified_funds CASCADE;")

    op.execute("""
        CREATE MATERIALIZED VIEW mv_unified_funds AS
        SELECT DISTINCT ON (external_id) * FROM (
            WITH geo_logic AS (
                SELECT
                    text_val,
                    CASE
                        WHEN text_val ILIKE '%emerging%' THEN 'Emerging Markets'
                        WHEN text_val ILIKE '%frontier%' THEN 'Emerging Markets'
                        WHEN text_val ILIKE '%china%' THEN 'Emerging Markets'
                        WHEN text_val ILIKE '%india%' THEN 'Emerging Markets'
                        WHEN text_val ILIKE '%latin america%' THEN 'Latin America'
                        WHEN text_val ILIKE '%latam%' THEN 'Latin America'
                        WHEN text_val ILIKE '%brazil%' THEN 'Latin America'
                        WHEN text_val ILIKE '%europe%' THEN 'Europe'
                        WHEN text_val ILIKE '%european%' THEN 'Europe'
                        WHEN text_val ILIKE '%eurozone%' THEN 'Europe'
                        WHEN text_val ILIKE '%asia%' THEN 'Asia Pacific'
                        WHEN text_val ILIKE '%japan%' THEN 'Asia Pacific'
                        WHEN text_val ILIKE '%pacific%' THEN 'Asia Pacific'
                        WHEN text_val ILIKE '%global%' THEN 'Global'
                        WHEN text_val ILIKE '%world%' THEN 'Global'
                        WHEN text_val ILIKE '%international%' THEN 'Global'
                        WHEN text_val ILIKE '%foreign%' THEN 'Global'
                        WHEN text_val ILIKE '%ex-us%' THEN 'Global'
                        WHEN text_val ILIKE '%ex us%' THEN 'Global'
                        ELSE 'US'
                    END as investment_geography
                FROM (
                    SELECT DISTINCT COALESCE(strategy_label, fund_name) as text_val FROM sec_registered_funds
                    UNION SELECT DISTINCT COALESCE(strategy_label, fund_name) FROM sec_etfs
                    UNION SELECT DISTINCT COALESCE(strategy_label, fund_name) FROM sec_bdcs
                    UNION SELECT DISTINCT COALESCE(strategy_label, fund_name) FROM sec_manager_funds
                    UNION SELECT DISTINCT COALESCE(strategy_label, fund_name) FROM esma_funds
                ) t
            )
            -- Branch 1: registered_us (mutual funds, closed-end, interval)
            SELECT
                'registered_us'::text as universe,
                COALESCE(fc.class_id, fc.series_id, rf.cik)::text as external_id,
                COALESCE(fc.series_name, rf.fund_name)::text as name,
                COALESCE(fc.ticker, rf.ticker)::text as ticker,
                rf.isin::text as isin,
                'US'::text as region,
                rf.fund_type::text as fund_type,
                rf.strategy_label::text as strategy_label,
                COALESCE(NULLIF(rf.total_assets, 0), fc.net_assets, rf.monthly_avg_net_assets)::numeric as aum_usd,
                rf.currency::text as currency,
                rf.domicile::text as domicile,
                m.firm_name::text as manager_name,
                m.crd_number::text as manager_id,
                rf.inception_date as inception_date,
                rf.total_shareholder_accounts as total_shareholder_accounts,
                NULL::integer as investor_count,
                fc.series_id as series_id,
                fc.series_name as series_name,
                fc.class_id as class_id,
                fc.class_name as class_name,
                (rf.last_nport_date IS NOT NULL) as has_holdings,
                (COALESCE(fc.ticker, rf.ticker) IS NOT NULL) as has_nav,
                EXISTS (
                    SELECT 1 FROM sec_13f_holdings h
                    JOIN sec_managers sm ON sm.cik = h.cik
                    WHERE sm.crd_number = rf.crd_number
                    AND h.report_date >= CURRENT_DATE - INTERVAL '180 days'
                ) as has_13f_overlay,
                (SELECT gl.investment_geography FROM geo_logic gl WHERE gl.text_val = COALESCE(rf.strategy_label, rf.fund_name) LIMIT 1) as investment_geography,
                NULL::integer as vintage_year,
                ps.expense_ratio_pct,
                ps.avg_annual_return_1y,
                ps.avg_annual_return_10y,
                rf.is_index,
                rf.is_target_date,
                rf.is_fund_of_fund
            FROM sec_registered_funds rf
            LEFT JOIN sec_fund_classes fc ON rf.cik = fc.cik
                AND fc.class_id != fc.series_id  -- exclude phantom rows (seed artifacts with no real class data)
            LEFT JOIN sec_managers m ON rf.crd_number = m.crd_number AND m.crd_number NOT LIKE 'cik_%%'
            LEFT JOIN sec_fund_prospectus_stats ps ON fc.series_id = ps.series_id AND fc.class_id = ps.class_id
            WHERE TRUE
            AND NOT EXISTS (SELECT 1 FROM sec_etfs e WHERE e.series_id = COALESCE(fc.series_id, rf.series_id))
            AND NOT EXISTS (SELECT 1 FROM sec_bdcs b WHERE b.series_id = COALESCE(fc.series_id, rf.series_id))
            AND NOT EXISTS (SELECT 1 FROM sec_money_market_funds mmf WHERE mmf.series_id = COALESCE(fc.series_id, rf.series_id))

            UNION ALL
            -- Branch 2: ETFs
            SELECT
                'registered_us'::text as universe,
                e.series_id::text as external_id,
                e.fund_name::text as name,
                e.ticker::text as ticker,
                e.isin::text as isin,
                'US'::text as region,
                'etf'::text as fund_type,
                e.strategy_label::text as strategy_label,
                e.monthly_avg_net_assets as aum_usd,
                e.currency::text as currency,
                e.domicile::text as domicile,
                NULL::text as manager_name,
                NULL::text as manager_id,
                e.inception_date as inception_date,
                NULL::integer as total_shareholder_accounts,
                NULL::integer as investor_count,
                NULL::text as series_id,
                NULL::text as series_name,
                NULL::text as class_id,
                NULL::text as class_name,
                TRUE as has_holdings,
                (e.ticker IS NOT NULL) as has_nav,
                FALSE as has_13f_overlay,
                (SELECT gl.investment_geography FROM geo_logic gl WHERE gl.text_val = COALESCE(e.strategy_label, e.fund_name) LIMIT 1) as investment_geography,
                NULL::integer as vintage_year,
                ps.expense_ratio_pct,
                ps.avg_annual_return_1y,
                ps.avg_annual_return_10y,
                NULL::boolean as is_index,
                NULL::boolean as is_target_date,
                NULL::boolean as is_fund_of_fund
            FROM sec_etfs e
            LEFT JOIN sec_fund_prospectus_stats ps ON e.series_id = ps.series_id

            UNION ALL
            -- Branch 3: BDCs
            SELECT
                'registered_us'::text as universe,
                b.series_id::text as external_id,
                b.fund_name::text as name,
                b.ticker::text as ticker,
                b.isin::text as isin,
                'US'::text as region,
                'bdc'::text as fund_type,
                b.strategy_label::text as strategy_label,
                b.monthly_avg_net_assets as aum_usd,
                b.currency::text as currency,
                b.domicile::text as domicile,
                NULL::text as manager_name,
                NULL::text as manager_id,
                b.inception_date as inception_date,
                NULL::integer as total_shareholder_accounts,
                NULL::integer as investor_count,
                NULL::text as series_id,
                NULL::text as series_name,
                NULL::text as class_id,
                NULL::text as class_name,
                TRUE as has_holdings,
                (b.ticker IS NOT NULL) as has_nav,
                FALSE as has_13f_overlay,
                (SELECT gl.investment_geography FROM geo_logic gl WHERE gl.text_val = COALESCE(b.strategy_label, b.fund_name) LIMIT 1) as investment_geography,
                NULL::integer as vintage_year,
                ps.expense_ratio_pct,
                ps.avg_annual_return_1y,
                ps.avg_annual_return_10y,
                NULL::boolean as is_index,
                NULL::boolean as is_target_date,
                NULL::boolean as is_fund_of_fund
            FROM sec_bdcs b
            LEFT JOIN sec_fund_prospectus_stats ps ON b.series_id = ps.series_id

            UNION ALL
            -- Branch 4: private_us
            SELECT
                'private_us'::text as universe,
                mf.id::text as external_id,
                mf.fund_name::text as name,
                NULL::text as ticker,
                NULL::text as isin,
                'US'::text as region,
                mf.fund_type::text as fund_type,
                mf.strategy_label::text as strategy_label,
                mf.gross_asset_value::numeric as aum_usd,
                'USD'::text as currency,
                'US'::text as domicile,
                sm.firm_name::text as manager_name,
                sm.crd_number::text as manager_id,
                NULL::date as inception_date,
                NULL::integer as total_shareholder_accounts,
                mf.investor_count as investor_count,
                NULL::text as series_id,
                NULL::text as series_name,
                NULL::text as class_id,
                NULL::text as class_name,
                FALSE as has_holdings,
                FALSE as has_nav,
                EXISTS (
                    SELECT 1 FROM sec_13f_holdings h
                    WHERE h.cik = sm.cik
                    AND h.report_date >= CURRENT_DATE - INTERVAL '180 days'
                ) as has_13f_overlay,
                (SELECT gl.investment_geography FROM geo_logic gl WHERE gl.text_val = COALESCE(mf.strategy_label, mf.fund_name) LIMIT 1) as investment_geography,
                mf.vintage_year as vintage_year,
                NULL::numeric as expense_ratio_pct,
                NULL::numeric as avg_annual_return_1y,
                NULL::numeric as avg_annual_return_10y,
                NULL::boolean as is_index,
                NULL::boolean as is_target_date,
                mf.is_fund_of_funds as is_fund_of_fund
            FROM sec_manager_funds mf
            JOIN sec_managers sm ON mf.crd_number = sm.crd_number

            UNION ALL
            -- Branch 5: ucits_eu
            SELECT
                'ucits_eu'::text as universe,
                ef.isin::text as external_id,
                ef.fund_name::text as name,
                ef.yahoo_ticker::text as ticker,
                ef.isin::text as isin,
                'EU'::text as region,
                ef.fund_type::text as fund_type,
                ef.strategy_label::text as strategy_label,
                NULL::numeric as aum_usd,
                NULL::text as currency,
                ef.domicile::text as domicile,
                em.company_name::text as manager_name,
                em.esma_id::text as manager_id,
                NULL::date as inception_date,
                NULL::integer as total_shareholder_accounts,
                NULL::integer as investor_count,
                NULL::text as series_id,
                NULL::text as series_name,
                NULL::text as class_id,
                NULL::text as class_name,
                FALSE as has_holdings,
                TRUE as has_nav,
                FALSE as has_13f_overlay,
                (SELECT gl.investment_geography FROM geo_logic gl WHERE gl.text_val = COALESCE(ef.strategy_label, ef.fund_name) LIMIT 1) as investment_geography,
                NULL::integer as vintage_year,
                NULL::numeric as expense_ratio_pct,
                NULL::numeric as avg_annual_return_1y,
                NULL::numeric as avg_annual_return_10y,
                NULL::boolean as is_index,
                NULL::boolean as is_target_date,
                NULL::boolean as is_fund_of_fund
            FROM esma_funds ef
            JOIN esma_managers em ON ef.esma_manager_id = em.esma_id
            WHERE ef.yahoo_ticker IS NOT NULL AND ef.yahoo_ticker != ''

            UNION ALL
            -- Branch 6: money_market
            SELECT
                'registered_us'::text as universe,
                mmf.series_id::text as external_id,
                mmf.fund_name::text as name,
                NULL::text as ticker,
                NULL::text as isin,
                'US'::text as region,
                'money_market'::text as fund_type,
                mmf.strategy_label::text as strategy_label,
                mmf.net_assets::numeric as aum_usd,
                mmf.currency::text as currency,
                mmf.domicile::text as domicile,
                mmf.investment_adviser::text as manager_name,
                NULL::text as manager_id,
                NULL::date as inception_date,
                NULL::integer as total_shareholder_accounts,
                NULL::integer as investor_count,
                NULL::text as series_id,
                NULL::text as series_name,
                NULL::text as class_id,
                NULL::text as class_name,
                FALSE as has_holdings,
                FALSE as has_nav,
                FALSE as has_13f_overlay,
                'US'::text as investment_geography,
                NULL::integer as vintage_year,
                NULL::numeric as expense_ratio_pct,
                NULL::numeric as avg_annual_return_1y,
                NULL::numeric as avg_annual_return_10y,
                NULL::boolean as is_index,
                NULL::boolean as is_target_date,
                NULL::boolean as is_fund_of_fund
            FROM sec_money_market_funds mmf
        ) combined
        ORDER BY external_id, aum_usd DESC NULLS LAST;
    """)

    # Recreate indexes
    op.execute("CREATE UNIQUE INDEX idx_mv_unified_funds_ext_id ON mv_unified_funds (external_id);")
    op.execute("CREATE INDEX idx_mv_unified_funds_name ON mv_unified_funds (name);")
    op.execute("CREATE INDEX idx_mv_unified_funds_ticker ON mv_unified_funds (ticker);")
    op.execute("CREATE INDEX idx_mv_unified_funds_isin ON mv_unified_funds (isin);")
    op.execute("CREATE INDEX idx_mv_unified_funds_aum ON mv_unified_funds (aum_usd);")
    op.execute("CREATE INDEX idx_mv_unified_funds_universe ON mv_unified_funds (universe);")
    op.execute("CREATE INDEX idx_mv_unified_funds_fund_type ON mv_unified_funds (fund_type);")
    op.execute("CREATE INDEX idx_mv_unified_funds_manager ON mv_unified_funds (manager_name);")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_unified_funds CASCADE;")
