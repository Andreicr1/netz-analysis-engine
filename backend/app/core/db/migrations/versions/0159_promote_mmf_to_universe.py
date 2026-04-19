"""promote sec_money_market_funds into instruments_universe

Closes the catalog gap for institutional mandates that require money-market
allocation (natural defensive sleeve in stress regimes).

Before: 373 MMFs in sec_money_market_funds, only 3 bridged to
instruments_universe — optimizer had no cash candidates despite full SEC
data available.

After: every sec_money_market_funds row with net_assets > 0 has a matching
instruments_universe row with canonical strategy_label, is_institutional=true,
and the SEC bridge attributes (sec_cik + sec_series_id) populated.

Idempotent: INSERT ... SELECT ... WHERE NOT EXISTS. Re-run is a no-op.

Revision ID: 0159_promote_mmf_to_universe
Revises: 0158_instrument_strategy_overrides
"""
from __future__ import annotations

from alembic import op

revision = "0159_promote_mmf_to_universe"
down_revision = "0158_instrument_strategy_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Promote every MMF not yet bridged into instruments_universe.
    # strategy_label comes straight from sec_money_market_funds.strategy_label
    # (already canonical: Government Money Market / Prime Money Market /
    # Money Market / Tax-Exempt Money Market / Single State Money Market).
    # AUM populated from net_assets so candidate_screener ranks by size.
    op.execute(
        """
        INSERT INTO instruments_universe (
            instrument_type, name, asset_class, geography, currency,
            is_active, attributes, slug
        )
        SELECT
            'fund',
            LEFT(smmf.fund_name, 255),
            'cash',
            'US',
            COALESCE(smmf.currency, 'USD'),
            TRUE,
            jsonb_build_object(
                'strategy_label',         smmf.strategy_label,
                'strategy_label_source',  'sec_mmf_promotion',
                'sec_cik',                smmf.cik,
                'sec_series_id',          smmf.series_id,
                'mmf_category',           smmf.mmf_category,
                'seeks_stable_nav',       COALESCE(smmf.seeks_stable_nav, TRUE),
                'is_institutional',       TRUE,
                'aum_usd',                smmf.net_assets,
                'domicile',               COALESCE(smmf.domicile, 'US'),
                'manager_name',           COALESCE(smmf.investment_adviser, smmf.fund_name),
                'inception_date',         '2000-01-01'
            ),
            'sec-mmf-' || smmf.series_id
        FROM sec_money_market_funds smmf
        WHERE smmf.strategy_label IS NOT NULL
          AND smmf.net_assets IS NOT NULL
          AND smmf.net_assets > 0
          AND NOT EXISTS (
              SELECT 1 FROM instruments_universe iu
              WHERE iu.attributes->>'sec_series_id' = smmf.series_id
                 OR iu.slug = 'sec-mmf-' || smmf.series_id
          );
        """
    )


def downgrade() -> None:
    # Remove only rows created by this migration (identifiable by slug prefix
    # and strategy_label_source).
    op.execute(
        """
        DELETE FROM instruments_universe
         WHERE slug LIKE 'sec-mmf-%'
           AND attributes->>'strategy_label_source' = 'sec_mmf_promotion';
        """
    )
