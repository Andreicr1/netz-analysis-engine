"""Unified global search — aggregator for funds, managers, and documents.

GET /search?q=&categories=funds,managers,documents

Fan-out to existing SQL queries (catalog, manager_screener, wealth_documents).
Returns grouped results by category with a small page_size for speed.

Refactored to use mv_unified_assets for high-performance global instrument search.
"""

from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Column, MetaData, Table, Text, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.models.document import WealthDocument
from app.domains.wealth.queries.manager_screener_sql import (
    ScreenerFilters,
    build_screener_queries,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/search", tags=["search"])

VALID_CATEGORIES = {"funds", "managers", "documents"}
MAX_PER_CATEGORY = 6

# ── Reflected Materialized View ──────────────────────────────

_meta = MetaData()
mv_unified_assets = Table(
    "mv_unified_assets",
    _meta,
    Column("id", Text, primary_key=True),
    Column("name", Text),
    Column("ticker", Text),
    Column("isin", Text),
    Column("asset_class", Text),
    Column("source", Text),
    Column("geography", Text),
)

# ── Response schemas ────────────────────────────────────────


class SearchResultItem(BaseModel):
    id: str
    title: str
    subtitle: str | None = None
    category: str
    href: str


class SearchCategoryGroup(BaseModel):
    category: str
    label: str
    items: list[SearchResultItem]
    total: int


class GlobalSearchResponse(BaseModel):
    query: str
    groups: list[SearchCategoryGroup]


# ── Route ───────────────────────────────────────────────────


from app.core.security.clerk_auth import CurrentUser, get_current_user
from app.core.tenancy.middleware import get_org_id
from app.domains.wealth.schemas.holdings import HoldingHolder, ReverseLookupResponse


@router.get(
    "",
    response_model=GlobalSearchResponse,
    summary="Global search across funds, managers, and documents",
)
async def global_search(
    q: str = Query(..., min_length=2, max_length=200),
    categories: str = Query("funds,managers,documents", description="Comma-separated categories"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: str = Depends(get_org_id),
) -> GlobalSearchResponse:
    """Fan-out search across funds, managers, and documents."""
    cats = {c.strip() for c in categories.split(",") if c.strip() in VALID_CATEGORIES}
    if not cats:
        cats = VALID_CATEGORIES

    tasks = []
    if "funds" in cats:
        tasks.append(_search_assets(db, q))
    if "managers" in cats:
        tasks.append(_search_managers(db, q, org_id))
    if "documents" in cats:
        tasks.append(_search_documents(db, q))

    groups = await asyncio.gather(*tasks, return_exceptions=True)
    valid_groups = [g for g in groups if isinstance(g, SearchCategoryGroup) and g.items]

    return GlobalSearchResponse(query=q, groups=valid_groups)


@router.get(
    "/holdings/reverse",
    response_model=ReverseLookupResponse,
    summary="Reverse lookup: find institutional holders of a CUSIP/ISIN",
)
async def reverse_holdings_lookup(
    cusip: str | None = Query(None),
    isin: str | None = Query(None),
    db: AsyncSession = Depends(get_db_with_rls),
) -> ReverseLookupResponse:
    """Find which Managers (13F) and Funds (N-PORT) hold a specific asset."""
    if not cusip and not isin:
        raise HTTPException(status_code=400, detail="CUSIP or ISIN required")

    from sqlalchemy import text
    
    # 1. Search Managers (13F)
    # Note: market_value in 13f is usually in $1000s
    mgr_sql = """
        SELECT 
            m.firm_name as holder_name,
            m.cik as holder_id,
            'manager' as holder_type,
            h.market_value * 1000 as market_value,
            h.report_date,
            (CAST(h.market_value * 1000 AS NUMERIC) / NULLIF(m.aum_total, 0)) * 100 as weight_pct
        FROM sec_13f_holdings h
        JOIN sec_managers m ON h.cik = m.cik
        WHERE h.cusip = :cusip
        AND h.report_date >= CURRENT_DATE - INTERVAL '180 days'
        ORDER BY h.market_value DESC
        LIMIT 20
    """
    
    # 2. Search Funds (N-PORT)
    fund_sql = """
        SELECT 
            f.fund_name as holder_name,
            f.cik as holder_id,
            'fund' as holder_type,
            h.market_value,
            h.report_date,
            h.pct_of_nav as weight_pct
        FROM sec_nport_holdings h
        JOIN sec_registered_funds f ON h.cik = f.cik
        WHERE (h.cusip = :cusip OR h.isin = :isin)
        AND h.report_date >= CURRENT_DATE - INTERVAL '180 days'
        ORDER BY h.market_value DESC NULLS LAST
        LIMIT 20
    """

    holders = []
    asset_name = "Selected Asset"

    # Execute queries
    mgr_res = await db.execute(text(mgr_sql), {"cusip": cusip})
    for r in mgr_res:
        holders.append(HoldingHolder(
            holder_name=r.holder_name,
            holder_id=r.holder_id,
            holder_type="manager",
            weight_pct=float(r.weight_pct) if r.weight_pct else None,
            market_value=float(r.market_value) if r.market_value else None,
            report_date=r.report_date
        ))

    fund_res = await db.execute(text(fund_sql), {"cusip": cusip, "isin": isin})
    for r in fund_res:
        holders.append(HoldingHolder(
            holder_name=r.holder_name,
            holder_id=r.holder_id,
            holder_type="fund",
            weight_pct=float(r.weight_pct) if r.weight_pct else None,
            market_value=float(r.market_value) if r.market_value else None,
            report_date=r.report_date
        ))

    # Try to find a nice name for the asset from the results
    if holders:
        # Sort combined results by weight or value
        holders.sort(key=lambda x: x.market_value or 0, reverse=True)

    return ReverseLookupResponse(
        asset_name=asset_name,
        cusip=cusip,
        isin=isin,
        holders=holders[:40]
    )


# ── Category search helpers ─────────────────────────────────


async def _search_assets(db: AsyncSession, q: str) -> SearchCategoryGroup:
    """Search unified assets (Equities, Bonds, Funds) via mv_unified_assets."""
    pattern = f"%{q}%"
    
    # Query mv_unified_assets
    stmt = (
        select(
            mv_unified_assets,
            func.count().over().label("_total")
        )
        .where(
            or_(
                mv_unified_assets.c.name.ilike(pattern),
                mv_unified_assets.c.ticker.ilike(pattern),
                mv_unified_assets.c.isin.ilike(pattern),
            )
        )
        .order_by(mv_unified_assets.c.name.asc())
        .limit(MAX_PER_CATEGORY)
    )

    rows = (await db.execute(stmt)).all()
    total = rows[0]._total if rows else 0

    items: list[SearchResultItem] = []
    for r in rows:
        # Logic for href: 
        # - Funds go to /screener/{id}
        # - Others (Equities/Bonds) could go to /universe/{id} or similar.
        # For now, following existing pattern where search results often lead to screener/details.
        
        category_label = r.asset_class.replace("_", " ").title()
        subtitle_parts = [p for p in [r.ticker, category_label, r.geography] if p]
        
        # If it's a SEC fund/equity from cusip_ticker_map, it might not be in screener yet
        # But we use the ID (CUSIP or Instrument UUID)
        href = f"/screener/{r.id}"
        if r.source == "internal":
            href = f"/universe/{r.id}"

        items.append(
            SearchResultItem(
                id=r.id,
                title=r.name,
                subtitle=" · ".join(subtitle_parts) if subtitle_parts else None,
                category="funds", # Keep category as "funds" for UI grouping/icon consistency
                href=href,
            ),
        )

    return SearchCategoryGroup(category="funds", label="Assets", items=items, total=total)


async def _search_managers(
    db: AsyncSession, q: str, org_id: str,
) -> SearchCategoryGroup:
    """Search SEC managers (uses existing manager_screener SQL builder)."""
    filters = ScreenerFilters(text_search=q, page_size=MAX_PER_CATEGORY)
    data_stmt, count_stmt = build_screener_queries(filters, org_id=org_id)

    rows_raw, count_raw = await asyncio.gather(
        db.execute(data_stmt),
        db.execute(count_stmt),
    )
    rows = rows_raw.all()
    total = count_raw.scalar() or 0

    items: list[SearchResultItem] = []
    for r in rows:
        crd = r[0] or ""
        firm = r[1] or "Unknown Manager"
        aum = r[2]
        state = r[4] or ""

        subtitle_parts = [state] if state else []
        if aum and aum > 0:
            if aum >= 1_000_000_000:
                subtitle_parts.append(f"${aum / 1_000_000_000:.1f}B AUM")
            elif aum >= 1_000_000:
                subtitle_parts.append(f"${aum / 1_000_000:.0f}M AUM")

        items.append(
            SearchResultItem(
                id=crd,
                title=firm,
                subtitle=" · ".join(subtitle_parts) if subtitle_parts else None,
                category="managers",
                href=f"/screener/managers/{crd}",
            ),
        )

    return SearchCategoryGroup(category="managers", label="Managers", items=items, total=total)


async def _search_documents(db: AsyncSession, q: str) -> SearchCategoryGroup:
    """Search wealth documents by title/filename (ILIKE)."""
    q_pattern = f"%{q}%"
    where_clause = or_(
        WealthDocument.title.ilike(q_pattern),
        WealthDocument.filename.ilike(q_pattern),
    )

    count_stmt = (
        select(func.count())
        .select_from(WealthDocument)
        .where(where_clause)
    )
    data_stmt = (
        select(WealthDocument)
        .where(where_clause)
        .order_by(WealthDocument.updated_at.desc())
        .limit(MAX_PER_CATEGORY)
    )

    rows_raw, count_raw = await asyncio.gather(
        db.execute(data_stmt),
        db.execute(count_stmt),
    )
    docs = rows_raw.scalars().all()
    total = count_raw.scalar() or 0

    items: list[SearchResultItem] = []
    for doc in docs:
        subtitle_parts = []
        if doc.domain:
            subtitle_parts.append(doc.domain)
        if doc.root_folder and doc.root_folder != "documents":
            subtitle_parts.append(doc.root_folder)

        items.append(
            SearchResultItem(
                id=str(doc.id),
                title=doc.title,
                subtitle=" · ".join(subtitle_parts) if subtitle_parts else doc.filename,
                category="documents",
                href=f"/documents/{doc.id}",
            ),
        )

    return SearchCategoryGroup(category="documents", label="Documents", items=items, total=total)
