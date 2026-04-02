"""Macro Performance Layer (Materialized Views)

Revision ID: 0079_macro_performance_layer
Revises: 0078_consolidated_screener_views
Create Date: 2026-04-02 15:00:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0079_macro_performance_layer"
down_revision: str | None = "0078_consolidated_screener_views"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    # 1. Create mv_macro_latest
    op.execute("""
        CREATE MATERIALIZED VIEW mv_macro_latest AS
        SELECT * FROM (
            (SELECT DISTINCT ON (series_id)
                'fred'::text as source,
                series_id::text as indicator_id,
                value::numeric as value,
                obs_date as obs_date,
                NULL::text as country_code
            FROM macro_data
            ORDER BY series_id, obs_date DESC)

            UNION ALL

            (SELECT DISTINCT ON (series_id)
                'treasury'::text as source,
                series_id::text as indicator_id,
                value::numeric as value,
                obs_date as obs_date,
                'US'::text as country_code
            FROM treasury_data
            ORDER BY series_id, obs_date DESC)

            UNION ALL

            (SELECT DISTINCT ON (indicator, country_code)
                'bis'::text as source,
                indicator::text as indicator_id,
                value::numeric as value,
                period::date as obs_date,
                country_code::text as country_code
            FROM bis_statistics
            ORDER BY indicator, country_code, period DESC)

            UNION ALL

            (SELECT DISTINCT ON (series_id)
                'ofr'::text as source,
                series_id::text as indicator_id,
                value::numeric as value,
                obs_date as obs_date,
                'US'::text as country_code
            FROM ofr_hedge_fund_data
            ORDER BY series_id, obs_date DESC)
        ) combined;
    """)

    # 2. Create mv_macro_regional_summary
    # Flattened view of the latest regional snapshot for fast display
    op.execute("""
        CREATE MATERIALIZED VIEW mv_macro_regional_summary AS
        WITH latest_snap AS (
            SELECT data_json, as_of_date
            FROM macro_regional_snapshots
            ORDER BY as_of_date DESC
            LIMIT 1
        )
        SELECT 
            as_of_date,
            region_key,
            (region_val->>'composite_score')::numeric as composite_score,
            (region_val->>'coverage')::numeric as coverage,
            region_val->'dimensions' as dimensions,
            region_val->'data_freshness' as data_freshness
        FROM latest_snap, jsonb_each(data_json->'regions') as r(region_key, region_val);
    """)

    # 3. Create indexes
    op.execute("CREATE UNIQUE INDEX idx_mv_macro_latest_id ON mv_macro_latest (source, indicator_id, country_code);")
    op.execute("CREATE INDEX idx_mv_macro_latest_indicator ON mv_macro_latest (indicator_id);")
    op.execute("CREATE UNIQUE INDEX idx_mv_macro_reg_summary_region ON mv_macro_regional_summary (region_key);")

def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_macro_regional_summary CASCADE;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_macro_latest CASCADE;")
