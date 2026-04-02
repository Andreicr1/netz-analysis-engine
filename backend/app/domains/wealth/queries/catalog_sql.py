"""Pure query builder for the Unified Fund Catalog.

NOW POWERED BY: mv_unified_funds (Materialized View)
Consolidates six fund universes into a single pre-computed performance layer.

Tables are ALL global (no organization_id, no RLS).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    ColumnElement,
    Date,
    Integer,
    MetaData,
    Numeric,
    Select,
    Table,
    Text,
    and_,
    func,
    literal_column,
    or_,
    select,
)

# ═══════════════════════════════════════════════════════════════════════════
#  Reflected Materialized View
# ═══════════════════════════════════════════════════════════════════════════

_meta = MetaData()

mv_unified_funds = Table(
    "mv_unified_funds",
    _meta,
    Column("universe", Text),
    Column("external_id", Text, primary_key=True),
    Column("name", Text),
    Column("ticker", Text),
    Column("isin", Text),
    Column("region", Text),
    Column("fund_type", Text),
    Column("strategy_label", Text),
    Column("aum_usd", Numeric),
    Column("currency", Text),
    Column("domicile", Text),
    Column("manager_name", Text),
    Column("manager_id", Text),
    Column("inception_date", Date),
    Column("total_shareholder_accounts", Integer),
    Column("investor_count", Integer),
    Column("series_id", Text),
    Column("series_name", Text),
    Column("class_id", Text),
    Column("class_name", Text),
    Column("has_holdings", Boolean),
    Column("has_nav", Boolean),
    Column("has_13f_overlay", Boolean),
    Column("investment_geography", Text),
    Column("vintage_year", Integer),
    Column("expense_ratio_pct", Numeric),
    Column("avg_annual_return_1y", Numeric),
    Column("avg_annual_return_10y", Numeric),
    Column("is_index", Boolean),
    Column("is_target_date", Boolean),
    Column("is_fund_of_fund", Boolean),
)

sec_money_market_funds = Table(
    "sec_money_market_funds",
    _meta,
    Column("series_id", Text, primary_key=True),
    Column("fund_name", Text),
    Column("mmf_category", Text),
    Column("strategy_label", Text),
    Column("seven_day_gross_yield", Numeric),
    Column("weighted_avg_maturity", Integer),
    Column("weighted_avg_life", Integer),
    Column("net_assets", Numeric),
)

# ═══════════════════════════════════════════════════════════════════════════
#  Text search escaping
# ═══════════════════════════════════════════════════════════════════════════

_ILIKE_ESCAPE_RE = re.compile(r"([%_\\])")


def _escape_ilike(text: str) -> str:
    return _ILIKE_ESCAPE_RE.sub(r"\\\1", text)


# ═══════════════════════════════════════════════════════════════════════════
#  Filter dataclass
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class CatalogFilters:
    q: str | None = None
    external_id: str | None = None        # exact match on external_id (for detail lookups)
    region: str | None = None             # US | EU
    fund_universe: str | None = None      # comma-separated categories or legacy values
    fund_type: str | None = None          # additional fund_type filter within universe
    strategy_label: str | None = None     # comma-separated strategy labels
    investment_geography: str | None = None  # comma-separated geography values
    aum_min: float | None = None
    has_nav: bool | None = True            # True = only funds with ticker (default: exclude untradeable)
    has_aum: bool | None = None            # True = only funds with AUM > 0
    domicile: str | None = None
    manager: str | None = None            # text search on manager name
    sort: str = "name_asc"               # name_asc | name_desc | aum_desc | aum_asc
    page: int = 1
    page_size: int = 50

    # Prospectus-based filters (applied to registered_us + etf branches)
    max_expense_ratio: float | None = None      # e.g. 0.50 → ER ≤ 0.50%
    min_return_1y: float | None = None          # e.g. 5.0 → avg_annual_return_1y ≥ 5%
    min_return_10y: float | None = None         # e.g. 8.0 → avg_annual_return_10y ≥ 8%


# ═══════════════════════════════════════════════════════════════════════════
#  Category-based universe parsing
# ═══════════════════════════════════════════════════════════════════════════

ALL_CATEGORIES = frozenset({
    "mutual_fund", "closed_end", "etf", "bdc",
    "hedge_fund", "private_fund", "ucits",
    "money_market",
})

_LEGACY_EXPANSIONS: dict[str, set[str]] = {
    "registered": {"mutual_fund", "closed_end", "etf", "bdc"},
    "private": {"hedge_fund", "private_fund"},
    "ucits": {"ucits"},
}


def _parse_categories(fund_universe: str | None) -> set[str] | None:
    if not fund_universe or fund_universe.strip() == "all":
        return None

    parts = {p.strip() for p in fund_universe.split(",") if p.strip()}
    categories: set[str] = set()
    for p in parts:
        if p in _LEGACY_EXPANSIONS:
            categories.update(_LEGACY_EXPANSIONS[p])
        elif p in ALL_CATEGORIES:
            categories.add(p)
    return categories or None


# ═══════════════════════════════════════════════════════════════════════════
#  Public API
# ═══════════════════════════════════════════════════════════════════════════


# All sort modes push NULL manager_name last so managed funds appear first
_SORT_MAP = {
    "name_asc": "(manager_name IS NULL), manager_name ASC, REGEXP_REPLACE(name, '^[^a-zA-Z]+', '', 'g') ASC, name ASC",
    "name_desc": "(manager_name IS NULL), manager_name ASC, REGEXP_REPLACE(name, '^[^a-zA-Z]+', '', 'g') DESC, name DESC",
    "aum_desc": "(manager_name IS NULL), aum_usd DESC NULLS LAST",
    "aum_asc": "(manager_name IS NULL), aum_usd ASC NULLS LAST",
    "manager_asc": "manager_name ASC NULLS LAST, name ASC",
    "manager_desc": "manager_name DESC NULLS FIRST, name ASC",
    "strategy_asc": "(manager_name IS NULL), strategy_label ASC NULLS LAST",
    "strategy_desc": "(manager_name IS NULL), strategy_label DESC NULLS LAST",
}


def _build_base_stmt(f: CatalogFilters) -> Select[Any]:
    """Build the base select with all filters applied to the view."""
    stmt = select(mv_unified_funds)
    
    conditions: list[ColumnElement[bool]] = []

    # 0. Exact external_id match (for detail lookups — bypasses text search)
    if f.external_id:
        conditions.append(mv_unified_funds.c.external_id == f.external_id)

    # 1. Full-text search
    if f.q:
        escaped = _escape_ilike(f.q)
        pattern = f"%{escaped}%"
        conditions.append(
            or_(
                mv_unified_funds.c.name.ilike(pattern),
                mv_unified_funds.c.ticker.ilike(pattern),
                mv_unified_funds.c.isin.ilike(pattern),
                mv_unified_funds.c.manager_name.ilike(pattern),
                mv_unified_funds.c.series_name.ilike(pattern),
            )
        )
        
    # 2. Region
    if f.region:
        conditions.append(mv_unified_funds.c.region == f.region)
        
    # 3. Categories (Universe)
    cats = _parse_categories(f.fund_universe)
    if cats is not None:
        cat_conditions = []
        if "mutual_fund" in cats:
            cat_conditions.append(and_(mv_unified_funds.c.universe == "registered_us", mv_unified_funds.c.fund_type.in_(["mutual_fund", "interval_fund"])))
        if "closed_end" in cats:
            cat_conditions.append(and_(mv_unified_funds.c.universe == "registered_us", mv_unified_funds.c.fund_type == "closed_end"))
        if "etf" in cats:
            cat_conditions.append(mv_unified_funds.c.fund_type == "etf")
        if "bdc" in cats:
            cat_conditions.append(mv_unified_funds.c.fund_type == "bdc")
        if "hedge_fund" in cats:
            cat_conditions.append(and_(mv_unified_funds.c.universe == "private_us", mv_unified_funds.c.fund_type == "Hedge Fund"))
        if "private_fund" in cats:
            cat_conditions.append(and_(mv_unified_funds.c.universe == "private_us", mv_unified_funds.c.fund_type != "Hedge Fund"))
        if "ucits" in cats:
            cat_conditions.append(mv_unified_funds.c.universe == "ucits_eu")
        if "money_market" in cats:
            cat_conditions.append(mv_unified_funds.c.fund_type == "money_market")
            
        if cat_conditions:
            conditions.append(or_(*cat_conditions))

    # 4. Specific Fund Type filter
    if f.fund_type:
        ft_list = [v.strip() for v in f.fund_type.split(",") if v.strip()]
        if len(ft_list) == 1:
            conditions.append(mv_unified_funds.c.fund_type == ft_list[0])
        elif ft_list:
            conditions.append(mv_unified_funds.c.fund_type.in_(ft_list))
            
    # 5. Strategy Label
    if f.strategy_label:
        sl_list = [v.strip() for v in f.strategy_label.split(",") if v.strip()]
        if len(sl_list) == 1:
            conditions.append(mv_unified_funds.c.strategy_label == sl_list[0])
        elif sl_list:
            conditions.append(mv_unified_funds.c.strategy_label.in_(sl_list))
            
    # 6. Investment Geography
    if f.investment_geography:
        geo_list = [v.strip() for v in f.investment_geography.split(",") if v.strip()]
        if len(geo_list) == 1:
            conditions.append(mv_unified_funds.c.investment_geography == geo_list[0])
        elif geo_list:
            conditions.append(mv_unified_funds.c.investment_geography.in_(geo_list))
            
    # 7. AUM
    if f.aum_min is not None:
        conditions.append(mv_unified_funds.c.aum_usd >= f.aum_min)
    if f.has_aum is True:
        conditions.append(and_(mv_unified_funds.c.aum_usd.isnot(None), mv_unified_funds.c.aum_usd > 0))
        
    # 8. NAV (Ticker availability)
    if f.has_nav is True:
        conditions.append(mv_unified_funds.c.ticker.isnot(None))
        
    # 9. Domicile
    if f.domicile:
        conditions.append(mv_unified_funds.c.domicile == f.domicile)
        
    # 10. Manager
    if f.manager:
        escaped = _escape_ilike(f.manager)
        conditions.append(mv_unified_funds.c.manager_name.ilike(f"%{escaped}%"))
        
    # 11. Prospectus filters
    if f.max_expense_ratio is not None:
        conditions.append(mv_unified_funds.c.expense_ratio_pct <= f.max_expense_ratio)
    if f.min_return_1y is not None:
        conditions.append(mv_unified_funds.c.avg_annual_return_1y >= f.min_return_1y)
    if f.min_return_10y is not None:
        conditions.append(mv_unified_funds.c.avg_annual_return_10y >= f.min_return_10y)

    if conditions:
        stmt = stmt.where(and_(*conditions))
        
    return stmt


def build_catalog_query(filters: CatalogFilters) -> Select[Any] | None:
    """Build paginated query from mv_unified_funds."""
    base = _build_base_stmt(filters)
    
    # Map 'aum' column to 'aum_usd' for the frontend expectations if needed, 
    # but the catalog response mapper handles it. 
    # Actually, we should rename it in the select to match previous 'aum' name.
    stmt = base.add_columns(func.count().over().label("_total"))
    
    # Alias aum_usd as aum for backward compatibility in the Select result
    stmt = stmt.column(mv_unified_funds.c.aum_usd.label("aum"))

    sort_expr: ColumnElement[Any] = literal_column(_SORT_MAP.get(filters.sort, "name ASC"))
    offset = (filters.page - 1) * filters.page_size

    return (
        stmt
        .order_by(sort_expr)
        .offset(offset)
        .limit(filters.page_size)
    )


def build_catalog_facets_query(filters: CatalogFilters) -> Select[Any] | None:
    """Build facet aggregation query over mv_unified_funds."""
    # Aggregation doesn't need pagination
    facet_filters = CatalogFilters(
        q=filters.q,
        region=filters.region,
        fund_universe=filters.fund_universe,
        fund_type=filters.fund_type,
        strategy_label=filters.strategy_label,
        investment_geography=filters.investment_geography,
        aum_min=filters.aum_min,
        has_nav=filters.has_nav,
        has_aum=filters.has_aum,
        domicile=filters.domicile,
        manager=filters.manager,
        page=1,
        page_size=1_000_000,
    )
    
    base = _build_base_stmt(facet_filters)
    sub = base.subquery()

    stmt = select(
        sub.c.universe,
        sub.c.region,
        sub.c.fund_type,
        sub.c.strategy_label,
        sub.c.domicile,
        sub.c.investment_geography,
        func.count().label("cnt"),
    ).group_by(
        sub.c.universe,
        sub.c.region,
        sub.c.fund_type,
        sub.c.strategy_label,
        sub.c.domicile,
        sub.c.investment_geography,
    )

    return stmt
