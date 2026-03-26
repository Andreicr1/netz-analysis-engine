"""Pure query builder for the Unified Fund Catalog.

Constructs a UNION ALL of three universes (registered_us, private_us,
ucits_eu) with composable filters.  Zero I/O — frozen dataclass input,
SQLAlchemy Core Select output.

Tables are ALL global (no organization_id, no RLS).

Performance notes:
- ~50k registered + ~50k private + ~30k UCITS (tickered) ≈ 130k rows
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
    Select,
    Table,
    Text,
    and_,
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
    Column("ticker", Text),
    Column("isin", Text),
    Column("total_assets", BigInteger),
    Column("total_shareholder_accounts", Integer),
    Column("inception_date", Date),
    Column("currency", Text),
    Column("domicile", Text),
    Column("last_nport_date", Date),
    Column("aum_below_threshold", Boolean),
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
    Column("gross_asset_value", BigInteger),
    Column("investor_count", Integer),
    Column("is_fund_of_funds", Boolean),
)

sec_13f_holdings = Table(
    "sec_13f_holdings",
    _meta,
    Column("report_date", Date, primary_key=True),
    Column("cik", Text, primary_key=True),
    Column("cusip", Text, primary_key=True),
    extend_existing=True,
)

esma_funds = Table(
    "esma_funds",
    _meta,
    Column("isin", Text, primary_key=True),
    Column("fund_name", Text, nullable=False),
    Column("esma_manager_id", Text),
    Column("domicile", Text),
    Column("fund_type", Text),
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
    region: str | None = None          # US | EU
    fund_universe: str | None = None   # registered | private | ucits | all
    fund_type: str | None = None       # mutual_fund | etf | hedge_fund | pe | vc | ucits ...
    aum_min: float | None = None
    has_nav: bool | None = None        # True = only funds with ticker
    domicile: str | None = None
    manager: str | None = None         # text search on manager name
    sort: str = "name_asc"             # name_asc | name_desc | aum_desc | aum_asc
    page: int = 1
    page_size: int = 50


# ═══════════════════════════════════════════════════════════════════════════
#  Branch builders
# ═══════════════════════════════════════════════════════════════════════════


def _registered_us_branch(f: CatalogFilters) -> Select | None:
    """Registered US funds (mutual, ETF) from sec_registered_funds."""
    if f.fund_universe and f.fund_universe not in ("registered", "all"):
        return None
    if f.region and f.region != "US":
        return None

    # Check if the fund's manager also files 13F (for overlay flag).
    # sec_managers.cik is the firm's CIK used for 13F filings.
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

    stmt = (
        select(
            literal("registered_us").label("universe"),
            sec_registered_funds.c.cik.label("external_id"),
            sec_registered_funds.c.fund_name.label("name"),
            sec_registered_funds.c.ticker,
            sec_registered_funds.c.isin,
            literal("US").label("region"),
            sec_registered_funds.c.fund_type,
            sec_registered_funds.c.total_assets.label("aum"),
            sec_registered_funds.c.currency,
            sec_registered_funds.c.domicile,
            sec_managers.c.firm_name.label("manager_name"),
            sec_managers.c.crd_number.label("manager_id"),
            sec_registered_funds.c.inception_date,
            sec_registered_funds.c.total_shareholder_accounts,
            literal_column("NULL").label("investor_count"),
            # disclosure booleans — computed at SQL level for facets
            literal(True).label("has_holdings"),
            (sec_registered_funds.c.ticker.isnot(None)).label("has_nav"),
            _13f_exists.label("has_13f_overlay"),
        )
        .select_from(sec_registered_funds)
        .outerjoin(
            sec_managers,
            sec_registered_funds.c.crd_number == sec_managers.c.crd_number,
        )
    )

    conditions = _common_conditions_registered(f)
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
            | sec_registered_funds.c.ticker.ilike(pattern)
            | sec_registered_funds.c.isin.ilike(pattern)
            | sec_managers.c.firm_name.ilike(pattern)
        )
    if f.fund_type:
        conditions.append(sec_registered_funds.c.fund_type == f.fund_type)
    if f.aum_min is not None:
        conditions.append(sec_registered_funds.c.total_assets >= int(f.aum_min))
    if f.has_nav is True:
        conditions.append(sec_registered_funds.c.ticker.isnot(None))
    if f.domicile:
        conditions.append(sec_registered_funds.c.domicile == f.domicile)
    if f.manager:
        escaped = _escape_ilike(f.manager)
        conditions.append(sec_managers.c.firm_name.ilike(f"%{escaped}%"))
    return conditions


def _private_us_branch(f: CatalogFilters) -> Select | None:
    """Private US funds (hedge, PE, VC) from sec_manager_funds."""
    if f.fund_universe and f.fund_universe not in ("private", "all"):
        return None
    if f.region and f.region != "US":
        return None
    # Private funds never have NAV
    if f.has_nav is True:
        return None

    # Check if the private fund's manager also files 13F.
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
            sec_manager_funds.c.gross_asset_value.label("aum"),
            literal("USD").label("currency"),
            literal("US").label("domicile"),
            sec_managers.c.firm_name.label("manager_name"),
            sec_managers.c.crd_number.label("manager_id"),
            literal_column("NULL").label("inception_date"),
            literal_column("NULL").label("total_shareholder_accounts"),
            sec_manager_funds.c.investor_count,
            # disclosure
            literal(False).label("has_holdings"),
            literal(False).label("has_nav"),
            _priv_13f_exists.label("has_13f_overlay"),
        )
        .select_from(sec_manager_funds)
        .join(
            sec_managers,
            sec_manager_funds.c.crd_number == sec_managers.c.crd_number,
        )
    )

    conditions: list = []
    if f.q:
        escaped = _escape_ilike(f.q)
        pattern = f"%{escaped}%"
        conditions.append(
            sec_manager_funds.c.fund_name.ilike(pattern)
            | sec_managers.c.firm_name.ilike(pattern)
        )
    if f.fund_type:
        conditions.append(sec_manager_funds.c.fund_type == f.fund_type)
    if f.aum_min is not None:
        conditions.append(sec_manager_funds.c.gross_asset_value >= int(f.aum_min))
    if f.domicile:
        # Private US = always US domicile
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
    if f.fund_universe and f.fund_universe not in ("ucits", "all"):
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
            literal_column("NULL").label("aum"),
            literal_column("NULL").label("currency"),
            esma_funds.c.domicile,
            esma_managers.c.company_name.label("manager_name"),
            esma_managers.c.esma_id.label("manager_id"),
            literal_column("NULL").label("inception_date"),
            literal_column("NULL").label("total_shareholder_accounts"),
            literal_column("NULL").label("investor_count"),
            # disclosure
            literal(False).label("has_holdings"),
            literal(True).label("has_nav"),  # all have ticker (WHERE filter)
            literal(False).label("has_13f_overlay"),
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
            | esma_managers.c.company_name.ilike(pattern)
        )
    if f.fund_type:
        conditions.append(esma_funds.c.fund_type == f.fund_type)
    # ESMA has no AUM — if aum_min set, skip this branch
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
    "name_asc": "name ASC",
    "name_desc": "name DESC",
    "aum_desc": "aum DESC NULLS LAST",
    "aum_asc": "aum ASC NULLS LAST",
}


def build_catalog_query(filters: CatalogFilters) -> Select | None:
    """Build paginated UNION ALL query with count() OVER() window.

    Returns None if all branches are pruned by filters.
    """
    branches = [
        b
        for b in [
            _registered_us_branch(filters),
            _private_us_branch(filters),
            _ucits_eu_branch(filters),
        ]
        if b is not None
    ]

    if not branches:
        return None

    combined = union_all(*branches).subquery("catalog")

    sort_expr = literal_column(_SORT_MAP.get(filters.sort, "name ASC"))
    offset = (filters.page - 1) * filters.page_size

    return (
        select(combined, func.count().over().label("_total"))
        .order_by(sort_expr)
        .offset(offset)
        .limit(filters.page_size)
    )


def build_catalog_facets_query(filters: CatalogFilters) -> Select | None:
    """Build facet aggregation query over the unified catalog.

    Returns counts grouped by universe, region, fund_type, domicile.
    Uses a single scan with grouping sets for efficiency.
    """
    # Build a simplified UNION ALL without pagination for facet counting.
    # Override pagination-related filter fields.
    facet_filters = CatalogFilters(
        q=filters.q,
        region=filters.region,
        fund_universe=filters.fund_universe,
        fund_type=filters.fund_type,
        aum_min=filters.aum_min,
        has_nav=filters.has_nav,
        domicile=filters.domicile,
        manager=filters.manager,
        page=1,
        page_size=1_000_000,  # no limit for facets
    )
    branches = [
        b
        for b in [
            _registered_us_branch(facet_filters),
            _private_us_branch(facet_filters),
            _ucits_eu_branch(facet_filters),
        ]
        if b is not None
    ]

    if not branches:
        return None

    combined = union_all(*branches).subquery("catalog_facets")

    return select(
        combined.c.universe,
        combined.c.region,
        combined.c.fund_type,
        combined.c.domicile,
        func.count().label("cnt"),
    ).group_by(
        combined.c.universe,
        combined.c.region,
        combined.c.fund_type,
        combined.c.domicile,
    )
