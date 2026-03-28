"""Unified global search — aggregator for funds, managers, and documents.

GET /search?q=&categories=funds,managers,documents

Fan-out to existing SQL queries (catalog, manager_screener, wealth_documents).
Returns grouped results by category with a small page_size for speed.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import route_cache
from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.models.document import WealthDocument
from app.domains.wealth.queries.catalog_sql import CatalogFilters, build_catalog_query
from app.domains.wealth.queries.manager_screener_sql import (
    ScreenerFilters,
    build_screener_queries,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/search", tags=["search"])

VALID_CATEGORIES = {"funds", "managers", "documents"}
MAX_PER_CATEGORY = 6


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


@router.get("", response_model=GlobalSearchResponse, summary="Unified global search")
@route_cache(ttl=30, key_prefix="global:search")
async def global_search(
    q: str = Query("", max_length=200),
    categories: str | None = Query(None, description="Comma-separated: funds,managers,documents"),
    db: AsyncSession = Depends(get_db_with_rls),
    org_id: uuid.UUID = Depends(get_org_id),
    actor: Actor = Depends(get_actor),
) -> GlobalSearchResponse:
    if not q or len(q.strip()) < 2:
        return GlobalSearchResponse(query=q, groups=[])

    q_stripped = q.strip()

    # Parse requested categories
    if categories:
        requested = {c.strip().lower() for c in categories.split(",")} & VALID_CATEGORIES
    else:
        requested = VALID_CATEGORIES

    # Fan-out concurrently
    tasks: dict[str, asyncio.Task[SearchCategoryGroup | None]] = {}
    if "funds" in requested:
        tasks["funds"] = asyncio.create_task(_search_funds(db, q_stripped))
    if "managers" in requested:
        tasks["managers"] = asyncio.create_task(
            _search_managers(db, q_stripped, str(org_id)),
        )
    if "documents" in requested:
        tasks["documents"] = asyncio.create_task(_search_documents(db, q_stripped))

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    groups: list[SearchCategoryGroup] = []
    for key, result in zip(tasks.keys(), results):
        if isinstance(result, Exception):
            logger.warning("global_search_category_error", category=key, error=str(result))
            continue
        if result and result.items:
            groups.append(result)

    return GlobalSearchResponse(query=q_stripped, groups=groups)


# ── Category search helpers ─────────────────────────────────


async def _search_funds(db: AsyncSession, q: str) -> SearchCategoryGroup:
    """Search fund catalog (uses existing catalog SQL builder)."""
    filters = CatalogFilters(q=q, page=1, page_size=MAX_PER_CATEGORY)
    stmt = build_catalog_query(filters)
    if stmt is None:
        return SearchCategoryGroup(category="funds", label="Funds", items=[], total=0)

    rows = (await db.execute(stmt)).all()
    total = rows[0]._total if rows else 0

    items: list[SearchResultItem] = []
    for r in rows:
        ext_id = getattr(r, "external_id", None) or ""
        universe = getattr(r, "universe", "") or ""
        name = getattr(r, "name", "") or "Unnamed Fund"
        ticker = getattr(r, "ticker", None) or ""
        manager = getattr(r, "manager_name", None) or ""

        subtitle_parts = [p for p in [ticker, universe, manager] if p]
        items.append(
            SearchResultItem(
                id=str(ext_id),
                title=name,
                subtitle=" · ".join(subtitle_parts) if subtitle_parts else None,
                category="funds",
                href=f"/screener/{ext_id}",
            ),
        )

    return SearchCategoryGroup(category="funds", label="Funds", items=items, total=total)


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
        # Row columns: crd_number, firm_name, aum_total, registration_status, state, ...
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
