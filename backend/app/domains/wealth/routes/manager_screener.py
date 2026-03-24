"""Manager Screener API routes — SEC manager discovery and comparison.

GET  /manager-screener                        — paginated screener list
GET  /manager-screener/managers/{crd}/profile  — ADV profile + funds + team
GET  /manager-screener/managers/{crd}/holdings — sector allocation, top 10, HHI
GET  /manager-screener/managers/{crd}/drift    — turnover timeline
GET  /manager-screener/managers/{crd}/institutional — 13F reverse lookup
GET  /manager-screener/managers/{crd}/universe-status — instrument universe status
POST /manager-screener/managers/{crd}/add-to-universe — add manager to universe
POST /manager-screener/managers/compare        — compare 2-5 managers
"""

from __future__ import annotations

import asyncio
import math
import re
import uuid
from datetime import date

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.cache import route_cache
from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.queries.manager_screener_sql import (
    ScreenerFilters,
    build_screener_queries,
)
from app.domains.wealth.schemas.manager_screener import (
    BrochureSearchHit,
    BrochureSearchResponse,
    BrochureSectionItem,
    BrochureSectionsResponse,
    DriftQuarter,
    HoldingRow,
    InstitutionalHolder,
    ManagerCompareRequest,
    ManagerCompareResult,
    ManagerDriftRead,
    ManagerFundRead,
    ManagerHoldingsRead,
    ManagerInstitutionalRead,
    ManagerProfileRead,
    ManagerRow,
    ManagerScreenerPage,
    ManagerTeamMemberRead,
    ManagerToUniverseRequest,
    ManagerUniverseRead,
    NportHoldingItem,
    NportHoldingsResponse,
)
from app.shared.enums import Role
from app.shared.models import (
    Sec13fDiff,
    Sec13fHolding,
    SecInstitutionalAllocation,
    SecManager,
    SecNportHolding,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/manager-screener", tags=["manager-screener"])

_CRD_RE = re.compile(r"^[A-Za-z0-9]+$")


def _require_investment_role(actor: Actor) -> None:
    if not actor.has_role(Role.INVESTMENT_TEAM) and not actor.has_role(Role.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Investment Team or Admin role required",
        )


def _validate_crd(crd: str) -> str:
    if not _CRD_RE.match(crd):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid CRD number",
        )
    return crd


async def _get_manager(db: AsyncSession, crd: str) -> SecManager:
    """Fetch a manager by CRD or raise 404."""
    stmt = select(SecManager).where(SecManager.crd_number == crd)
    result = await db.execute(stmt)
    manager = result.scalar_one_or_none()
    if not manager:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Manager {crd} not found",
        )
    return manager


# ═══════════════════════════════════════════════════════════════════════════
#  GET / — Paginated screener list
# ═══════════════════════════════════════════════════════════════════════════


def _require_investment_role_dep(actor: Actor = Depends(get_actor)) -> None:
    _require_investment_role(actor)


@router.get(
    "/",
    response_model=ManagerScreenerPage,
    summary="Paginated manager screener",
    dependencies=[Depends(_require_investment_role_dep)],
)
@route_cache(ttl=300, global_key=True, key_prefix="mgr:list")
async def list_managers(
    # Block 1 — Firma
    aum_min: int | None = Query(None),
    aum_max: int | None = Query(None),
    states: list[str] | None = Query(None),
    countries: list[str] | None = Query(None),
    registration_status: str | None = Query(None),
    compliance_clean: bool | None = Query(None),
    adv_filed_after: date | None = Query(None),
    adv_filed_before: date | None = Query(None),
    text_search: str | None = Query(None, max_length=200),
    fee_types: list[str] | None = Query(None),
    # Block 2 — Portfolio
    sectors: list[str] | None = Query(None),
    hhi_min: float | None = Query(None),
    hhi_max: float | None = Query(None),
    position_count_min: int | None = Query(None),
    position_count_max: int | None = Query(None),
    portfolio_value_min: int | None = Query(None),
    # Block 3 — Drift
    style_drift_detected: bool | None = Query(None),
    turnover_min: float | None = Query(None),
    turnover_max: float | None = Query(None),
    high_activity_quarters_min: int | None = Query(None),
    # Block 4 — Institutional
    has_institutional_holders: bool | None = Query(None),
    holder_types: list[str] | None = Query(None),
    # Block 5 — Universe
    universe_statuses: list[str] | None = Query(None),
    # Sort & pagination
    sort_by: str = Query("aum_total"),
    sort_dir: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    # Dependencies
    db: AsyncSession = Depends(get_db_with_rls),
    org_id: uuid.UUID = Depends(get_org_id),
    actor: Actor = Depends(get_actor),
) -> ManagerScreenerPage:
    filters = ScreenerFilters(
        aum_min=aum_min,
        aum_max=aum_max,
        states=states or [],
        countries=countries or [],
        registration_status=registration_status,
        compliance_clean=compliance_clean,
        adv_filed_after=adv_filed_after,
        adv_filed_before=adv_filed_before,
        text_search=text_search,
        fee_types=fee_types or [],
        sectors=sectors or [],
        hhi_min=hhi_min,
        hhi_max=hhi_max,
        position_count_min=position_count_min,
        position_count_max=position_count_max,
        portfolio_value_min=portfolio_value_min,
        style_drift_detected=style_drift_detected,
        turnover_min=turnover_min,
        turnover_max=turnover_max,
        high_activity_quarters_min=high_activity_quarters_min,
        has_institutional_holders=has_institutional_holders,
        holder_types=holder_types or [],
        universe_statuses=universe_statuses or [],
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        page_size=page_size,
    )

    data_query, count_query = build_screener_queries(filters, str(org_id))

    data_result = await db.execute(data_query)
    count_result = await db.execute(count_query)

    rows = data_result.mappings().all()
    total_count = count_result.scalar_one()

    managers = [
        ManagerRow(
            crd_number=r["crd_number"],
            firm_name=r["firm_name"],
            aum_total=r["aum_total"],
            registration_status=r["registration_status"],
            state=r["state"],
            country=r["country"],
            compliance_disclosures=r["compliance_disclosures"],
            position_count=r["position_count"],
            drift_churn=r["drift_churn"],
            universe_status=r["universe_status"],
        )
        for r in rows
    ]

    return ManagerScreenerPage(
        managers=managers,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=(page * page_size) < total_count,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  GET /managers/{crd}/profile
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/managers/{crd}/profile",
    response_model=ManagerProfileRead,
    summary="Manager ADV profile",
)
async def get_profile(
    crd: str = Path(...),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> ManagerProfileRead:
    _require_investment_role(actor)
    crd = _validate_crd(crd)

    stmt = (
        select(SecManager)
        .options(selectinload(SecManager.funds), selectinload(SecManager.team))
        .where(SecManager.crd_number == crd)
    )
    result = await db.execute(stmt)
    manager = result.scalar_one_or_none()
    if not manager:
        raise HTTPException(status_code=404, detail=f"Manager {crd} not found")

    return ManagerProfileRead(
        crd_number=manager.crd_number,
        cik=manager.cik,
        firm_name=manager.firm_name,
        sec_number=manager.sec_number,
        registration_status=manager.registration_status,
        aum_total=manager.aum_total,
        aum_discretionary=manager.aum_discretionary,
        aum_non_discretionary=manager.aum_non_discretionary,
        total_accounts=manager.total_accounts,
        fee_types=manager.fee_types,
        client_types=manager.client_types,
        state=manager.state,
        country=manager.country,
        website=manager.website,
        compliance_disclosures=manager.compliance_disclosures,
        last_adv_filed_at=manager.last_adv_filed_at,
        funds=[ManagerFundRead.model_validate(f) for f in manager.funds],
        team=[ManagerTeamMemberRead.model_validate(t) for t in manager.team],
    )


# ═══════════════════════════════════════════════════════════════════════════
#  GET /managers/{crd}/holdings
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/managers/{crd}/holdings",
    response_model=ManagerHoldingsRead,
    summary="Manager holdings — sector allocation, top 10, HHI",
)
async def get_holdings(
    crd: str = Path(...),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> ManagerHoldingsRead:
    _require_investment_role(actor)
    crd = _validate_crd(crd)

    manager = await _get_manager(db, crd)
    if not manager.cik:
        return ManagerHoldingsRead()

    today = date.today()

    # Latest quarter holdings — always filter report_date for chunk pruning
    latest_q_stmt = (
        select(func.max(Sec13fHolding.report_date))
        .where(Sec13fHolding.cik == manager.cik)
        .where(Sec13fHolding.report_date <= today)
    )
    latest_q_result = await db.execute(latest_q_stmt)
    latest_quarter = latest_q_result.scalar_one_or_none()

    if not latest_quarter:
        return ManagerHoldingsRead()

    # Get all holdings for that quarter
    holdings_stmt = (
        select(Sec13fHolding)
        .where(Sec13fHolding.cik == manager.cik)
        .where(Sec13fHolding.report_date == latest_quarter)
        .order_by(Sec13fHolding.market_value.desc().nulls_last())
    )
    holdings_result = await db.execute(holdings_stmt)
    holdings = holdings_result.scalars().all()

    # Sector allocation
    total_value = sum(h.market_value or 0 for h in holdings)
    sector_values: dict[str, int] = {}
    for h in holdings:
        sector = h.sector or "Unknown"
        sector_values[sector] = sector_values.get(sector, 0) + (h.market_value or 0)

    sector_allocation = {
        s: v / total_value if total_value > 0 else 0.0
        for s, v in sorted(sector_values.items(), key=lambda x: -x[1])
    }

    # HHI
    weights = list(sector_allocation.values())
    hhi = sum(w * w for w in weights) if weights else None

    # Top 10
    top_holdings = [
        HoldingRow(
            cusip=h.cusip,
            issuer_name=h.issuer_name,
            sector=h.sector,
            market_value=h.market_value,
            weight=(h.market_value or 0) / total_value if total_value > 0 else None,
        )
        for h in holdings[:10]
    ]

    # 4-quarter history (sector aggregation per quarter)
    cutoff = date(today.year - 1, today.month, today.day)
    history_stmt = (
        select(
            Sec13fHolding.report_date,
            Sec13fHolding.sector,
            func.sum(Sec13fHolding.market_value).label("value"),
        )
        .where(Sec13fHolding.cik == manager.cik)
        .where(Sec13fHolding.report_date >= cutoff)
        .where(Sec13fHolding.report_date <= today)
        .group_by(Sec13fHolding.report_date, Sec13fHolding.sector)
        .order_by(Sec13fHolding.report_date)
    )
    history_result = await db.execute(history_stmt)
    history_rows = history_result.mappings().all()

    # Group by quarter
    history: list[dict] = []
    quarters_seen: dict[date, dict] = {}
    for row in history_rows:
        q = row["report_date"]
        if q not in quarters_seen:
            entry: dict = {"quarter": q.isoformat(), "sectors": {}}
            quarters_seen[q] = entry
            history.append(entry)
        quarters_seen[q]["sectors"][row["sector"] or "Unknown"] = int(row["value"] or 0)

    return ManagerHoldingsRead(
        sector_allocation=sector_allocation,
        top_holdings=top_holdings,
        hhi=hhi,
        history=history,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  GET /managers/{crd}/drift
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/managers/{crd}/drift",
    response_model=ManagerDriftRead,
    summary="Manager drift — turnover timeline",
)
async def get_drift(
    crd: str = Path(...),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> ManagerDriftRead:
    _require_investment_role(actor)
    crd = _validate_crd(crd)

    manager = await _get_manager(db, crd)
    if not manager.cik:
        return ManagerDriftRead()

    today = date.today()
    cutoff = date(today.year - 2, today.month, today.day)

    # Quarter-by-quarter diff stats — always filter quarter_to for chunk pruning
    stmt = (
        select(
            Sec13fDiff.quarter_to,
            Sec13fDiff.action,
            func.count().label("cnt"),
        )
        .where(Sec13fDiff.cik == manager.cik)
        .where(Sec13fDiff.quarter_to >= cutoff)
        .where(Sec13fDiff.quarter_to <= today)
        .group_by(Sec13fDiff.quarter_to, Sec13fDiff.action)
        .order_by(Sec13fDiff.quarter_to)
    )
    result = await db.execute(stmt)
    rows = result.mappings().all()

    # Aggregate by quarter
    quarter_data: dict[date, dict[str, int]] = {}
    for row in rows:
        q = row["quarter_to"]
        if q not in quarter_data:
            quarter_data[q] = {
                "NEW_POSITION": 0,
                "EXITED": 0,
                "INCREASED": 0,
                "DECREASED": 0,
                "UNCHANGED": 0,
            }
        quarter_data[q][row["action"]] = int(row["cnt"])

    quarters: list[DriftQuarter] = []
    style_drift_detected = False

    for q, actions in sorted(quarter_data.items()):
        total = sum(actions.values())
        churn = actions["NEW_POSITION"] + actions["EXITED"]
        turnover = churn / total if total > 0 else 0.0

        if turnover > 0.3:
            style_drift_detected = True

        quarters.append(
            DriftQuarter(
                quarter=q,
                turnover=turnover,
                new_positions=actions["NEW_POSITION"],
                exited_positions=actions["EXITED"],
                increased=actions["INCREASED"],
                decreased=actions["DECREASED"],
                unchanged=actions["UNCHANGED"],
                total_changes=total,
            )
        )

    return ManagerDriftRead(
        quarters=quarters,
        style_drift_detected=style_drift_detected,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  GET /managers/{crd}/institutional
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/managers/{crd}/institutional",
    response_model=ManagerInstitutionalRead,
    summary="Institutional holders — 13F reverse lookup",
)
async def get_institutional(
    crd: str = Path(...),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> ManagerInstitutionalRead:
    _require_investment_role(actor)
    crd = _validate_crd(crd)

    manager = await _get_manager(db, crd)
    if not manager.cik:
        return ManagerInstitutionalRead()

    today = date.today()
    cutoff = date(today.year - 1, today.month, today.day)

    # Find institutions that hold positions matching this manager's CIK
    # via the institutional allocations table — always filter report_date
    stmt = (
        select(
            SecInstitutionalAllocation.filer_name,
            SecInstitutionalAllocation.filer_type,
            SecInstitutionalAllocation.filer_cik,
            func.sum(SecInstitutionalAllocation.market_value).label("total_value"),
        )
        .where(SecInstitutionalAllocation.target_cusip.in_(
            select(Sec13fHolding.cusip)
            .where(Sec13fHolding.cik == manager.cik)
            .where(Sec13fHolding.report_date >= cutoff)
            .where(Sec13fHolding.report_date <= today)
            .distinct()
        ))
        .where(SecInstitutionalAllocation.report_date >= cutoff)
        .where(SecInstitutionalAllocation.report_date <= today)
        .group_by(
            SecInstitutionalAllocation.filer_name,
            SecInstitutionalAllocation.filer_type,
            SecInstitutionalAllocation.filer_cik,
        )
        .order_by(func.sum(SecInstitutionalAllocation.market_value).desc().nulls_last())
        .limit(50)
    )
    result = await db.execute(stmt)
    rows = result.mappings().all()

    holders = [
        InstitutionalHolder(
            filer_name=r["filer_name"],
            filer_type=r["filer_type"],
            filer_cik=r["filer_cik"],
            market_value=int(r["total_value"]) if r["total_value"] else None,
        )
        for r in rows
    ]

    # Coverage type
    if not holders:
        coverage_type = "none"
    elif len(holders) >= 10:
        coverage_type = "full"
    else:
        coverage_type = "partial"

    return ManagerInstitutionalRead(
        coverage_type=coverage_type,
        holders=holders,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  GET /managers/{crd}/universe-status
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/managers/{crd}/universe-status",
    response_model=ManagerUniverseRead,
    summary="Manager universe status",
)
async def get_universe_status(
    crd: str = Path(...),
    db: AsyncSession = Depends(get_db_with_rls),
    org_id: uuid.UUID = Depends(get_org_id),
    actor: Actor = Depends(get_actor),
) -> ManagerUniverseRead:
    _require_investment_role(actor)
    crd = _validate_crd(crd)

    stmt = (
        select(Instrument)
        .where(Instrument.attributes["source"].astext == "sec_manager")
        .where(Instrument.attributes["sec_crd_number"].astext == crd)
    )
    result = await db.execute(stmt)
    instrument = result.scalar_one_or_none()

    if not instrument:
        return ManagerUniverseRead()

    return ManagerUniverseRead(
        instrument_id=instrument.instrument_id,
        approval_status=instrument.approval_status,
        asset_class=instrument.asset_class,
        geography=instrument.geography,
        currency=instrument.currency,
        block_id=instrument.block_id,
        added_at=instrument.created_at,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  GET /managers/{crd}/nport — N-PORT mutual fund holdings
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/managers/{crd}/nport",
    response_model=NportHoldingsResponse,
    summary="N-PORT mutual fund holdings for a manager",
)
async def get_manager_nport_holdings(
    crd: str = Path(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    report_date: date | None = Query(None),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> NportHoldingsResponse:
    """Return paginated N-PORT holdings for a manager (resolved CRD→CIK)."""
    _require_investment_role(actor)
    crd = _validate_crd(crd)

    manager = await _get_manager(db, crd)
    if not manager.cik:
        return NportHoldingsResponse(
            crd_number=crd, total_holdings=0, holdings=[],
            page=page, page_size=page_size, total_pages=0,
        )

    today = date.today()

    # Resolve report_date: use latest if not specified
    if report_date is None:
        latest_stmt = (
            select(func.max(SecNportHolding.report_date))
            .where(SecNportHolding.cik == manager.cik)
            .where(SecNportHolding.report_date <= today)
        )
        result = await db.execute(latest_stmt)
        report_date = result.scalar_one_or_none()

    if report_date is None:
        return NportHoldingsResponse(
            crd_number=crd, total_holdings=0, holdings=[],
            page=page, page_size=page_size, total_pages=0,
        )

    # Count total
    count_stmt = (
        select(func.count())
        .select_from(SecNportHolding)
        .where(SecNportHolding.cik == manager.cik)
        .where(SecNportHolding.report_date == report_date)
    )

    # Paginated data
    offset = (page - 1) * page_size
    data_stmt = (
        select(SecNportHolding)
        .where(SecNportHolding.cik == manager.cik)
        .where(SecNportHolding.report_date == report_date)
        .order_by(SecNportHolding.market_value.desc().nulls_last())
        .limit(page_size)
        .offset(offset)
    )

    count_result, data_result = await asyncio.gather(
        db.execute(count_stmt),
        db.execute(data_stmt),
    )

    total = count_result.scalar_one()
    rows = data_result.scalars().all()

    holdings = [
        NportHoldingItem(
            cusip=h.cusip,
            isin=h.isin,
            issuer_name=h.issuer_name or "Unknown",
            asset_class=h.asset_class,
            sector=h.sector,
            market_value=float(h.market_value) if h.market_value else None,
            quantity=float(h.quantity) if h.quantity else None,
            currency=h.currency,
            pct_of_nav=float(h.pct_of_nav) if h.pct_of_nav else None,
            report_date=h.report_date,
        )
        for h in rows
    ]

    return NportHoldingsResponse(
        crd_number=crd,
        report_date=report_date,
        total_holdings=total,
        holdings=holdings,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total > 0 else 0,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  GET /managers/{crd}/brochure/sections — ADV brochure sections listing
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/managers/{crd}/brochure/sections",
    response_model=BrochureSectionsResponse,
    summary="List ADV brochure sections for a manager",
)
async def get_brochure_sections(
    crd: str = Path(...),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> BrochureSectionsResponse:
    _require_investment_role(actor)
    crd = _validate_crd(crd)
    await _get_manager(db, crd)  # 404 if not found

    result = await db.execute(
        text(
            "SELECT crd_number, section, LEFT(content, 200) AS content_excerpt, filing_date "
            "FROM sec_manager_brochure_text "
            "WHERE crd_number = :crd "
            "ORDER BY filing_date DESC, section"
        ),
        {"crd": crd},
    )
    rows = result.mappings().all()

    return BrochureSectionsResponse(
        crd_number=crd,
        sections=[
            BrochureSectionItem(
                section=r["section"],
                content_excerpt=r["content_excerpt"],
                filing_date=r["filing_date"],
            )
            for r in rows
        ],
        total_sections=len(rows),
    )


# ═══════════════════════════════════════════════════════════════════════════
#  GET /managers/{crd}/brochure — full-text search in ADV brochure
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/managers/{crd}/brochure",
    response_model=BrochureSearchResponse,
    summary="Full-text search within manager's ADV brochure",
)
async def search_brochure(
    crd: str = Path(...),
    q: str = Query(..., min_length=2, max_length=200),
    section: str | None = Query(None),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> BrochureSearchResponse:
    _require_investment_role(actor)
    crd = _validate_crd(crd)
    await _get_manager(db, crd)  # 404 if not found

    sql = (
        "SELECT section, filing_date, "
        "  ts_headline('english', content, plainto_tsquery('english', :query), "
        "    'MaxFragments=2,MaxWords=30') AS headline, "
        "  ts_rank(to_tsvector('english', content), plainto_tsquery('english', :query)) AS rank "
        "FROM sec_manager_brochure_text "
        "WHERE crd_number = :crd "
        "  AND to_tsvector('english', content) @@ plainto_tsquery('english', :query)"
    )
    params: dict = {"crd": crd, "query": q}

    if section:
        sql += " AND section = :section"
        params["section"] = section

    sql += " ORDER BY rank DESC"

    result = await db.execute(text(sql), params)
    rows = result.mappings().all()

    return BrochureSearchResponse(
        crd_number=crd,
        query=q,
        results=[
            BrochureSearchHit(
                section=r["section"],
                headline=r["headline"],
                filing_date=r["filing_date"],
                rank=float(r["rank"]),
            )
            for r in rows
        ],
        total_results=len(rows),
    )


# ═══════════════════════════════════════════════════════════════════════════
#  POST /managers/{crd}/add-to-universe
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/managers/{crd}/add-to-universe",
    response_model=ManagerUniverseRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add manager to instrument universe",
)
async def add_to_universe(
    body: ManagerToUniverseRequest,
    crd: str = Path(...),
    db: AsyncSession = Depends(get_db_with_rls),
    org_id: uuid.UUID = Depends(get_org_id),
    actor: Actor = Depends(get_actor),
) -> ManagerUniverseRead:
    _require_investment_role(actor)
    crd = _validate_crd(crd)

    # Check if already in universe
    existing_stmt = (
        select(Instrument)
        .where(Instrument.attributes["source"].astext == "sec_manager")
        .where(Instrument.attributes["sec_crd_number"].astext == crd)
    )
    existing_result = await db.execute(existing_stmt)
    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Manager {crd} already in universe",
        )

    # Fetch manager to get name and CIK
    manager = await _get_manager(db, crd)

    instrument = Instrument(
        instrument_type="fund",
        name=manager.firm_name,
        asset_class=body.asset_class,
        geography=body.geography,
        currency=body.currency,
        block_id=body.block_id,
        approval_status="pending",
        attributes={
            "source": "sec_manager",
            "sec_crd_number": crd,
            "sec_cik": manager.cik,
        },
    )
    db.add(instrument)
    await db.commit()
    await db.refresh(instrument)

    return ManagerUniverseRead(
        instrument_id=instrument.instrument_id,
        approval_status=instrument.approval_status,
        asset_class=instrument.asset_class,
        geography=instrument.geography,
        currency=instrument.currency,
        block_id=instrument.block_id,
        added_at=instrument.created_at,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  POST /managers/compare
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/managers/compare",
    response_model=ManagerCompareResult,
    summary="Compare 2-5 managers",
)
async def compare_managers(
    body: ManagerCompareRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> ManagerCompareResult:
    _require_investment_role(actor)

    # Validate all CRDs
    for crd in body.crd_numbers:
        _validate_crd(crd)

    # Fetch all managers with funds + team
    stmt = (
        select(SecManager)
        .options(selectinload(SecManager.funds), selectinload(SecManager.team))
        .where(SecManager.crd_number.in_(body.crd_numbers))
    )
    result = await db.execute(stmt)
    managers = result.scalars().all()

    if len(managers) < 2:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="At least 2 valid managers required for comparison",
        )

    # Build profiles
    profiles = [
        ManagerProfileRead(
            crd_number=m.crd_number,
            cik=m.cik,
            firm_name=m.firm_name,
            sec_number=m.sec_number,
            registration_status=m.registration_status,
            aum_total=m.aum_total,
            aum_discretionary=m.aum_discretionary,
            aum_non_discretionary=m.aum_non_discretionary,
            total_accounts=m.total_accounts,
            fee_types=m.fee_types,
            client_types=m.client_types,
            state=m.state,
            country=m.country,
            website=m.website,
            compliance_disclosures=m.compliance_disclosures,
            last_adv_filed_at=m.last_adv_filed_at,
            funds=[ManagerFundRead.model_validate(f) for f in m.funds],
            team=[ManagerTeamMemberRead.model_validate(t) for t in m.team],
        )
        for m in managers
    ]

    today = date.today()

    # Sector allocations per manager (from latest quarter)
    sector_allocations: dict[str, dict[str, float]] = {}
    cusip_sets: dict[str, set[str]] = {}

    for m in managers:
        if not m.cik:
            sector_allocations[m.crd_number] = {}
            cusip_sets[m.crd_number] = set()
            continue

        # Get latest quarter holdings — always filter report_date
        latest_q_stmt = (
            select(func.max(Sec13fHolding.report_date))
            .where(Sec13fHolding.cik == m.cik)
            .where(Sec13fHolding.report_date <= today)
        )
        lq_result = await db.execute(latest_q_stmt)
        lq = lq_result.scalar_one_or_none()

        if not lq:
            sector_allocations[m.crd_number] = {}
            cusip_sets[m.crd_number] = set()
            continue

        holdings_stmt = (
            select(Sec13fHolding)
            .where(Sec13fHolding.cik == m.cik)
            .where(Sec13fHolding.report_date == lq)
        )
        h_result = await db.execute(holdings_stmt)
        holdings = h_result.scalars().all()

        total_val = sum(h.market_value or 0 for h in holdings)
        sectors: dict[str, int] = {}
        cusips: set[str] = set()
        for h in holdings:
            s = h.sector or "Unknown"
            sectors[s] = sectors.get(s, 0) + (h.market_value or 0)
            cusips.add(h.cusip)

        sector_allocations[m.crd_number] = {
            s: v / total_val if total_val > 0 else 0.0
            for s, v in sorted(sectors.items(), key=lambda x: -x[1])
        }
        cusip_sets[m.crd_number] = cusips

    # Jaccard overlap (pairwise average)
    all_sets = list(cusip_sets.values())
    if len(all_sets) >= 2 and all(s for s in all_sets):
        overlaps = []
        for i in range(len(all_sets)):
            for j in range(i + 1, len(all_sets)):
                union = all_sets[i] | all_sets[j]
                intersection = all_sets[i] & all_sets[j]
                if union:
                    overlaps.append(len(intersection) / len(union))
        jaccard = sum(overlaps) / len(overlaps) if overlaps else None
    else:
        jaccard = None

    # Drift comparison
    drift_comparison: list[dict] = []
    cutoff = date(today.year - 2, today.month, today.day)
    for m in managers:
        if not m.cik:
            drift_comparison.append({"crd_number": m.crd_number, "quarters": []})
            continue

        drift_stmt = (
            select(
                Sec13fDiff.quarter_to,
                func.count().label("total"),
                func.count().filter(
                    Sec13fDiff.action.in_(["NEW_POSITION", "EXITED"])
                ).label("churn"),
            )
            .where(Sec13fDiff.cik == m.cik)
            .where(Sec13fDiff.quarter_to >= cutoff)
            .where(Sec13fDiff.quarter_to <= today)
            .group_by(Sec13fDiff.quarter_to)
            .order_by(Sec13fDiff.quarter_to)
        )
        d_result = await db.execute(drift_stmt)
        d_rows = d_result.mappings().all()

        drift_comparison.append({
            "crd_number": m.crd_number,
            "quarters": [
                {
                    "quarter": r["quarter_to"].isoformat(),
                    "turnover": int(r["churn"]) / int(r["total"]) if int(r["total"]) > 0 else 0.0,
                    "total_changes": int(r["total"]),
                }
                for r in d_rows
            ],
        })

    return ManagerCompareResult(
        managers=profiles,
        sector_allocations=sector_allocations,
        jaccard_overlap=jaccard,
        drift_comparison=drift_comparison,
    )
