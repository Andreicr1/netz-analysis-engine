"""ESMA UCITS fund universe endpoints.

All tables are GLOBAL (no organization_id, no RLS).
Uses get_db_session (not get_db_with_rls).
Auth: Role.INVESTMENT_TEAM or Role.ADMIN.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.db.engine import async_session_factory
from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.domains.wealth.queries.esma_sql import (
    EsmaFundFilters,
    EsmaManagerFilters,
    build_fund_detail_query,
    build_fund_list_queries,
    build_manager_detail_query,
    build_manager_funds_query,
    build_manager_list_queries,
    build_sec_crossref_query,
)
from app.domains.wealth.schemas.esma import (
    EsmaFundDetail,
    EsmaFundItem,
    EsmaFundPage,
    EsmaManagerDetail,
    EsmaManagerItem,
    EsmaManagerPage,
    EsmaSecCrossRef,
)
from app.shared.enums import Role

router = APIRouter(prefix="/esma", tags=["esma"])


def _require_esma_role(actor: Actor) -> None:
    if not actor.has_role(Role.INVESTMENT_TEAM) and not actor.has_role(Role.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Investment team or admin role required",
        )


# ── 1. GET /esma/managers ────────────────────────────────────────


@router.get(
    "/managers",
    response_model=EsmaManagerPage,
    summary="List ESMA managers",
)
async def list_esma_managers(
    country: str | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> EsmaManagerPage:
    _require_esma_role(actor)

    filters = EsmaManagerFilters(
        country=country, search=search, page=page, page_size=page_size,
    )
    data_q, count_q = build_manager_list_queries(filters)

    async with async_session_factory() as db:
        data_result = await db.execute(data_q)
        count_result = await db.execute(count_q)

    rows = data_result.all()
    total = count_result.scalar() or 0

    items = [
        EsmaManagerItem(
            esma_id=r.esma_id,
            company_name=r.company_name,
            country=r.country,
            authorization_status=r.authorization_status,
            sec_crd_number=r.sec_crd_number,
            fund_count=int(r.fund_count) if r.fund_count else 0,
        )
        for r in rows
    ]
    return EsmaManagerPage(items=items, total=total, page=page, page_size=page_size)


# ── 2. GET /esma/managers/{esma_id} ─────────────────────────────


@router.get(
    "/managers/{esma_id}",
    response_model=EsmaManagerDetail,
    summary="Get ESMA manager detail with funds",
)
async def get_esma_manager(
    esma_id: str,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> EsmaManagerDetail:
    _require_esma_role(actor)

    mgr_q = build_manager_detail_query(esma_id)
    funds_q = build_manager_funds_query(esma_id)

    async with async_session_factory() as db:
        mgr_result = await db.execute(mgr_q)
        funds_result = await db.execute(funds_q)

    mgr = mgr_result.first()
    if mgr is None:
        raise HTTPException(status_code=404, detail="Manager not found")

    fund_rows = funds_result.all()
    funds = [
        EsmaFundItem(
            isin=f.isin,
            fund_name=f.fund_name,
            domicile=f.domicile,
            fund_type=f.fund_type,
            yahoo_ticker=f.yahoo_ticker,
            esma_manager_id=f.esma_manager_id,
        )
        for f in fund_rows
    ]
    return EsmaManagerDetail(
        esma_id=mgr.esma_id,
        company_name=mgr.company_name,
        country=mgr.country,
        authorization_status=mgr.authorization_status,
        sec_crd_number=mgr.sec_crd_number,
        funds=funds,
    )


# ── 3. GET /esma/funds ──────────────────────────────────────────


@router.get(
    "/funds",
    response_model=EsmaFundPage,
    summary="List ESMA UCITS funds",
)
async def list_esma_funds(
    domicile: str | None = Query(None),
    fund_type: str | None = Query(None, alias="type"),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> EsmaFundPage:
    _require_esma_role(actor)

    filters = EsmaFundFilters(
        domicile=domicile, fund_type=fund_type, search=search,
        page=page, page_size=page_size,
    )
    data_q, count_q = build_fund_list_queries(filters)

    async with async_session_factory() as db:
        data_result = await db.execute(data_q)
        count_result = await db.execute(count_q)

    rows = data_result.all()
    total = count_result.scalar() or 0

    items = [
        EsmaFundItem(
            isin=r.isin,
            fund_name=r.fund_name,
            domicile=r.domicile,
            fund_type=r.fund_type,
            yahoo_ticker=r.yahoo_ticker,
            esma_manager_id=r.esma_manager_id,
        )
        for r in rows
    ]
    return EsmaFundPage(items=items, total=total, page=page, page_size=page_size)


# ── 4. GET /esma/funds/{isin} ───────────────────────────────────


@router.get(
    "/funds/{isin}",
    response_model=EsmaFundDetail,
    summary="Get ESMA fund detail with manager",
)
async def get_esma_fund(
    isin: str,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> EsmaFundDetail:
    _require_esma_role(actor)

    q = build_fund_detail_query(isin)

    async with async_session_factory() as db:
        result = await db.execute(q)

    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Fund not found")

    manager = None
    if row.mgr_esma_id:
        manager = EsmaManagerItem(
            esma_id=row.mgr_esma_id,
            company_name=row.mgr_company_name or "",
            country=row.mgr_country,
            authorization_status=row.mgr_authorization_status,
            sec_crd_number=row.mgr_sec_crd_number,
            fund_count=int(row.mgr_fund_count) if row.mgr_fund_count else 0,
        )
    return EsmaFundDetail(
        isin=row.isin,
        fund_name=row.fund_name,
        domicile=row.domicile,
        fund_type=row.fund_type,
        yahoo_ticker=row.yahoo_ticker,
        manager=manager,
    )


# ── 5. GET /esma/managers/{esma_id}/sec-crossref ────────────────


@router.get(
    "/managers/{esma_id}/sec-crossref",
    response_model=EsmaSecCrossRef,
    summary="SEC cross-reference for ESMA manager",
)
async def get_esma_sec_crossref(
    esma_id: str,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> EsmaSecCrossRef:
    _require_esma_role(actor)

    q = build_sec_crossref_query(esma_id)

    async with async_session_factory() as db:
        result = await db.execute(q)

    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Manager not found")

    return EsmaSecCrossRef(
        esma_id=row.esma_id,
        sec_crd_number=row.sec_crd_number,
        sec_firm_name=row.sec_firm_name,
        matched=row.sec_firm_name is not None,
    )
