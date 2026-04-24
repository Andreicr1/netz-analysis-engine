"""Search routes for the wealth surface.

``GET /search`` is the low-latency command palette endpoint backed by
``mv_unified_funds`` and Redis.

``GET /search/global`` preserves the legacy grouped search used by the
wealth application shell.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import Column, MetaData, Table, Text, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.config_service import ConfigService
from app.core.jobs.tracker import get_redis_pool
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.models.document import WealthDocument
from app.domains.wealth.queries.catalog_sql import mv_unified_funds
from app.domains.wealth.queries.manager_screener_sql import (
    ScreenerFilters,
    build_screener_queries,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/search", tags=["search"])

VALID_CATEGORIES = {"funds", "managers", "documents"}
MAX_PER_CATEGORY = 6
DEFAULT_COMMAND_PALETTE_LIMIT = 8
MAX_COMMAND_PALETTE_LIMIT = 20
DEFAULT_CACHE_TTL_S = 600
MIN_CACHE_TTL_S = 300
MAX_CACHE_TTL_S = 900
_search_singleflight: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

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


class FundSearchResult(BaseModel):
    instrument_id: str = Field(..., description="Stable mv_unified_funds external_id")
    name: str = Field(..., description="Fund display name")
    ticker: str | None = Field(None, description="Ticker when available")
    strategy_label: str | None = Field(None, description="Normalized strategy classification")
    asset_class: str | None = Field(None, description="Fund type / asset class")


class SearchResponse(BaseModel):
    results: list[FundSearchResult]
    latency_ms: float = Field(..., description="Backend latency in milliseconds")
    cached: bool = Field(False, description="True when served from Redis")


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
    response_model=SearchResponse,
    summary="Command palette fund search",
)
async def command_palette_search(
    response: Response,
    q: str = Query(..., min_length=2, max_length=200),
    limit: int = Query(DEFAULT_COMMAND_PALETTE_LIMIT, ge=1, le=MAX_COMMAND_PALETTE_LIMIT),
    db: AsyncSession = Depends(get_db_with_rls),
    _user: CurrentUser = Depends(get_current_user),
) -> SearchResponse:
    """Low-latency fund search for the terminal command palette."""
    normalized_query = q.strip()
    config_service = ConfigService(db)
    ttl_s = await _resolve_palette_cache_ttl(config_service)
    cache_key = _palette_cache_key(normalized_query, limit)
    cache_control = f"private, max-age={ttl_s}, stale-while-revalidate=60"
    response.headers["Cache-Control"] = cache_control

    redis: aioredis.Redis | None = None
    try:
        redis = aioredis.Redis(connection_pool=get_redis_pool())
        cached = await redis.get(cache_key)
        if cached is not None:
            payload = SearchResponse.model_validate_json(
                cached.decode() if isinstance(cached, bytes) else str(cached),
            )
            payload.cached = True
            return payload
    except Exception as exc:  # noqa: BLE001 - fail open on Redis outage
        logger.warning("palette_search_cache_get_failed", key=cache_key, error=str(exc))
        redis = None

    try:
        started_at = time.perf_counter()
        lock = _search_singleflight[cache_key]
        async with lock:
            if redis is not None:
                try:
                    cached = await redis.get(cache_key)
                    if cached is not None:
                        payload = SearchResponse.model_validate_json(
                            cached.decode() if isinstance(cached, bytes) else str(cached),
                        )
                        payload.cached = True
                        return payload
                except Exception as exc:  # noqa: BLE001 - fail open on Redis outage
                    logger.warning("palette_search_cache_recheck_failed", key=cache_key, error=str(exc))

            payload = await _run_palette_search(db, normalized_query, limit, started_at=started_at)
            if redis is not None:
                try:
                    await redis.setex(
                        cache_key,
                        ttl_s,
                        payload.model_dump_json(),
                    )
                except Exception as exc:  # noqa: BLE001 - fail open on Redis outage
                    logger.warning("palette_search_cache_set_failed", key=cache_key, error=str(exc))
            return payload
    finally:
        if redis is not None:
            try:
                await redis.aclose()
            except Exception:  # noqa: BLE001 - best effort
                pass


@router.get(
    "/global",
    response_model=GlobalSearchResponse,
    summary="Legacy global search across funds, managers, and documents",
)
async def global_search(
    q: str = Query(..., min_length=2, max_length=200),
    categories: str = Query("funds,managers,documents", description="Comma-separated categories"),
    db: AsyncSession = Depends(get_db_with_rls),
    _user: CurrentUser = Depends(get_current_user),
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
        category_label = r.asset_class.replace("_", " ").title()
        subtitle_parts = [p for p in [r.ticker, category_label, r.geography] if p]

        # Funds → fact-sheet route; internal instruments → universe detail
        href = f"/screener/fund/{r.id}"
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


async def _resolve_palette_cache_ttl(config_service: ConfigService) -> int:
    """Read optional cache tuning from ConfigService, with safe bounds."""
    try:
        config = await config_service.get("wealth", "command_palette")
        raw_ttl = config.value.get("search_cache_ttl_seconds")
        if isinstance(raw_ttl, int):
            return max(MIN_CACHE_TTL_S, min(MAX_CACHE_TTL_S, raw_ttl))
    except Exception as exc:  # noqa: BLE001 - optional config, fail to default
        logger.warning("palette_search_config_fallback", error=str(exc))
    return DEFAULT_CACHE_TTL_S


def _palette_cache_key(q: str, limit: int) -> str:
    return f"search:palette:v1:{q.lower()}:{limit}"


async def _run_palette_search(
    db: AsyncSession,
    q: str,
    limit: int,
    *,
    started_at: float,
) -> SearchResponse:
    pattern = f"%{q}%"
    lower_q = q.lower()
    rank_expr = case(
        (func.lower(func.coalesce(mv_unified_funds.c.ticker, "")) == lower_q, 0),
        (func.lower(mv_unified_funds.c.name).like(f"{lower_q}%"), 1),
        (func.lower(func.coalesce(mv_unified_funds.c.ticker, "")).like(f"{lower_q}%"), 2),
        else_=3,
    )
    stmt = (
        select(
            mv_unified_funds.c.external_id,
            mv_unified_funds.c.name,
            mv_unified_funds.c.ticker,
            mv_unified_funds.c.strategy_label,
            mv_unified_funds.c.fund_type,
            rank_expr.label("_rank"),
        )
        .where(
            mv_unified_funds.c.is_institutional.is_(True),
            or_(
                mv_unified_funds.c.name.ilike(pattern),
                mv_unified_funds.c.ticker.ilike(pattern),
            ),
        )
        .order_by(
            rank_expr.asc(),
            mv_unified_funds.c.aum_usd.desc().nullslast(),
            mv_unified_funds.c.name.asc(),
        )
        .limit(limit)
    )

    rows = (await db.execute(stmt)).mappings().all()
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    return SearchResponse(
        results=[
            FundSearchResult(
                instrument_id=str(row["external_id"]),
                name=str(row["name"]),
                ticker=row["ticker"],
                strategy_label=row["strategy_label"],
                asset_class=row["fund_type"],
            )
            for row in rows
        ],
        latency_ms=elapsed_ms,
    )
