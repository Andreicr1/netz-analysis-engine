"""Screener API routes — trigger and query instrument screening.

POST /screener/run      — trigger on-demand screening
GET  /screener/runs     — list screening runs
GET  /screener/runs/{id}— run detail with results
GET  /screener/results  — latest results with filters
GET  /screener/results/{instrument_id} — screening history
GET  /screener/search   — global instrument search (server-side)
GET  /screener/facets   — facet counts for filter sidebar
POST /screener/import-esma/{isin} — import ESMA fund to universe
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Float, String, literal, select, union_all
from sqlalchemy import func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.config_service import ConfigService
from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.screening_result import ScreeningResult, ScreeningRun
from app.domains.wealth.schemas.instrument_search import (
    EsmaImportRequest,
    FacetItem,
    InstrumentSearchItem,
    InstrumentSearchPage,
    ScreenerFacets,
)
from app.domains.wealth.schemas.screening import (
    ScreeningResultRead,
    ScreeningRunRead,
    ScreeningRunRequest,
    ScreeningRunResponse,
)
from app.shared.enums import Role
from app.shared.models import EsmaFund, EsmaIsinTickerMap, EsmaManager

logger = structlog.get_logger()

router = APIRouter(prefix="/screener", tags=["screener"])


def _require_investment_role(actor: Actor) -> None:
    if not actor.has_role(Role.INVESTMENT_TEAM) and not actor.has_role(Role.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Investment Team or Admin role required",
        )


@router.post(
    "/run",
    response_model=ScreeningRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger on-demand screening",
)
async def trigger_screening(
    body: ScreeningRunRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    org_id: uuid.UUID = Depends(get_org_id),
    actor: Actor = Depends(get_actor),
) -> ScreeningRunResponse:
    _require_investment_role(actor)

    # Load instruments to screen
    stmt = select(Instrument).where(Instrument.is_active.is_(True))
    if body.instrument_type:
        stmt = stmt.where(Instrument.instrument_type == body.instrument_type)
    if body.block_id:
        stmt = stmt.where(Instrument.block_id == body.block_id)
    if body.instrument_ids:
        stmt = stmt.where(Instrument.instrument_id.in_(body.instrument_ids))

    result = await db.execute(stmt)
    instruments = result.scalars().all()

    if not instruments:
        raise HTTPException(status_code=404, detail="No instruments found matching criteria")

    # Load screening config
    config_svc = ConfigService(db)
    config_l1 = (await config_svc.get("liquid_funds", "screening_layer1", org_id)).value
    config_l2 = (await config_svc.get("liquid_funds", "screening_layer2", org_id)).value
    config_l3 = (await config_svc.get("liquid_funds", "screening_layer3", org_id)).value

    config_hash = hashlib.sha256(
        json.dumps({"l1": config_l1, "l2": config_l2, "l3": config_l3}, sort_keys=True).encode()
    ).hexdigest()

    # Create screening run
    run = ScreeningRun(
        organization_id=org_id,
        run_type="on_demand",
        instrument_count=len(instruments),
        config_hash=config_hash,
    )
    db.add(run)
    await db.flush()

    # Extract instrument data for screening (cross async boundary safely)
    instrument_dicts = [
        {
            "instrument_id": i.instrument_id,
            "instrument_type": i.instrument_type,
            "attributes": dict(i.attributes) if i.attributes else {},
            "block_id": i.block_id,
        }
        for i in instruments
    ]

    # Run screening in thread (pure CPU logic)
    from vertical_engines.wealth.screener.service import ScreenerService

    screener = ScreenerService(config_l1, config_l2, config_l3)
    screening_results = await asyncio.to_thread(
        lambda: [
            screener.screen_instrument(**inst_dict)
            for inst_dict in instrument_dicts
        ]
    )

    # Mark previous results as not current
    for inst_dict in instrument_dicts:
        await db.execute(
            select(ScreeningResult)
            .where(
                ScreeningResult.instrument_id == inst_dict["instrument_id"],
                ScreeningResult.is_current.is_(True),
            )
            .with_for_update()
        )

    # Persist results
    for sr in screening_results:
        screening_result = ScreeningResult(
            organization_id=org_id,
            instrument_id=sr.instrument_id,
            run_id=run.run_id,
            overall_status=sr.overall_status,
            score=sr.score,
            failed_at_layer=sr.failed_at_layer,
            layer_results=sr.layer_results_dict,
            required_analysis_type=sr.required_analysis_type,
            is_current=True,
        )
        db.add(screening_result)

    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    await db.commit()

    return ScreeningRunResponse(
        run_id=run.run_id,
        status="completed",
        instrument_count=len(instruments),
    )


@router.get(
    "/runs",
    response_model=list[ScreeningRunRead],
    summary="List screening runs",
)
async def list_runs(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[ScreeningRunRead]:
    result = await db.execute(
        select(ScreeningRun)
        .order_by(ScreeningRun.started_at.desc())
        .limit(limit)
    )
    runs = result.scalars().all()
    return [ScreeningRunRead.model_validate(r) for r in runs]


@router.get(
    "/runs/{run_id}",
    response_model=ScreeningRunRead,
    summary="Get screening run detail",
)
async def get_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> ScreeningRunRead:
    result = await db.execute(
        select(ScreeningRun).where(ScreeningRun.run_id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Screening run not found")
    return ScreeningRunRead.model_validate(run)


@router.get(
    "/results",
    response_model=list[ScreeningResultRead],
    summary="Latest screening results with filters",
)
async def list_results(
    overall_status: str | None = Query(None, description="PASS|FAIL|WATCHLIST"),
    instrument_type: str | None = Query(None),
    block_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[ScreeningResultRead]:
    stmt = (
        select(
            ScreeningResult,
            Instrument.name.label("inst_name"),
            Instrument.isin.label("inst_isin"),
            Instrument.ticker.label("inst_ticker"),
            Instrument.instrument_type.label("inst_type"),
            Instrument.block_id.label("inst_block_id"),
            Instrument.geography.label("inst_geography"),
            Instrument.currency.label("inst_currency"),
            Instrument.attributes["sec_crd_number"].astext.label("inst_manager_crd"),
            Instrument.attributes["strategy"].astext.label("inst_strategy"),
            Instrument.attributes["aum"].astext.label("inst_aum"),
        )
        .join(
            Instrument,
            ScreeningResult.instrument_id == Instrument.instrument_id,
        )
        .where(ScreeningResult.is_current.is_(True))
    )
    if overall_status:
        stmt = stmt.where(ScreeningResult.overall_status == overall_status)
    if instrument_type:
        stmt = stmt.where(Instrument.instrument_type == instrument_type)
    if block_id:
        stmt = stmt.where(Instrument.block_id == block_id)

    stmt = stmt.order_by(ScreeningResult.score.desc().nulls_last()).limit(limit)
    result = await db.execute(stmt)
    rows = result.all()

    enriched: list[ScreeningResultRead] = []
    for row in rows:
        sr = row[0]
        data = ScreeningResultRead.model_validate(sr)
        data.name = row.inst_name
        data.isin = row.inst_isin
        data.ticker = row.inst_ticker
        data.instrument_type = row.inst_type
        data.block_id = row.inst_block_id
        data.geography = row.inst_geography
        data.currency = row.inst_currency
        data.manager_crd = row.inst_manager_crd
        data.strategy = row.inst_strategy
        try:
            data.aum = float(row.inst_aum) if row.inst_aum else None
        except (ValueError, TypeError):
            data.aum = None
        enriched.append(data)

    return enriched


@router.get(
    "/results/{instrument_id}",
    response_model=list[ScreeningResultRead],
    summary="Screening history for instrument",
)
async def get_instrument_results(
    instrument_id: uuid.UUID,
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[ScreeningResultRead]:
    result = await db.execute(
        select(ScreeningResult)
        .where(ScreeningResult.instrument_id == instrument_id)
        .order_by(ScreeningResult.screened_at.desc())
        .limit(limit)
    )
    results = result.scalars().all()
    return [ScreeningResultRead.model_validate(r) for r in results]


# ── Global Instrument Search ────────────────────────────────────────────


def _build_internal_query(
    q: str | None,
    instrument_type: str | None,
    asset_class: str | None,
    geography: str | None,
    domicile: str | None,
    currency: str | None,
    strategy: str | None,
    aum_min: float | None,
    aum_max: float | None,
    block_id: str | None,
    approval_status: str | None,
):
    """Build a select for instruments_universe rows."""
    stmt = (
        select(
            Instrument.instrument_id.cast(String).label("instrument_id"),
            literal("internal").label("source"),
            Instrument.instrument_type.label("instrument_type"),
            Instrument.name.label("name"),
            Instrument.isin.label("isin"),
            Instrument.ticker.label("ticker"),
            Instrument.asset_class.label("asset_class"),
            Instrument.geography.label("geography"),
            Instrument.attributes["domicile"].astext.label("domicile"),
            Instrument.currency.label("currency"),
            Instrument.attributes["strategy"].astext.label("strategy"),
            Instrument.attributes["aum"].astext.label("aum"),
            Instrument.attributes["manager_name"].astext.label("manager_name"),
            Instrument.attributes["sec_crd_number"].astext.label("manager_crd"),
            literal(None).label("esma_manager_id"),
            Instrument.approval_status.label("approval_status"),
            Instrument.block_id.label("block_id"),
            Instrument.attributes["structure"].astext.label("structure"),
        )
        .where(Instrument.is_active.is_(True))
    )
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            Instrument.name.ilike(pattern)
            | Instrument.isin.ilike(pattern)
            | Instrument.ticker.ilike(pattern)
            | Instrument.attributes["manager_name"].astext.ilike(pattern)
        )
    if instrument_type:
        stmt = stmt.where(Instrument.instrument_type == instrument_type)
    if asset_class:
        stmt = stmt.where(Instrument.asset_class == asset_class)
    if geography:
        stmt = stmt.where(Instrument.geography == geography)
    if domicile:
        stmt = stmt.where(Instrument.attributes["domicile"].astext == domicile)
    if currency:
        stmt = stmt.where(Instrument.currency == currency)
    if strategy:
        stmt = stmt.where(Instrument.attributes["strategy"].astext == strategy)
    if aum_min is not None:
        stmt = stmt.where(Instrument.attributes["aum"].astext.cast(Float) >= aum_min)
    if aum_max is not None:
        stmt = stmt.where(Instrument.attributes["aum"].astext.cast(Float) <= aum_max)
    if block_id:
        stmt = stmt.where(Instrument.block_id == block_id)
    if approval_status:
        stmt = stmt.where(Instrument.approval_status == approval_status)
    return stmt


def _build_esma_query(
    q: str | None,
    geography: str | None,
    domicile: str | None,
    currency: str | None,
):
    """Build a select for esma_funds joined with ticker map."""
    # Map domicile to currency/geography for ESMA
    stmt = (
        select(
            literal(None).label("instrument_id"),
            literal("esma").label("source"),
            literal("fund").label("instrument_type"),
            EsmaFund.fund_name.label("name"),
            EsmaFund.isin.label("isin"),
            EsmaIsinTickerMap.yahoo_ticker.label("ticker"),
            literal("alternatives").label("asset_class"),
            sa_func.coalesce(EsmaFund.domicile, literal("dm_europe")).label("geography"),
            EsmaFund.domicile.label("domicile"),
            literal("EUR").label("currency"),
            EsmaFund.fund_type.label("strategy"),
            literal(None).label("aum"),
            EsmaManager.company_name.label("manager_name"),
            literal(None).label("manager_crd"),
            EsmaFund.esma_manager_id.label("esma_manager_id"),
            literal(None).label("approval_status"),
            literal(None).label("block_id"),
            literal("UCITS").label("structure"),
        )
        .select_from(EsmaFund)
        .outerjoin(EsmaIsinTickerMap, EsmaFund.isin == EsmaIsinTickerMap.isin)
        .outerjoin(EsmaManager, EsmaFund.esma_manager_id == EsmaManager.esma_id)
    )
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            EsmaFund.fund_name.ilike(pattern)
            | EsmaFund.isin.ilike(pattern)
            | EsmaIsinTickerMap.yahoo_ticker.ilike(pattern)
            | EsmaManager.company_name.ilike(pattern)
        )
    if domicile:
        stmt = stmt.where(EsmaFund.domicile == domicile)
    if geography and geography != "dm_europe":
        # ESMA only has European funds, filter out unless dm_europe or global
        if geography != "global":
            stmt = stmt.where(literal(False))
    return stmt


@router.get(
    "/search",
    response_model=InstrumentSearchPage,
    summary="Global instrument search across internal universe and ESMA",
)
async def search_instruments(
    q: str | None = Query(None),
    instrument_type: str | None = Query(None),
    asset_class: str | None = Query(None),
    geography: str | None = Query(None),
    domicile: str | None = Query(None),
    currency: str | None = Query(None),
    strategy: str | None = Query(None),
    aum_min: float | None = Query(None),
    aum_max: float | None = Query(None),
    block_id: str | None = Query(None),
    approval_status: str | None = Query(None),
    source: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_with_rls),
    org_id: uuid.UUID = Depends(get_org_id),
) -> InstrumentSearchPage:
    queries = []

    # Internal universe (always unless source=esma)
    if source != "esma":
        queries.append(
            _build_internal_query(
                q, instrument_type, asset_class, geography,
                domicile, currency, strategy, aum_min, aum_max,
                block_id, approval_status,
            )
        )

    # ESMA (if source=esma, or source is None and instrument_type is fund-like or None)
    if source == "esma" or (
        source is None
        and instrument_type in (None, "fund")
        and block_id is None
        and approval_status is None
    ):
        queries.append(_build_esma_query(q, geography, domicile, currency))

    if not queries:
        return InstrumentSearchPage(items=[], total=0, page=page, page_size=page_size, has_next=False)

    combined = union_all(*queries).subquery("combined")

    # Count
    count_stmt = select(sa_func.count()).select_from(combined)
    total = (await db.execute(count_stmt)).scalar() or 0

    # Paginate
    offset = (page - 1) * page_size
    data_stmt = select(combined).order_by(combined.c.name).offset(offset).limit(page_size)
    rows = (await db.execute(data_stmt)).all()

    # Enrich with screening status (left join on instrument_id)
    instrument_ids = [r.instrument_id for r in rows if r.instrument_id]
    screening_map: dict[str, tuple[str | None, float | None]] = {}
    if instrument_ids:
        sr_stmt = (
            select(
                ScreeningResult.instrument_id.cast(String),
                ScreeningResult.overall_status,
                ScreeningResult.score,
            )
            .where(
                ScreeningResult.instrument_id.in_([uuid.UUID(iid) for iid in instrument_ids]),
                ScreeningResult.is_current.is_(True),
            )
        )
        sr_rows = (await db.execute(sr_stmt)).all()
        for iid, sr_status, sr_score in sr_rows:
            screening_map[iid] = (sr_status, float(sr_score) if sr_score is not None else None)

    items = []
    for r in rows:
        scr_status, scr_score = screening_map.get(r.instrument_id or "", (None, None))
        aum_val = None
        if r.aum is not None:
            try:
                aum_val = float(r.aum)
            except (ValueError, TypeError):
                pass
        items.append(
            InstrumentSearchItem(
                instrument_id=r.instrument_id,
                source=r.source,
                instrument_type=r.instrument_type,
                name=r.name or "",
                isin=r.isin,
                ticker=r.ticker,
                asset_class=r.asset_class or "",
                geography=r.geography or "",
                domicile=r.domicile,
                currency=r.currency or "USD",
                strategy=r.strategy,
                aum=aum_val,
                manager_name=r.manager_name,
                manager_crd=r.manager_crd,
                esma_manager_id=r.esma_manager_id,
                approval_status=r.approval_status,
                screening_status=scr_status,
                screening_score=scr_score,
                block_id=r.block_id,
                structure=r.structure,
            )
        )

    return InstrumentSearchPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_next=(offset + page_size) < total,
    )


@router.get(
    "/facets",
    response_model=ScreenerFacets,
    summary="Facet counts for screener sidebar filters",
)
async def get_screener_facets(
    q: str | None = Query(None),
    instrument_type: str | None = Query(None),
    asset_class: str | None = Query(None),
    geography: str | None = Query(None),
    source: str | None = Query(None),
    db: AsyncSession = Depends(get_db_with_rls),
    org_id: uuid.UUID = Depends(get_org_id),
) -> ScreenerFacets:
    """Compute facet counts from instruments_universe + ESMA.

    Returns counts by instrument_type, geography, asset_class, domicile,
    currency, strategy, source, and screening status.
    """
    # Internal facets
    base = select(Instrument).where(Instrument.is_active.is_(True))
    if q:
        pattern = f"%{q}%"
        base = base.where(
            Instrument.name.ilike(pattern) | Instrument.isin.ilike(pattern) | Instrument.ticker.ilike(pattern)
        )

    result = await db.execute(base)
    instruments = result.scalars().all()

    type_counts: dict[str, int] = {}
    geo_counts: dict[str, int] = {}
    ac_counts: dict[str, int] = {}
    dom_counts: dict[str, int] = {}
    cur_counts: dict[str, int] = {}
    strat_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {"internal": 0, "esma": 0}
    total_approved = 0

    for inst in instruments:
        type_counts[inst.instrument_type] = type_counts.get(inst.instrument_type, 0) + 1
        geo_counts[inst.geography] = geo_counts.get(inst.geography, 0) + 1
        ac_counts[inst.asset_class] = ac_counts.get(inst.asset_class, 0) + 1
        cur_counts[inst.currency] = cur_counts.get(inst.currency, 0) + 1
        source_counts["internal"] += 1
        if inst.approval_status == "approved":
            total_approved += 1
        attrs = inst.attributes or {}
        dom = attrs.get("domicile")
        if dom:
            dom_counts[dom] = dom_counts.get(dom, 0) + 1
        strat = attrs.get("strategy")
        if strat:
            strat_counts[strat] = strat_counts.get(strat, 0) + 1

    # ESMA count (if not filtered to internal only)
    if source != "internal":
        esma_count_stmt = select(sa_func.count()).select_from(EsmaFund)
        if q:
            esma_count_stmt = esma_count_stmt.where(
                EsmaFund.fund_name.ilike(f"%{q}%") | EsmaFund.isin.ilike(f"%{q}%")
            )
        esma_count = (await db.execute(esma_count_stmt)).scalar() or 0
        source_counts["esma"] = esma_count
        type_counts["fund"] = type_counts.get("fund", 0) + esma_count
        geo_counts["dm_europe"] = geo_counts.get("dm_europe", 0) + esma_count

    # Screening status facets
    sr_stmt = (
        select(ScreeningResult.overall_status, sa_func.count())
        .where(ScreeningResult.is_current.is_(True))
        .group_by(ScreeningResult.overall_status)
    )
    sr_result = await db.execute(sr_stmt)
    scr_counts: dict[str, int] = {}
    total_screened = 0
    for sr_status, sr_count in sr_result.all():
        scr_counts[sr_status] = sr_count
        total_screened += sr_count

    def to_facets(counts: dict[str, int]) -> list[FacetItem]:
        return sorted(
            [FacetItem(value=k, label=k, count=v) for k, v in counts.items() if v > 0],
            key=lambda f: -f.count,
        )

    total_universe = sum(source_counts.values())
    return ScreenerFacets(
        instrument_types=to_facets(type_counts),
        geographies=to_facets(geo_counts),
        asset_classes=to_facets(ac_counts),
        domiciles=to_facets(dom_counts),
        currencies=to_facets(cur_counts),
        strategies=to_facets(strat_counts),
        sources=to_facets(source_counts),
        screening_statuses=to_facets(scr_counts),
        total_universe=total_universe,
        total_screened=total_screened,
        total_approved=total_approved,
    )


# ── ESMA Import ─────────────────────────────────────────────────────────


@router.post(
    "/import-esma/{isin}",
    response_model=ScreeningResultRead,
    status_code=status.HTTP_201_CREATED,
    summary="Import an ESMA fund into instruments_universe",
)
async def import_esma_fund(
    isin: str,
    body: EsmaImportRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    org_id: uuid.UUID = Depends(get_org_id),
    actor: Actor = Depends(get_actor),
) -> dict:
    _require_investment_role(actor)

    from app.domains.wealth.services.esma_import_service import import_esma_fund_to_universe

    instrument = await import_esma_fund_to_universe(
        db, org_id, isin, block_id=body.block_id, strategy=body.strategy,
    )
    return {
        "instrument_id": str(instrument.instrument_id),
        "name": instrument.name,
        "isin": instrument.isin,
        "status": "imported",
    }
