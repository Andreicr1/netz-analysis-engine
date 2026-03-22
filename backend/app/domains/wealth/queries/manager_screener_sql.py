"""Pure query builder for the Manager Screener.

Constructs dynamic SQLAlchemy Core ``Select`` statements for the screener
list endpoint.  Zero I/O — frozen dataclass input, Select output.

Reads from:
  - ``sec_managers`` (catalog)
  - ``sec_13f_holdings_agg`` (continuous aggregate, created by migration 0038)
  - ``sec_13f_drift_agg``   (continuous aggregate, created by migration 0038)
  - ``instruments_universe`` (tenant-scoped, for universe status overlay)

No imports from ``app.domains`` routes or services.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    Integer,
    MetaData,
    Select,
    String,
    Table,
    Text,
    and_,
    cast,
    func,
    literal_column,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# ═══════════════════════════════════════════════════════════════════════════
#  Reflected tables (Core-style, not ORM)
# ═══════════════════════════════════════════════════════════════════════════

_meta = MetaData()

sec_managers = Table(
    "sec_managers",
    _meta,
    Column("crd_number", Text, primary_key=True),
    Column("cik", Text),
    Column("firm_name", Text, nullable=False),
    Column("sec_number", Text),
    Column("registration_status", Text),
    Column("aum_total", BigInteger),
    Column("aum_discretionary", BigInteger),
    Column("aum_non_discretionary", BigInteger),
    Column("total_accounts", Integer),
    Column("fee_types", JSONB),
    Column("client_types", JSONB),
    Column("state", Text),
    Column("country", Text),
    Column("website", Text),
    Column("compliance_disclosures", Integer),
    Column("last_adv_filed_at", Date),
    extend_existing=True,
)

holdings_agg = Table(
    "sec_13f_holdings_agg",
    _meta,
    Column("cik", Text),
    Column("quarter", Date),
    Column("sector", Text),
    Column("sector_value", BigInteger),
    Column("position_count", Integer),
    extend_existing=True,
)

drift_agg = Table(
    "sec_13f_drift_agg",
    _meta,
    Column("cik", Text),
    Column("quarter", Date),
    Column("churn_count", Integer),
    Column("total_changes", Integer),
    extend_existing=True,
)

instruments_universe = Table(
    "instruments_universe",
    _meta,
    Column("instrument_id", Text, primary_key=True),
    Column("organization_id", Text),
    Column("name", Text),
    Column("approval_status", String(20)),
    Column("attributes", JSONB),
    Column("is_active", Text),
    extend_existing=True,
)


# ═══════════════════════════════════════════════════════════════════════════
#  Filters dataclass
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ScreenerFilters:
    """All filter blocks for the manager screener list."""

    # Block 1 — Firma
    aum_min: int | None = None
    aum_max: int | None = None
    strategy_types: list[str] = field(default_factory=list)
    fee_types: list[str] = field(default_factory=list)
    states: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    registration_status: str | None = None
    compliance_clean: bool | None = None
    adv_filed_after: date | None = None
    adv_filed_before: date | None = None
    text_search: str | None = None

    # Block 2 — Portfolio (reads continuous aggregate)
    sectors: list[str] = field(default_factory=list)
    hhi_min: float | None = None
    hhi_max: float | None = None
    position_count_min: int | None = None
    position_count_max: int | None = None
    portfolio_value_min: int | None = None

    # Block 3 — Drift (reads continuous aggregate)
    style_drift_detected: bool | None = None
    turnover_min: float | None = None
    turnover_max: float | None = None
    high_activity_quarters_min: int | None = None

    # Block 4 — Institutional
    has_institutional_holders: bool | None = None
    holder_types: list[str] = field(default_factory=list)

    # Block 5 — Universe status
    universe_statuses: list[str] = field(default_factory=list)

    # Sort & pagination
    sort_by: str = "aum_total"
    sort_dir: str = "desc"
    page: int = 1
    page_size: int = 25


# ═══════════════════════════════════════════════════════════════════════════
#  Sort column allowlist (prevents ORDER BY injection)
# ═══════════════════════════════════════════════════════════════════════════

_SORT_COLUMNS: dict[str, Column] = {
    "aum_total": sec_managers.c.aum_total,
    "firm_name": sec_managers.c.firm_name,
    "compliance_disclosures": sec_managers.c.compliance_disclosures,
    "last_adv_filed_at": sec_managers.c.last_adv_filed_at,
    "state": sec_managers.c.state,
    "country": sec_managers.c.country,
}

# ═══════════════════════════════════════════════════════════════════════════
#  Text search escaping
# ═══════════════════════════════════════════════════════════════════════════

_ILIKE_ESCAPE_RE = re.compile(r"([%_\\])")


def _escape_ilike(text: str) -> str:
    """Escape ILIKE special characters."""
    return _ILIKE_ESCAPE_RE.sub(r"\\\1", text)


# ═══════════════════════════════════════════════════════════════════════════
#  Query builder
# ═══════════════════════════════════════════════════════════════════════════


def build_screener_queries(
    filters: ScreenerFilters,
    org_id: str,
    latest_quarter: date | None = None,
    drift_cutoff: date | None = None,
) -> tuple[Select, Select]:
    """Build data + count queries for the manager screener list.

    Parameters
    ----------
    filters:
        All filter blocks.
    org_id:
        Organization ID for instruments_universe join.
    latest_quarter:
        Upper bound for holdings aggregate queries. Defaults to today.
    drift_cutoff:
        Lower bound for drift aggregate queries (e.g. 2 years ago).

    Returns
    -------
    tuple of (data_query, count_query) for ``asyncio.gather()`` execution.
    """
    if latest_quarter is None:
        latest_quarter = date.today()
    if drift_cutoff is None:
        # 2 years of drift history
        drift_cutoff = date(latest_quarter.year - 2, latest_quarter.month, latest_quarter.day)

    conditions: list = []

    # ── Block 1: Firma filters ──────────────────────────────────
    if filters.aum_min is not None:
        conditions.append(sec_managers.c.aum_total >= filters.aum_min)
    if filters.aum_max is not None:
        conditions.append(sec_managers.c.aum_total <= filters.aum_max)
    if filters.states:
        conditions.append(sec_managers.c.state.in_(filters.states))
    if filters.countries:
        conditions.append(sec_managers.c.country.in_(filters.countries))
    if filters.registration_status:
        conditions.append(sec_managers.c.registration_status == filters.registration_status)
    if filters.compliance_clean is True:
        conditions.append(
            (sec_managers.c.compliance_disclosures == 0)
            | (sec_managers.c.compliance_disclosures.is_(None))
        )
    if filters.adv_filed_after:
        conditions.append(sec_managers.c.last_adv_filed_at >= filters.adv_filed_after)
    if filters.adv_filed_before:
        conditions.append(sec_managers.c.last_adv_filed_at <= filters.adv_filed_before)
    if filters.text_search:
        escaped = _escape_ilike(filters.text_search)
        conditions.append(
            sec_managers.c.firm_name.ilike(f"%{escaped}%")
        )
    if filters.fee_types:
        # fee_types JSONB contains keys like {"performance_fee": true}
        for ft in filters.fee_types:
            conditions.append(
                sec_managers.c.fee_types[ft].astext.cast(String) == "true"
            )

    # ── Holdings subquery (Block 2 uses this) ───────────────────
    # Always filter by time column for chunk pruning.
    # Two-step: first find latest quarter per CIK, then aggregate.
    latest_quarter_sub = (
        select(
            holdings_agg.c.cik,
            func.max(holdings_agg.c.quarter).label("max_quarter"),
        )
        .where(holdings_agg.c.quarter <= latest_quarter)
        .group_by(holdings_agg.c.cik)
        .subquery("latest_quarter")
    )
    latest_q_sub = (
        select(
            holdings_agg.c.cik,
            func.sum(holdings_agg.c.sector_value).label("total_value"),
            func.sum(holdings_agg.c.position_count).label("total_positions"),
        )
        .join(
            latest_quarter_sub,
            and_(
                holdings_agg.c.cik == latest_quarter_sub.c.cik,
                holdings_agg.c.quarter == latest_quarter_sub.c.max_quarter,
            ),
        )
        .group_by(holdings_agg.c.cik)
        .subquery("latest_holdings")
    )

    # ── Drift subquery (Block 3) ────────────────────────────────
    # Always include time-column filter for chunk pruning
    drift_sub = (
        select(
            drift_agg.c.cik,
            func.sum(drift_agg.c.churn_count).label("total_churn"),
            func.count().label("active_quarters"),
        )
        .where(drift_agg.c.quarter >= drift_cutoff)
        .where(drift_agg.c.quarter <= latest_quarter)
        .group_by(drift_agg.c.cik)
        .subquery("drift_summary")
    )

    # ── Universe status subquery (Block 5) ──────────────────────
    universe_sub = (
        select(
            instruments_universe.c.attributes["sec_crd_number"].astext.label("crd_number"),
            instruments_universe.c.approval_status,
        )
        .where(
            instruments_universe.c.organization_id == cast(literal_column("'" + str(org_id).replace("'", "''") + "'"), PG_UUID)
        )
        .where(instruments_universe.c.attributes["source"].astext == "sec_manager")
        .subquery("universe_status")
    )

    # ── Main query ──────────────────────────────────────────────
    base = (
        select(
            sec_managers.c.crd_number,
            sec_managers.c.firm_name,
            sec_managers.c.aum_total,
            sec_managers.c.registration_status,
            sec_managers.c.state,
            sec_managers.c.country,
            sec_managers.c.compliance_disclosures,
            latest_q_sub.c.total_value.label("portfolio_value"),
            latest_q_sub.c.total_positions.label("position_count"),
            drift_sub.c.total_churn.label("drift_churn"),
            drift_sub.c.active_quarters,
            universe_sub.c.approval_status.label("universe_status"),
        )
        .outerjoin(latest_q_sub, sec_managers.c.cik == latest_q_sub.c.cik)
        .outerjoin(drift_sub, sec_managers.c.cik == drift_sub.c.cik)
        .outerjoin(universe_sub, sec_managers.c.crd_number == universe_sub.c.crd_number)
    )

    # ── Block 2: Portfolio filters ──────────────────────────────
    if filters.position_count_min is not None:
        conditions.append(latest_q_sub.c.total_positions >= filters.position_count_min)
    if filters.position_count_max is not None:
        conditions.append(latest_q_sub.c.total_positions <= filters.position_count_max)
    if filters.portfolio_value_min is not None:
        conditions.append(latest_q_sub.c.total_value >= filters.portfolio_value_min)

    # ── Block 3: Drift filters ──────────────────────────────────
    if filters.high_activity_quarters_min is not None:
        conditions.append(drift_sub.c.active_quarters >= filters.high_activity_quarters_min)

    # ── Block 5: Universe status filters ────────────────────────
    if filters.universe_statuses:
        conditions.append(universe_sub.c.approval_status.in_(filters.universe_statuses))

    # Apply all conditions
    if conditions:
        base = base.where(and_(*conditions))

    # ── Sort ────────────────────────────────────────────────────
    sort_col = _SORT_COLUMNS.get(filters.sort_by, sec_managers.c.aum_total)
    if filters.sort_dir == "asc":
        base = base.order_by(sort_col.asc().nulls_last())
    else:
        base = base.order_by(sort_col.desc().nulls_last())

    # ── Count query (no pagination, no ordering) ────────────────
    count_query = select(func.count()).select_from(base.alias("filtered"))

    # ── Pagination ──────────────────────────────────────────────
    offset = (filters.page - 1) * filters.page_size
    data_query = base.limit(filters.page_size).offset(offset)

    return data_query, count_query
