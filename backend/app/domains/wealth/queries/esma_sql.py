"""ESMA query builder.

Pure query builder — constructs SQLAlchemy Core Select statements.
Tables are global (no organization_id, no RLS).
Text search: ILIKE with _escape_ilike().
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import (
    Column,
    MetaData,
    Select,
    Table,
    Text,
    and_,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import ARRAY

# ═══════════════════════════════════════════════════════════════════
#  Reflected tables (Core-style, not ORM)
# ═══════════════════════════════════════════════════════════════════

_meta = MetaData()

esma_managers = Table(
    "esma_managers",
    _meta,
    Column("esma_id", Text, primary_key=True),
    Column("lei", Text),
    Column("company_name", Text, nullable=False),
    Column("country", Text),
    Column("authorization_status", Text),
    Column("fund_count", Text),
    Column("sec_crd_number", Text),
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

sec_managers = Table(
    "sec_managers",
    _meta,
    Column("crd_number", Text, primary_key=True),
    Column("firm_name", Text),
    extend_existing=True,
)

# ═══════════════════════════════════════════════════════════════════
#  Text search escaping
# ═══════════════════════════════════════════════════════════════════

_ILIKE_ESCAPE_RE = re.compile(r"([%_\\])")


def _escape_ilike(text: str) -> str:
    """Escape ILIKE special characters."""
    return _ILIKE_ESCAPE_RE.sub(r"\\\1", text)


# ═══════════════════════════════════════════════════════════════════
#  Filter dataclasses
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class EsmaManagerFilters:
    country: str | None = None
    search: str | None = None
    page: int = 1
    page_size: int = 50


@dataclass(frozen=True)
class EsmaFundFilters:
    domicile: str | None = None
    fund_type: str | None = None
    search: str | None = None
    page: int = 1
    page_size: int = 50


# ═══════════════════════════════════════════════════════════════════
#  Query builders
# ═══════════════════════════════════════════════════════════════════


def build_manager_list_queries(
    filters: EsmaManagerFilters,
) -> tuple[Select, Select]:
    """Build data + count queries for paginated manager list."""
    conditions: list = []

    if filters.country:
        conditions.append(esma_managers.c.country == filters.country)
    if filters.search:
        escaped = _escape_ilike(filters.search)
        conditions.append(esma_managers.c.company_name.ilike(f"%{escaped}%"))

    where = and_(*conditions) if conditions else None

    base = select(
        esma_managers.c.esma_id,
        esma_managers.c.company_name,
        esma_managers.c.country,
        esma_managers.c.authorization_status,
        esma_managers.c.sec_crd_number,
        esma_managers.c.fund_count,
    )
    if where is not None:
        base = base.where(where)

    data_q = (
        base
        .order_by(esma_managers.c.company_name)
        .limit(filters.page_size)
        .offset((filters.page - 1) * filters.page_size)
    )

    count_base = select(func.count()).select_from(esma_managers)
    if where is not None:
        count_base = count_base.where(where)

    return data_q, count_base


def build_manager_detail_query(esma_id: str) -> Select:
    """Query single manager by esma_id."""
    return (
        select(
            esma_managers.c.esma_id,
            esma_managers.c.company_name,
            esma_managers.c.country,
            esma_managers.c.authorization_status,
            esma_managers.c.sec_crd_number,
        )
        .where(esma_managers.c.esma_id == esma_id)
    )


def build_manager_funds_query(esma_id: str) -> Select:
    """Query all funds for a given manager."""
    return (
        select(
            esma_funds.c.isin,
            esma_funds.c.fund_name,
            esma_funds.c.domicile,
            esma_funds.c.fund_type,
            esma_funds.c.yahoo_ticker,
            esma_funds.c.esma_manager_id,
        )
        .where(esma_funds.c.esma_manager_id == esma_id)
        .order_by(esma_funds.c.fund_name)
    )


def build_fund_list_queries(
    filters: EsmaFundFilters,
) -> tuple[Select, Select]:
    """Build data + count queries for paginated fund list."""
    conditions: list = []

    if filters.domicile:
        conditions.append(esma_funds.c.domicile == filters.domicile)
    if filters.fund_type:
        conditions.append(esma_funds.c.fund_type == filters.fund_type)
    if filters.search:
        escaped = _escape_ilike(filters.search)
        conditions.append(esma_funds.c.fund_name.ilike(f"%{escaped}%"))

    where = and_(*conditions) if conditions else None

    base = select(
        esma_funds.c.isin,
        esma_funds.c.fund_name,
        esma_funds.c.domicile,
        esma_funds.c.fund_type,
        esma_funds.c.yahoo_ticker,
        esma_funds.c.esma_manager_id,
    )
    if where is not None:
        base = base.where(where)

    data_q = (
        base
        .order_by(esma_funds.c.fund_name)
        .limit(filters.page_size)
        .offset((filters.page - 1) * filters.page_size)
    )

    count_base = select(func.count()).select_from(esma_funds)
    if where is not None:
        count_base = count_base.where(where)

    return data_q, count_base


def build_fund_detail_query(isin: str) -> Select:
    """Query single fund with joined manager info."""
    return (
        select(
            esma_funds.c.isin,
            esma_funds.c.fund_name,
            esma_funds.c.domicile,
            esma_funds.c.fund_type,
            esma_funds.c.yahoo_ticker,
            esma_managers.c.esma_id.label("mgr_esma_id"),
            esma_managers.c.company_name.label("mgr_company_name"),
            esma_managers.c.country.label("mgr_country"),
            esma_managers.c.authorization_status.label("mgr_authorization_status"),
            esma_managers.c.sec_crd_number.label("mgr_sec_crd_number"),
            esma_managers.c.fund_count.label("mgr_fund_count"),
        )
        .join(
            esma_managers,
            esma_funds.c.esma_manager_id == esma_managers.c.esma_id,
            isouter=True,
        )
        .where(esma_funds.c.isin == isin)
    )


def build_sec_crossref_query(esma_id: str) -> Select:
    """Query SEC cross-reference for a given ESMA manager."""
    return (
        select(
            esma_managers.c.esma_id,
            esma_managers.c.sec_crd_number,
            sec_managers.c.firm_name.label("sec_firm_name"),
        )
        .outerjoin(
            sec_managers,
            esma_managers.c.sec_crd_number == sec_managers.c.crd_number,
        )
        .where(esma_managers.c.esma_id == esma_id)
    )
