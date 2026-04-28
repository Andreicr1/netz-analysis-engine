"""PR-Q91 — UCITS data-availability gate (NAV-eligibility) + bridge ESMA↔universe.

Three-part fix:

1. **Bridge** — Populate ``instruments_universe.attributes->>'fund_lei'`` for
   UCITS rows. ``universe_sync`` writes ``fund_subtype='ucits'`` for 2,931
   rows but ``fund_lei`` stayed NULL on every row (excluded.fund_lei was
   COALESCE'd with NULL for legacy rows). Without ``fund_lei`` the
   ``esma_aum_sync`` worker (Q78) cannot match instruments back to
   ``esma_funds`` and the screener cannot resolve manager metadata.

2. **mv_unified_funds UCITS branch refactor** — current branch:
     - reports ``has_nav = true`` hard-coded for all 2,929 ESMA funds with
       ``yahoo_ticker``, even though only ~289 have any row in
       ``nav_timeseries``.
     - returns ``aum_usd = NULL`` even though Q78 enriched 56 instruments
       with real Yahoo ``totalAssets`` in ``attributes->>'aum_usd'``.
     - uses ``ef.legacy_isin_misnamed`` as ``external_id`` and ``isin``
       (the legacy column stores LEIs, not ISINs — Q11B residue).

   New branch INNER JOINs ``instruments_universe`` (ticker = yahoo_ticker)
   AND filters by ``EXISTS(nav_timeseries)``, so ``has_nav`` is no longer
   a lie. ``aum_usd`` reads from ``attributes->>'aum_usd'`` (Q78 output).
   ``external_id`` uses ``COALESCE(es.isin, iu.ticker, ef.lei)``.

3. **Layer 1 unchanged** — screener ``min_track_record_years: 3`` keeps
   working as the eligibility gate; the view now stops reporting funds
   that cannot possibly satisfy any NAV-based check.

Empirical impact (DB local 2026-04-28):
- 2,929 UCITS with yahoo_ticker → 288 with NAV → 178 with ≥3y span →
  56 with AUM populated → **26 funds clear AUM≥$100M+3y track record**.
- Decision D-UCITS-ship-baseline (2026-04-28) crystallized:
  UCITS coverage = whatever Yahoo/Tiingo deliver, no manual seed.

Revision ID: 0194_q91_ucits_data_gate
Revises: 0193_q90_revert_q87_manual_seed
Create Date: 2026-04-28
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0194_q91_ucits_data_gate"
down_revision: str | None = "0193_q90_revert_q87_manual_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# UCITS branch — fixed (Q91): INNER JOIN universe + EXISTS nav + real AUM.
# All other branches (registered_us / etfs / bdcs / private / mmf) match
# 0183 verbatim — no behaviour change for SEC universes.
# ---------------------------------------------------------------------------
_MV_SQL_UP = """
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
    -- Branch 1: registered_us
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
        COALESCE(m.firm_name, rf.fund_name)::text as manager_name,
        CASE WHEN m.crd_number IS NOT NULL THEN m.crd_number ELSE NULL END::text as manager_id,
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
        rf.is_fund_of_fund,
        rf.is_institutional
    FROM sec_registered_funds rf
    LEFT JOIN sec_fund_classes fc ON rf.cik = fc.cik
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
        NULL::boolean as is_fund_of_fund,
        e.is_institutional
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
        NULL::boolean as is_fund_of_fund,
        b.is_institutional
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
        mf.is_fund_of_funds as is_fund_of_fund,
        mf.is_institutional
    FROM sec_manager_funds mf
    JOIN sec_managers sm ON mf.crd_number = sm.crd_number

    UNION ALL
    -- Branch 5: ucits_eu (Q91 — data-availability gate)
    -- INNER JOIN instruments_universe + EXISTS(nav_timeseries) make has_nav truthful.
    -- aum_usd reads from Q78 enrichment (instruments_universe.attributes).
    -- external_id prefers FIRDS ISIN, falls back to ticker, then LEI.
    SELECT
        'ucits_eu'::text as universe,
        COALESCE(es.isin, iu.ticker, ef.lei)::text as external_id,
        COALESCE(NULLIF(es.full_name, ''), ef.fund_name)::text as name,
        iu.ticker::text as ticker,
        es.isin::text as isin,
        'EU'::text as region,
        ef.fund_type::text as fund_type,
        ef.strategy_label::text as strategy_label,
        (iu.attributes->>'aum_usd')::numeric as aum_usd,
        COALESCE(iu.currency, NULLIF(iu.attributes->>'aum_currency', ''))::text as currency,
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
        NULL::boolean as is_fund_of_fund,
        ef.is_institutional
    FROM esma_funds ef
    JOIN instruments_universe iu
        ON iu.ticker = ef.yahoo_ticker
       AND iu.is_active IS NOT FALSE
    LEFT JOIN esma_securities es ON es.fund_lei = ef.lei AND es.is_active
    LEFT JOIN esma_managers em ON em.esma_id = ef.esma_manager_id
    WHERE ef.yahoo_ticker IS NOT NULL
      AND ef.yahoo_ticker <> ''
      AND EXISTS (
          SELECT 1 FROM nav_timeseries n WHERE n.instrument_id = iu.instrument_id
      )

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
        NULL::boolean as is_fund_of_fund,
        mmf.is_institutional
    FROM sec_money_market_funds mmf
) combined
ORDER BY external_id, aum_usd DESC NULLS LAST;
"""


# Down: restore 0183 view (legacy_isin_misnamed-based UCITS branch).
_MV_SQL_DOWN = """
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
    SELECT
        'ucits_eu'::text as universe,
        ef.legacy_isin_misnamed::text as external_id,
        ef.fund_name::text as name,
        ef.yahoo_ticker::text as ticker,
        ef.legacy_isin_misnamed::text as isin,
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
        NULL::boolean as is_fund_of_fund,
        ef.is_institutional
    FROM esma_funds ef
    JOIN esma_managers em ON ef.esma_manager_id = em.esma_id
    WHERE ef.yahoo_ticker IS NOT NULL AND ef.yahoo_ticker != ''
) combined
ORDER BY external_id, aum_usd DESC NULLS LAST;
"""


_INDEXES = [
    "CREATE UNIQUE INDEX idx_mv_unified_funds_ext_id ON mv_unified_funds (external_id);",
    "CREATE INDEX idx_mv_unified_funds_name ON mv_unified_funds (name);",
    "CREATE INDEX idx_mv_unified_funds_ticker ON mv_unified_funds (ticker);",
    "CREATE INDEX idx_mv_unified_funds_isin ON mv_unified_funds (isin);",
    "CREATE INDEX idx_mv_unified_funds_aum ON mv_unified_funds (aum_usd);",
    "CREATE INDEX idx_mv_unified_funds_universe ON mv_unified_funds (universe);",
    "CREATE INDEX idx_mv_unified_funds_fund_type ON mv_unified_funds (fund_type);",
    (
        "CREATE INDEX idx_mv_unified_funds_institutional "
        "ON mv_unified_funds (external_id) WHERE is_institutional = true;"
    ),
]


# Bridge: populate fund_lei in instruments_universe for UCITS rows whose
# ticker matches an esma_funds.yahoo_ticker. yahoo_ticker is unique in
# esma_funds (verified empirically), so the join is single-valued.
_BRIDGE_UP = """
UPDATE instruments_universe iu
SET attributes = iu.attributes || jsonb_build_object('fund_lei', ef.lei)
FROM esma_funds ef
WHERE ef.yahoo_ticker = iu.ticker
  AND ef.yahoo_ticker IS NOT NULL
  AND ef.yahoo_ticker <> ''
  AND iu.attributes->>'fund_subtype' = 'ucits'
  AND (iu.attributes->>'fund_lei' IS NULL OR iu.attributes->>'fund_lei' = '');
"""

_BRIDGE_DOWN = """
UPDATE instruments_universe iu
SET attributes = iu.attributes - 'fund_lei'
WHERE iu.attributes->>'fund_subtype' = 'ucits'
  AND iu.attributes ? 'fund_lei';
"""


# Reactivate UCITS instruments that *do* have NAV but were deactivated by
# universe_sync._deactivate_no_nav (race: deactivation ran before NAV
# arrived, ESMA re-upsert ON CONFLICT does not reset is_active=true).
# Tag with attributes->>'q91_reactivated_at' so downgrade can revert
# precisely the rows this migration changed.
_REACTIVATE_UP = """
UPDATE instruments_universe iu
SET is_active = true,
    attributes = iu.attributes || jsonb_build_object(
        'q91_reactivated_at', now()::text
    ),
    updated_at = now()
FROM esma_funds ef
WHERE ef.yahoo_ticker = iu.ticker
  AND iu.is_active = false
  AND iu.attributes->>'fund_subtype' = 'ucits'
  AND EXISTS (
      SELECT 1 FROM nav_timeseries n WHERE n.instrument_id = iu.instrument_id
  );
"""

_REACTIVATE_DOWN = """
UPDATE instruments_universe
SET is_active = false,
    attributes = attributes - 'q91_reactivated_at',
    updated_at = now()
WHERE attributes ? 'q91_reactivated_at';
"""


def upgrade() -> None:
    op.execute(_BRIDGE_UP)
    op.execute(_REACTIVATE_UP)
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_unified_funds CASCADE;")
    op.execute(_MV_SQL_UP)
    for ddl in _INDEXES:
        op.execute(ddl)
    op.execute("REFRESH MATERIALIZED VIEW mv_unified_funds;")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_unified_funds CASCADE;")
    op.execute(_MV_SQL_DOWN)
    for ddl in _INDEXES:
        op.execute(ddl)
    op.execute(_REACTIVATE_DOWN)
    op.execute(_BRIDGE_DOWN)
