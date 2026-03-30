"""Pure query builder for the Unified Fund Catalog.

Constructs a UNION ALL of five branches (registered_us mutual/closed-end,
ETFs, BDCs, private_us, ucits_eu) with composable filters.  Zero I/O —
frozen dataclass input, SQLAlchemy Core Select output.

Tables are ALL global (no organization_id, no RLS).

The frontend sends category-based universe filters that map to branch
activation + fund_type constraints.  Seven UI categories:

  mutual_fund   → registered_us branch, fund_type in (mutual_fund, interval_fund)
  closed_end    → registered_us branch, fund_type = closed_end
  etf           → sec_etfs branch
  bdc           → sec_bdcs branch
  hedge_fund    → private_us branch, fund_type = Hedge Fund
  private_fund  → private_us branch, fund_type != Hedge Fund
  ucits         → ucits_eu branch

Performance notes:
- ~50k registered + ~1k etf + ~200 bdc + ~50k private + ~30k UCITS ≈ 131k rows
- PostgreSQL pushes WHERE predicates into each UNION ALL branch
- count() OVER() window function avoids second roundtrip
- If p95 > 200ms: create materialized view mv_unified_fund_catalog
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    Integer,
    MetaData,
    Numeric,
    Select,
    String,
    Table,
    Text,
    and_,
    case,
    func,
    literal,
    literal_column,
    select,
    union_all,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# ═══════════════════════════════════════════════════════════════════════════
#  Reflected tables (Core-style, not ORM)
# ═══════════════════════════════════════════════════════════════════════════

_meta = MetaData()

sec_registered_funds = Table(
    "sec_registered_funds",
    _meta,
    Column("cik", Text, primary_key=True),
    Column("crd_number", Text),
    Column("fund_name", Text, nullable=False),
    Column("fund_type", Text, nullable=False),
    Column("strategy_label", Text),
    Column("ticker", Text),
    Column("isin", Text),
    Column("total_assets", BigInteger),
    Column("total_shareholder_accounts", Integer),
    Column("inception_date", Date),
    Column("currency", Text),
    Column("domicile", Text),
    Column("monthly_avg_net_assets", Numeric(20, 2)),
    Column("last_nport_date", Date),
    Column("aum_below_threshold", Boolean),
    # N-CEN enrichment flags (migration 0065)
    Column("is_index", Boolean),
    Column("is_target_date", Boolean),
    Column("is_fund_of_fund", Boolean),
)

sec_fund_classes = Table(
    "sec_fund_classes",
    _meta,
    Column("cik", Text, primary_key=True),
    Column("series_id", Text, primary_key=True),
    Column("class_id", Text, primary_key=True),
    Column("series_name", Text),
    Column("class_name", Text),
    Column("ticker", Text),
)

sec_managers = Table(
    "sec_managers",
    _meta,
    Column("crd_number", Text, primary_key=True),
    Column("cik", Text),
    Column("firm_name", Text),
    extend_existing=True,
)

sec_manager_funds = Table(
    "sec_manager_funds",
    _meta,
    Column("id", PG_UUID, primary_key=True),
    Column("crd_number", Text, nullable=False),
    Column("fund_name", Text, nullable=False),
    Column("fund_type", Text),
    Column("strategy_label", Text),
    Column("gross_asset_value", BigInteger),
    Column("investor_count", Integer),
    Column("is_fund_of_funds", Boolean),
    Column("vintage_year", Integer),
)

sec_13f_holdings = Table(
    "sec_13f_holdings",
    _meta,
    Column("report_date", Date, primary_key=True),
    Column("cik", Text, primary_key=True),
    Column("cusip", Text, primary_key=True),
    extend_existing=True,
)

sec_etfs = Table(
    "sec_etfs",
    _meta,
    Column("series_id", String, primary_key=True),
    Column("cik", String, nullable=False),
    Column("fund_name", String, nullable=False),
    Column("ticker", String),
    Column("isin", String),
    Column("strategy_label", String),
    Column("monthly_avg_net_assets", Numeric(20, 2)),
    Column("inception_date", Date),
    Column("domicile", String),
    Column("currency", String),
)

sec_bdcs = Table(
    "sec_bdcs",
    _meta,
    Column("series_id", String, primary_key=True),
    Column("cik", String, nullable=False),
    Column("fund_name", String, nullable=False),
    Column("ticker", String),
    Column("isin", String),
    Column("strategy_label", String),
    Column("monthly_avg_net_assets", Numeric(20, 2)),
    Column("inception_date", Date),
    Column("domicile", String),
    Column("currency", String),
)

esma_funds = Table(
    "esma_funds",
    _meta,
    Column("isin", Text, primary_key=True),
    Column("fund_name", Text, nullable=False),
    Column("esma_manager_id", Text),
    Column("domicile", Text),
    Column("fund_type", Text),
    Column("strategy_label", Text),
    Column("host_member_states", ARRAY(Text)),
    Column("yahoo_ticker", Text),
)

esma_managers = Table(
    "esma_managers",
    _meta,
    Column("esma_id", Text, primary_key=True),
    Column("company_name", Text, nullable=False),
    Column("country", Text),
    extend_existing=True,
)

sec_fund_prospectus_stats = Table(
    "sec_fund_prospectus_stats",
    _meta,
    Column("series_id", Text, primary_key=True),
    Column("class_id", Text, primary_key=True),
    Column("expense_ratio_pct", Numeric),
    Column("avg_annual_return_1y", Numeric),
    Column("avg_annual_return_10y", Numeric),
    extend_existing=True,
)

# ═══════════════════════════════════════════════════════════════════════════
#  Text search escaping
# ═══════════════════════════════════════════════════════════════════════════

_ILIKE_ESCAPE_RE = re.compile(r"([%_\\])")


def _escape_ilike(text: str) -> str:
    return _ILIKE_ESCAPE_RE.sub(r"\\\1", text)


# ═══════════════════════════════════════════════════════════════════════════
#  Investment geography — SQL-level keyword classification (Layer 2 cascade)
# ═══════════════════════════════════════════════════════════════════════════


def _geography_case(name_col, strategy_col=None, *, default: str = "US"):
    """Build a SQL CASE for investment_geography from fund name + strategy_label.

    This mirrors Layer 2 of geography_classifier.py using SQL ILIKE.
    """
    text_col = func.coalesce(strategy_col, name_col) if strategy_col is not None else name_col
    return case(
        (text_col.ilike("%emerging%"), literal("Emerging Markets")),
        (text_col.ilike("%frontier%"), literal("Emerging Markets")),
        (text_col.ilike("%china%"), literal("Emerging Markets")),
        (text_col.ilike("%india%"), literal("Emerging Markets")),
        (text_col.ilike("%latin america%"), literal("Latin America")),
        (text_col.ilike("%latam%"), literal("Latin America")),
        (text_col.ilike("%brazil%"), literal("Latin America")),
        (text_col.ilike("%europe%"), literal("Europe")),
        (text_col.ilike("%european%"), literal("Europe")),
        (text_col.ilike("%eurozone%"), literal("Europe")),
        (text_col.ilike("%asia%"), literal("Asia Pacific")),
        (text_col.ilike("%japan%"), literal("Asia Pacific")),
        (text_col.ilike("%pacific%"), literal("Asia Pacific")),
        (text_col.ilike("%global%"), literal("Global")),
        (text_col.ilike("%world%"), literal("Global")),
        (text_col.ilike("%international%"), literal("Global")),
        (text_col.ilike("%foreign%"), literal("Global")),
        (text_col.ilike("%ex-us%"), literal("Global")),
        (text_col.ilike("%ex us%"), literal("Global")),
        else_=literal(default),
    ).label("investment_geography")


def _apply_geography_filter(stmt, geo_col, f: "CatalogFilters"):
    """Apply investment_geography filter if set."""
    if not f.investment_geography:
        return stmt
    geo_list = [v.strip() for v in f.investment_geography.split(",") if v.strip()]
    if len(geo_list) == 1:
        return stmt.where(geo_col == geo_list[0])
    if geo_list:
        return stmt.where(geo_col.in_(geo_list))
    return stmt


# ═══════════════════════════════════════════════════════════════════════════
#  Filter dataclass
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class CatalogFilters:
    q: str | None = None
    region: str | None = None             # US | EU
    fund_universe: str | None = None      # comma-separated categories or legacy values
    fund_type: str | None = None          # additional fund_type filter within universe
    strategy_label: str | None = None     # comma-separated strategy labels
    investment_geography: str | None = None  # comma-separated geography values
    aum_min: float | None = None
    has_nav: bool | None = None           # True = only funds with ticker
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

# Seven UI categories that the frontend sends as comma-separated fund_universe.
ALL_CATEGORIES = frozenset({
    "mutual_fund", "closed_end", "etf", "bdc",
    "hedge_fund", "private_fund", "ucits",
})

# Legacy value → expansion to new categories.
_LEGACY_EXPANSIONS: dict[str, set[str]] = {
    "registered": {"mutual_fund", "closed_end", "etf", "bdc"},
    "private": {"hedge_fund", "private_fund"},
    "ucits": {"ucits"},
}


def _parse_categories(fund_universe: str | None) -> set[str] | None:
    """Parse fund_universe into a set of active categories.

    Returns None when all categories are active (no filter / "all").
    Returns a set of category strings otherwise.
    """
    if not fund_universe or fund_universe.strip() == "all":
        return None

    parts = {p.strip() for p in fund_universe.split(",") if p.strip()}
    categories: set[str] = set()
    for p in parts:
        if p in _LEGACY_EXPANSIONS:
            categories.update(_LEGACY_EXPANSIONS[p])
        elif p in ALL_CATEGORIES:
            categories.add(p)
        # Ignore unknown values silently.
    return categories or None


# ═══════════════════════════════════════════════════════════════════════════
#  Branch builders
# ═══════════════════════════════════════════════════════════════════════════


def _registered_us_branch(f: CatalogFilters) -> Select | None:
    """Registered US funds (mutual_fund, closed_end, interval_fund)."""
    cats = _parse_categories(f.fund_universe)
    reg_cats = {"mutual_fund", "closed_end"}
    if cats is not None:
        active = cats & reg_cats
        if not active:
            return None
    else:
        active = None  # all types
    if f.region and f.region != "US":
        return None

    # 13F overlay flag
    _mgr_cik = (
        select(sec_managers.c.cik)
        .where(sec_managers.c.crd_number == sec_registered_funds.c.crd_number)
        .correlate(sec_registered_funds)
        .scalar_subquery()
    )
    _13f_exists = (
        select(literal(True))
        .select_from(sec_13f_holdings)
        .where(sec_13f_holdings.c.cik == _mgr_cik)
        .where(sec_13f_holdings.c.report_date >= func.current_date() - 180)
        .correlate(sec_registered_funds)
        .exists()
    )

    _effective_ticker = func.coalesce(
        sec_fund_classes.c.ticker, sec_registered_funds.c.ticker,
    )

    stmt = (
        select(
            literal("registered_us").label("universe"),
            func.coalesce(
                sec_fund_classes.c.series_id,
                sec_registered_funds.c.cik,
            ).label("external_id"),
            func.coalesce(
                sec_fund_classes.c.series_name,
                sec_registered_funds.c.fund_name,
            ).label("name"),
            _effective_ticker.label("ticker"),
            sec_registered_funds.c.isin,
            literal("US").label("region"),
            sec_registered_funds.c.fund_type,
            sec_registered_funds.c.strategy_label,
            func.coalesce(
                sec_registered_funds.c.total_assets,
                sec_registered_funds.c.monthly_avg_net_assets,
            ).label("aum"),
            sec_registered_funds.c.currency,
            sec_registered_funds.c.domicile,
            sec_managers.c.firm_name.label("manager_name"),
            sec_managers.c.crd_number.label("manager_id"),
            sec_registered_funds.c.inception_date,
            sec_registered_funds.c.total_shareholder_accounts,
            literal_column("NULL").label("investor_count"),
            sec_fund_classes.c.series_id,
            sec_fund_classes.c.series_name,
            sec_fund_classes.c.class_id,
            sec_fund_classes.c.class_name,
            literal(True).label("has_holdings"),
            (_effective_ticker.isnot(None)).label("has_nav"),
            _13f_exists.label("has_13f_overlay"),
            _geography_case(
                sec_registered_funds.c.fund_name,
                sec_registered_funds.c.strategy_label,
                default="US",
            ),
            literal_column("NULL").label("vintage_year"),
            # Fee & performance (from prospectus stats)
            sec_fund_prospectus_stats.c.expense_ratio_pct,
            sec_fund_prospectus_stats.c.avg_annual_return_1y,
            sec_fund_prospectus_stats.c.avg_annual_return_10y,
            # N-CEN enrichment flags
            sec_registered_funds.c.is_index,
            sec_registered_funds.c.is_target_date,
            sec_registered_funds.c.is_fund_of_fund,
        )
        .select_from(sec_registered_funds)
        .outerjoin(
            sec_fund_classes,
            sec_registered_funds.c.cik == sec_fund_classes.c.cik,
        )
        .outerjoin(
            sec_managers,
            sec_registered_funds.c.crd_number == sec_managers.c.crd_number,
        )
        .outerjoin(
            sec_fund_prospectus_stats,
            and_(
                sec_fund_classes.c.series_id == sec_fund_prospectus_stats.c.series_id,
                sec_fund_classes.c.class_id == sec_fund_prospectus_stats.c.class_id,
            ),
        )
    )

    # Prospectus-based filters (applied on the already-joined table)
    _has_prospectus_filters = (
        f.max_expense_ratio is not None
        or f.min_return_1y is not None
        or f.min_return_10y is not None
    )

    # Exclude series already captured in sec_etfs or sec_bdcs (prevents
    # ETF/BDC funds from showing as "Mutual Fund" via registered_us branch).
    _in_etf = (
        select(literal(True))
        .select_from(sec_etfs)
        .where(sec_etfs.c.series_id == sec_fund_classes.c.series_id)
        .correlate(sec_fund_classes)
        .exists()
    )
    _in_bdc = (
        select(literal(True))
        .select_from(sec_bdcs)
        .where(sec_bdcs.c.series_id == sec_fund_classes.c.series_id)
        .correlate(sec_fund_classes)
        .exists()
    )
    stmt = stmt.where(~_in_etf).where(~_in_bdc)

    conditions = _common_conditions_registered(f)
    # Category-based fund_type restriction
    if active is not None and active != reg_cats:
        # Map categories to DB fund_type values
        allowed_types: list[str] = []
        if "mutual_fund" in active:
            allowed_types.extend(["mutual_fund", "interval_fund"])
        if "closed_end" in active:
            allowed_types.append("closed_end")
        conditions.append(sec_registered_funds.c.fund_type.in_(allowed_types))

    # Prospectus filter conditions
    if f.max_expense_ratio is not None:
        conditions.append(
            sec_fund_prospectus_stats.c.expense_ratio_pct <= f.max_expense_ratio,
        )
    if f.min_return_1y is not None:
        conditions.append(
            sec_fund_prospectus_stats.c.avg_annual_return_1y >= f.min_return_1y,
        )
    if f.min_return_10y is not None:
        conditions.append(
            sec_fund_prospectus_stats.c.avg_annual_return_10y >= f.min_return_10y,
        )

    if conditions:
        stmt = stmt.where(and_(*conditions))
    return stmt


def _common_conditions_registered(f: CatalogFilters) -> list:
    conditions: list = []
    if f.q:
        escaped = _escape_ilike(f.q)
        pattern = f"%{escaped}%"
        conditions.append(
            sec_registered_funds.c.fund_name.ilike(pattern)
            | sec_fund_classes.c.series_name.ilike(pattern)
            | sec_registered_funds.c.ticker.ilike(pattern)
            | sec_fund_classes.c.ticker.ilike(pattern)
            | sec_registered_funds.c.isin.ilike(pattern)
            | sec_managers.c.firm_name.ilike(pattern),
        )
    if f.fund_type:
        ft_list = [v.strip() for v in f.fund_type.split(",") if v.strip()]
        if len(ft_list) == 1:
            conditions.append(sec_registered_funds.c.fund_type == ft_list[0])
        elif ft_list:
            conditions.append(sec_registered_funds.c.fund_type.in_(ft_list))
    if f.strategy_label:
        sl_list = [v.strip() for v in f.strategy_label.split(",") if v.strip()]
        if len(sl_list) == 1:
            conditions.append(sec_registered_funds.c.strategy_label == sl_list[0])
        elif sl_list:
            conditions.append(sec_registered_funds.c.strategy_label.in_(sl_list))
    if f.aum_min is not None:
        conditions.append(sec_registered_funds.c.total_assets >= int(f.aum_min))
    if f.has_nav is True:
        _eff_ticker = func.coalesce(
            sec_fund_classes.c.ticker, sec_registered_funds.c.ticker,
        )
        conditions.append(_eff_ticker.isnot(None))
    if f.domicile:
        conditions.append(sec_registered_funds.c.domicile == f.domicile)
    if f.manager:
        escaped = _escape_ilike(f.manager)
        conditions.append(sec_managers.c.firm_name.ilike(f"%{escaped}%"))
    return conditions


def _etf_branch(f: CatalogFilters) -> Select | None:
    """ETFs from sec_etfs (985 rows, N-CEN sourced)."""
    cats = _parse_categories(f.fund_universe)
    if cats is not None and "etf" not in cats:
        return None
    if f.region and f.region != "US":
        return None

    stmt = (
        select(
            literal("registered_us").label("universe"),
            sec_etfs.c.series_id.label("external_id"),
            sec_etfs.c.fund_name.label("name"),
            sec_etfs.c.ticker,
            sec_etfs.c.isin,
            literal("US").label("region"),
            literal("etf").label("fund_type"),
            sec_etfs.c.strategy_label,
            sec_etfs.c.monthly_avg_net_assets.label("aum"),
            sec_etfs.c.currency,
            sec_etfs.c.domicile,
            literal_column("NULL").label("manager_name"),
            literal_column("NULL").label("manager_id"),
            sec_etfs.c.inception_date,
            literal_column("NULL").label("total_shareholder_accounts"),
            literal_column("NULL").label("investor_count"),
            literal_column("NULL").label("series_id"),
            literal_column("NULL").label("series_name"),
            literal_column("NULL").label("class_id"),
            literal_column("NULL").label("class_name"),
            literal(True).label("has_holdings"),
            (sec_etfs.c.ticker.isnot(None)).label("has_nav"),
            literal(False).label("has_13f_overlay"),
            _geography_case(
                sec_etfs.c.fund_name,
                sec_etfs.c.strategy_label,
                default="US",
            ),
            literal_column("NULL").label("vintage_year"),
            # Fee & performance (ETFs have prospectus stats via series_id)
            sec_fund_prospectus_stats.c.expense_ratio_pct,
            sec_fund_prospectus_stats.c.avg_annual_return_1y,
            sec_fund_prospectus_stats.c.avg_annual_return_10y,
            # N-CEN flags (ETFs don't have these in sec_etfs table)
            literal_column("NULL").label("is_index"),
            literal_column("NULL").label("is_target_date"),
            literal_column("NULL").label("is_fund_of_fund"),
        )
        .select_from(sec_etfs)
        .outerjoin(
            sec_fund_prospectus_stats,
            sec_etfs.c.series_id == sec_fund_prospectus_stats.c.series_id,
        )
    )

    conditions: list[object] = []
    if f.q:
        escaped = _escape_ilike(f.q)
        pattern = f"%{escaped}%"
        conditions.append(
            sec_etfs.c.fund_name.ilike(pattern)
            | sec_etfs.c.ticker.ilike(pattern)
            | sec_etfs.c.isin.ilike(pattern),
        )
    if f.strategy_label:
        sl_list = [v.strip() for v in f.strategy_label.split(",") if v.strip()]
        if len(sl_list) == 1:
            conditions.append(sec_etfs.c.strategy_label == sl_list[0])
        elif sl_list:
            conditions.append(sec_etfs.c.strategy_label.in_(sl_list))
    if f.aum_min is not None:
        conditions.append(sec_etfs.c.monthly_avg_net_assets >= int(f.aum_min))
    if f.has_nav is True:
        conditions.append(sec_etfs.c.ticker.isnot(None))
    if f.domicile:
        conditions.append(sec_etfs.c.domicile == f.domicile)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    return stmt


def _bdc_branch(f: CatalogFilters) -> Select | None:
    """BDCs from sec_bdcs (196 rows, N-CEN sourced)."""
    cats = _parse_categories(f.fund_universe)
    if cats is not None and "bdc" not in cats:
        return None
    if f.region and f.region != "US":
        return None

    stmt = (
        select(
            literal("registered_us").label("universe"),
            sec_bdcs.c.series_id.label("external_id"),
            sec_bdcs.c.fund_name.label("name"),
            sec_bdcs.c.ticker,
            sec_bdcs.c.isin,
            literal("US").label("region"),
            literal("bdc").label("fund_type"),
            sec_bdcs.c.strategy_label,
            sec_bdcs.c.monthly_avg_net_assets.label("aum"),
            sec_bdcs.c.currency,
            sec_bdcs.c.domicile,
            literal_column("NULL").label("manager_name"),
            literal_column("NULL").label("manager_id"),
            sec_bdcs.c.inception_date,
            literal_column("NULL").label("total_shareholder_accounts"),
            literal_column("NULL").label("investor_count"),
            literal_column("NULL").label("series_id"),
            literal_column("NULL").label("series_name"),
            literal_column("NULL").label("class_id"),
            literal_column("NULL").label("class_name"),
            literal(True).label("has_holdings"),
            (sec_bdcs.c.ticker.isnot(None)).label("has_nav"),
            literal(False).label("has_13f_overlay"),
            _geography_case(
                sec_bdcs.c.fund_name,
                sec_bdcs.c.strategy_label,
                default="US",
            ),
            literal_column("NULL").label("vintage_year"),
            # Fee & performance (BDCs have prospectus stats via series_id)
            sec_fund_prospectus_stats.c.expense_ratio_pct,
            sec_fund_prospectus_stats.c.avg_annual_return_1y,
            sec_fund_prospectus_stats.c.avg_annual_return_10y,
            # N-CEN flags (BDCs don't have these in sec_bdcs table)
            literal_column("NULL").label("is_index"),
            literal_column("NULL").label("is_target_date"),
            literal_column("NULL").label("is_fund_of_fund"),
        )
        .select_from(sec_bdcs)
        .outerjoin(
            sec_fund_prospectus_stats,
            sec_bdcs.c.series_id == sec_fund_prospectus_stats.c.series_id,
        )
    )

    conditions: list[object] = []
    if f.q:
        escaped = _escape_ilike(f.q)
        pattern = f"%{escaped}%"
        conditions.append(
            sec_bdcs.c.fund_name.ilike(pattern)
            | sec_bdcs.c.ticker.ilike(pattern)
            | sec_bdcs.c.isin.ilike(pattern),
        )
    if f.strategy_label:
        sl_list = [v.strip() for v in f.strategy_label.split(",") if v.strip()]
        if len(sl_list) == 1:
            conditions.append(sec_bdcs.c.strategy_label == sl_list[0])
        elif sl_list:
            conditions.append(sec_bdcs.c.strategy_label.in_(sl_list))
    if f.aum_min is not None:
        conditions.append(sec_bdcs.c.monthly_avg_net_assets >= int(f.aum_min))
    if f.has_nav is True:
        conditions.append(sec_bdcs.c.ticker.isnot(None))
    if f.domicile:
        conditions.append(sec_bdcs.c.domicile == f.domicile)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    return stmt


def _private_us_branch(f: CatalogFilters) -> Select | None:
    """Private US funds (hedge, PE, VC) from sec_manager_funds."""
    cats = _parse_categories(f.fund_universe)
    if cats is not None:
        priv_cats = cats & {"hedge_fund", "private_fund"}
        if not priv_cats:
            return None
    else:
        priv_cats = None  # all private types
    if f.region and f.region != "US":
        return None
    if f.has_nav is True:
        return None

    _priv_mgr_cik = (
        select(sec_managers.c.cik)
        .where(sec_managers.c.crd_number == sec_manager_funds.c.crd_number)
        .correlate(sec_manager_funds)
        .scalar_subquery()
    )
    _priv_13f_exists = (
        select(literal(True))
        .select_from(sec_13f_holdings)
        .where(sec_13f_holdings.c.cik == _priv_mgr_cik)
        .where(sec_13f_holdings.c.report_date >= func.current_date() - 180)
        .correlate(sec_manager_funds)
        .exists()
    )

    stmt = (
        select(
            literal("private_us").label("universe"),
            func.cast(sec_manager_funds.c.id, Text).label("external_id"),
            sec_manager_funds.c.fund_name.label("name"),
            literal_column("NULL").label("ticker"),
            literal_column("NULL").label("isin"),
            literal("US").label("region"),
            sec_manager_funds.c.fund_type,
            sec_manager_funds.c.strategy_label,
            sec_manager_funds.c.gross_asset_value.label("aum"),
            literal("USD").label("currency"),
            literal("US").label("domicile"),
            sec_managers.c.firm_name.label("manager_name"),
            sec_managers.c.crd_number.label("manager_id"),
            literal_column("NULL").label("inception_date"),
            literal_column("NULL").label("total_shareholder_accounts"),
            sec_manager_funds.c.investor_count,
            literal_column("NULL").label("series_id"),
            literal_column("NULL").label("series_name"),
            literal_column("NULL").label("class_id"),
            literal_column("NULL").label("class_name"),
            literal(False).label("has_holdings"),
            literal(False).label("has_nav"),
            _priv_13f_exists.label("has_13f_overlay"),
            _geography_case(
                sec_manager_funds.c.fund_name,
                sec_manager_funds.c.strategy_label,
                default="Global",
            ),
            sec_manager_funds.c.vintage_year,
            # No prospectus data for private funds
            literal_column("NULL").label("expense_ratio_pct"),
            literal_column("NULL").label("avg_annual_return_1y"),
            literal_column("NULL").label("avg_annual_return_10y"),
            # No N-CEN flags for private funds
            literal_column("NULL").label("is_index"),
            literal_column("NULL").label("is_target_date"),
            sec_manager_funds.c.is_fund_of_funds.label("is_fund_of_fund"),
        )
        .select_from(sec_manager_funds)
        .join(
            sec_managers,
            sec_manager_funds.c.crd_number == sec_managers.c.crd_number,
        )
    )

    conditions: list = []
    # Category-based hedge / non-hedge restriction
    if priv_cats is not None:
        if priv_cats == {"hedge_fund"}:
            conditions.append(sec_manager_funds.c.fund_type == "Hedge Fund")
        elif priv_cats == {"private_fund"}:
            conditions.append(sec_manager_funds.c.fund_type != "Hedge Fund")
        # If both selected → no extra filter (show all private)

    if f.q:
        escaped = _escape_ilike(f.q)
        pattern = f"%{escaped}%"
        conditions.append(
            sec_manager_funds.c.fund_name.ilike(pattern)
            | sec_managers.c.firm_name.ilike(pattern),
        )
    if f.fund_type:
        ft_list = [v.strip() for v in f.fund_type.split(",") if v.strip()]
        if len(ft_list) == 1:
            conditions.append(sec_manager_funds.c.fund_type == ft_list[0])
        elif ft_list:
            conditions.append(sec_manager_funds.c.fund_type.in_(ft_list))
    if f.strategy_label:
        sl_list = [v.strip() for v in f.strategy_label.split(",") if v.strip()]
        if len(sl_list) == 1:
            conditions.append(sec_manager_funds.c.strategy_label == sl_list[0])
        elif sl_list:
            conditions.append(sec_manager_funds.c.strategy_label.in_(sl_list))
    if f.aum_min is not None:
        conditions.append(sec_manager_funds.c.gross_asset_value >= int(f.aum_min))
    if f.domicile:
        if f.domicile != "US":
            return None
    if f.manager:
        escaped = _escape_ilike(f.manager)
        conditions.append(sec_managers.c.firm_name.ilike(f"%{escaped}%"))

    if conditions:
        stmt = stmt.where(and_(*conditions))
    return stmt


def _ucits_eu_branch(f: CatalogFilters) -> Select | None:
    """EU UCITS funds from esma_funds (only with yahoo_ticker resolved)."""
    cats = _parse_categories(f.fund_universe)
    if cats is not None and "ucits" not in cats:
        return None
    if f.region and f.region != "EU":
        return None

    stmt = (
        select(
            literal("ucits_eu").label("universe"),
            esma_funds.c.isin.label("external_id"),
            esma_funds.c.fund_name.label("name"),
            esma_funds.c.yahoo_ticker.label("ticker"),
            esma_funds.c.isin,
            literal("EU").label("region"),
            esma_funds.c.fund_type,
            esma_funds.c.strategy_label,
            literal_column("NULL").label("aum"),
            literal_column("NULL").label("currency"),
            esma_funds.c.domicile,
            esma_managers.c.company_name.label("manager_name"),
            esma_managers.c.esma_id.label("manager_id"),
            literal_column("NULL").label("inception_date"),
            literal_column("NULL").label("total_shareholder_accounts"),
            literal_column("NULL").label("investor_count"),
            literal_column("NULL").label("series_id"),
            literal_column("NULL").label("series_name"),
            literal_column("NULL").label("class_id"),
            literal_column("NULL").label("class_name"),
            literal(False).label("has_holdings"),
            literal(True).label("has_nav"),
            literal(False).label("has_13f_overlay"),
            _geography_case(
                esma_funds.c.fund_name,
                esma_funds.c.strategy_label,
                default="Europe",
            ),
            literal_column("NULL").label("vintage_year"),
            # No prospectus data for UCITS funds
            literal_column("NULL").label("expense_ratio_pct"),
            literal_column("NULL").label("avg_annual_return_1y"),
            literal_column("NULL").label("avg_annual_return_10y"),
            # No N-CEN flags for UCITS
            literal_column("NULL").label("is_index"),
            literal_column("NULL").label("is_target_date"),
            literal_column("NULL").label("is_fund_of_fund"),
        )
        .select_from(esma_funds)
        .join(esma_managers, esma_funds.c.esma_manager_id == esma_managers.c.esma_id)
        .where(esma_funds.c.yahoo_ticker.isnot(None))
        .where(esma_funds.c.yahoo_ticker != "")
    )

    conditions: list = []
    if f.q:
        escaped = _escape_ilike(f.q)
        pattern = f"%{escaped}%"
        conditions.append(
            esma_funds.c.fund_name.ilike(pattern)
            | esma_funds.c.isin.ilike(pattern)
            | esma_funds.c.yahoo_ticker.ilike(pattern)
            | esma_managers.c.company_name.ilike(pattern),
        )
    if f.fund_type:
        ft_list = [v.strip() for v in f.fund_type.split(",") if v.strip()]
        if len(ft_list) == 1:
            conditions.append(esma_funds.c.fund_type == ft_list[0])
        elif ft_list:
            conditions.append(esma_funds.c.fund_type.in_(ft_list))
    if f.strategy_label:
        sl_list = [v.strip() for v in f.strategy_label.split(",") if v.strip()]
        if len(sl_list) == 1:
            conditions.append(esma_funds.c.strategy_label == sl_list[0])
        elif sl_list:
            conditions.append(esma_funds.c.strategy_label.in_(sl_list))
    if f.aum_min is not None:
        return None
    if f.domicile:
        conditions.append(esma_funds.c.domicile == f.domicile)
    if f.manager:
        escaped = _escape_ilike(f.manager)
        conditions.append(esma_managers.c.company_name.ilike(f"%{escaped}%"))

    if conditions:
        stmt = stmt.where(and_(*conditions))
    return stmt


# ═══════════════════════════════════════════════════════════════════════════
#  Public API
# ═══════════════════════════════════════════════════════════════════════════


_SORT_MAP = {
    "name_asc": "REGEXP_REPLACE(name, '^[^a-zA-Z]+', '', 'g') ASC, name ASC",
    "name_desc": "REGEXP_REPLACE(name, '^[^a-zA-Z]+', '', 'g') DESC, name DESC",
    "aum_desc": "aum DESC NULLS LAST",
    "aum_asc": "aum ASC NULLS LAST",
    "manager_asc": "manager_name ASC NULLS LAST",
    "manager_desc": "manager_name DESC NULLS LAST",
    "strategy_asc": "strategy_label ASC NULLS LAST",
    "strategy_desc": "strategy_label DESC NULLS LAST",
}


def _all_branches(filters: CatalogFilters) -> list[Select]:
    return [
        b
        for b in [
            _registered_us_branch(filters),
            _etf_branch(filters),
            _bdc_branch(filters),
            _private_us_branch(filters),
            _ucits_eu_branch(filters),
        ]
        if b is not None
    ]


def build_catalog_query(filters: CatalogFilters) -> Select | None:
    """Build paginated UNION ALL query with count() OVER() window.

    Returns None if all branches are pruned by filters.
    """
    branches = _all_branches(filters)
    if not branches:
        return None

    combined = union_all(*branches).subquery("catalog")

    sort_expr = literal_column(_SORT_MAP.get(filters.sort, "name ASC"))
    offset = (filters.page - 1) * filters.page_size

    stmt = select(combined, func.count().over().label("_total"))

    # Apply investment_geography filter on the UNION ALL result
    if filters.investment_geography:
        geo_list = [v.strip() for v in filters.investment_geography.split(",") if v.strip()]
        if len(geo_list) == 1:
            stmt = stmt.where(combined.c.investment_geography == geo_list[0])
        elif geo_list:
            stmt = stmt.where(combined.c.investment_geography.in_(geo_list))

    return (
        stmt
        .order_by(sort_expr)
        .offset(offset)
        .limit(filters.page_size)
    )


def build_catalog_facets_query(filters: CatalogFilters) -> Select | None:
    """Build facet aggregation query over the unified catalog.

    Returns counts grouped by universe, region, fund_type, strategy_label,
    domicile, investment_geography.
    Uses a single scan with grouping sets for efficiency.
    """
    facet_filters = CatalogFilters(
        q=filters.q,
        region=filters.region,
        fund_universe=filters.fund_universe,
        fund_type=filters.fund_type,
        strategy_label=filters.strategy_label,
        investment_geography=filters.investment_geography,
        aum_min=filters.aum_min,
        has_nav=filters.has_nav,
        domicile=filters.domicile,
        manager=filters.manager,
        page=1,
        page_size=1_000_000,
    )
    branches = _all_branches(facet_filters)
    if not branches:
        return None

    combined = union_all(*branches).subquery("catalog_facets")

    stmt = select(
        combined.c.universe,
        combined.c.region,
        combined.c.fund_type,
        combined.c.strategy_label,
        combined.c.domicile,
        combined.c.investment_geography,
        func.count().label("cnt"),
    ).group_by(
        combined.c.universe,
        combined.c.region,
        combined.c.fund_type,
        combined.c.strategy_label,
        combined.c.domicile,
        combined.c.investment_geography,
    )

    # Apply geography filter to facet query too
    if filters.investment_geography:
        geo_list = [v.strip() for v in filters.investment_geography.split(",") if v.strip()]
        if len(geo_list) == 1:
            stmt = stmt.where(combined.c.investment_geography == geo_list[0])
        elif geo_list:
            stmt = stmt.where(combined.c.investment_geography.in_(geo_list))

    return stmt
