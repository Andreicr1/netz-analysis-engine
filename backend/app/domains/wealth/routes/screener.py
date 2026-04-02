"""Screener API routes — trigger and query instrument screening.

POST /screener/run      — trigger on-demand screening
GET  /screener/runs     — list screening runs
GET  /screener/runs/{id}— run detail with results
GET  /screener/results  — latest results with filters
GET  /screener/results/{instrument_id} — screening history
GET  /screener/search   — global instrument search (server-side)
GET  /screener/facets   — facet counts for filter sidebar
GET  /screener/securities         — global equity/ETF discovery (no RLS)
GET  /screener/securities/facets  — facets for global securities
POST /screener/import/{identifier}  — unified import (auto-detect ISIN or ticker)
POST /screener/import-esma/{isin}    — import ESMA fund to universe (alias)
POST /screener/import-sec/{ticker}   — import SEC security to universe (alias)
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import Float, Select, String, case, literal, select, union_all
from sqlalchemy import func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import route_cache
from app.core.config.config_service import ConfigService
from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.instrument_org import InstrumentOrg
from app.domains.wealth.models.screening_result import ScreeningResult, ScreeningRun
from app.domains.wealth.queries.catalog_sql import (
    CatalogFilters,
    build_catalog_facets_query,
    build_catalog_query,
    sec_money_market_funds,
)
from app.domains.wealth.schemas.catalog import (
    CatalogFacetItem,
    CatalogFacets,
    DisclosureMatrix,
    FundFactSheet,
    FundHolding,
    NavPoint,
    TeamMember,
    UnifiedCatalogPage,
    UnifiedFundItem,
)
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
from app.shared.models import EsmaFund, EsmaManager, SecCusipTickerMap

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

    # Load instruments to screen (join InstrumentOrg for org-scoped block_id)
    stmt = (
        select(Instrument, InstrumentOrg.block_id.label("org_block_id"))
        .join(InstrumentOrg, InstrumentOrg.instrument_id == Instrument.instrument_id)
        .where(Instrument.is_active.is_(True))
    )
    if body.instrument_type:
        stmt = stmt.where(Instrument.instrument_type == body.instrument_type)
    if body.block_id:
        stmt = stmt.where(InstrumentOrg.block_id == body.block_id)
    if body.instrument_ids:
        stmt = stmt.where(Instrument.instrument_id.in_(body.instrument_ids))

    result = await db.execute(stmt)
    rows = result.all()

    if not rows:
        raise HTTPException(status_code=404, detail="No instruments found matching criteria")

    instruments = [row[0] for row in rows]

    # Load screening config
    config_svc = ConfigService(db)
    config_l1 = (await config_svc.get("liquid_funds", "screening_layer1", org_id)).value
    config_l2 = (await config_svc.get("liquid_funds", "screening_layer2", org_id)).value
    config_l3 = (await config_svc.get("liquid_funds", "screening_layer3", org_id)).value

    config_hash = hashlib.sha256(
        json.dumps({"l1": config_l1, "l2": config_l2, "l3": config_l3}, sort_keys=True).encode(),
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
            "instrument_id": row[0].instrument_id,
            "instrument_type": row[0].instrument_type,
            "attributes": dict(row[0].attributes) if row[0].attributes else {},
            "block_id": row.org_block_id,
        }
        for row in rows
    ]

    # Run screening in thread (pure CPU logic)
    from vertical_engines.wealth.screener.service import ScreenerService

    screener = ScreenerService(config_l1, config_l2, config_l3)
    screening_results = await asyncio.to_thread(
        lambda: [
            screener.screen_instrument(**inst_dict)
            for inst_dict in instrument_dicts
        ],
    )

    # Mark previous results as not current
    for inst_dict in instrument_dicts:
        await db.execute(
            select(ScreeningResult)
            .where(
                ScreeningResult.instrument_id == inst_dict["instrument_id"],
                ScreeningResult.is_current.is_(True),
            )
            .with_for_update(),
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
    run.completed_at = datetime.now(UTC)
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
        .limit(limit),
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
        select(ScreeningRun).where(ScreeningRun.run_id == run_id),
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
@route_cache(ttl=60, key_prefix="screener:results")
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
            InstrumentOrg.block_id.label("inst_block_id"),
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
        .join(
            InstrumentOrg,
            InstrumentOrg.instrument_id == Instrument.instrument_id,
        )
        .where(ScreeningResult.is_current.is_(True))
    )
    if overall_status:
        stmt = stmt.where(ScreeningResult.overall_status == overall_status)
    if instrument_type:
        stmt = stmt.where(Instrument.instrument_type == instrument_type)
    if block_id:
        stmt = stmt.where(InstrumentOrg.block_id == block_id)

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
        .limit(limit),
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
) -> Select[Any]:
    """Build a select for instruments_universe rows (joined with instruments_org)."""
    _internal_geo_case = case(
        (Instrument.geography == "north_america", literal("US")),
        (Instrument.geography == "dm_europe", literal("Europe")),
        (Instrument.geography == "dm_asia", literal("Asia")),
        (Instrument.geography == "emerging", literal("Emerging Markets")),
        (Instrument.geography == "global", literal("Global")),
        else_=Instrument.geography,
    )
    stmt = (
        select(
            Instrument.instrument_id.cast(String).label("instrument_id"),
            literal("internal").label("source"),
            Instrument.instrument_type.label("instrument_type"),
            Instrument.name.label("name"),
            Instrument.isin.label("isin"),
            Instrument.ticker.label("ticker"),
            Instrument.asset_class.label("asset_class"),
            _internal_geo_case.label("geography"),
            Instrument.investment_geography.label("investment_geography"),
            Instrument.attributes["domicile"].astext.label("domicile"),
            Instrument.currency.label("currency"),
            Instrument.attributes["strategy"].astext.label("strategy"),
            Instrument.attributes["aum"].astext.label("aum"),
            Instrument.attributes["manager_name"].astext.label("manager_name"),
            Instrument.attributes["sec_crd_number"].astext.label("manager_crd"),
            literal(None).label("esma_manager_id"),
            InstrumentOrg.approval_status.label("approval_status"),
            InstrumentOrg.block_id.label("block_id"),
            Instrument.attributes["structure"].astext.label("structure"),
        )
        .join(InstrumentOrg, InstrumentOrg.instrument_id == Instrument.instrument_id)
        .where(Instrument.is_active.is_(True))
    )
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            Instrument.name.ilike(pattern)
            | Instrument.isin.ilike(pattern)
            | Instrument.ticker.ilike(pattern)
            | Instrument.attributes["manager_name"].astext.ilike(pattern),
        )
    if instrument_type:
        stmt = stmt.where(Instrument.instrument_type == instrument_type)
    if asset_class:
        stmt = stmt.where(Instrument.asset_class == asset_class)
    if geography:
        stmt = stmt.where(_internal_geo_case == geography)
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
        stmt = stmt.where(InstrumentOrg.block_id == block_id)
    if approval_status:
        stmt = stmt.where(InstrumentOrg.approval_status == approval_status)
    return stmt


_esma_geo_case = case(
    (EsmaFund.fund_name.ilike("%emerging%"), literal("Emerging Markets")),
    (EsmaFund.fund_name.ilike("%frontier%"), literal("Emerging Markets")),
    (EsmaFund.fund_name.ilike("%latin america%"), literal("Latin America")),
    (EsmaFund.fund_name.ilike("%latam%"), literal("Latin America")),
    (EsmaFund.fund_name.ilike("%brazil%"), literal("Latin America")),
    (EsmaFund.fund_name.ilike("%asia%"), literal("Asia")),
    (EsmaFund.fund_name.ilike("%japan%"), literal("Asia")),
    (EsmaFund.fund_name.ilike("%china%"), literal("Asia")),
    (EsmaFund.fund_name.ilike("%india%"), literal("Asia")),
    (EsmaFund.fund_name.ilike("%pacific%"), literal("Asia")),
    (EsmaFund.fund_name.ilike("%nikkei%"), literal("Asia")),
    (EsmaFund.fund_name.ilike("% us %"), literal("US")),
    (EsmaFund.fund_name.ilike("%america%"), literal("US")),
    (EsmaFund.fund_name.ilike("%s&p%"), literal("US")),
    (EsmaFund.fund_name.ilike("%nasdaq%"), literal("US")),
    (EsmaFund.fund_name.ilike("%russell%"), literal("US")),
    (EsmaFund.fund_name.ilike("%global%"), literal("Global")),
    (EsmaFund.fund_name.ilike("%world%"), literal("Global")),
    (EsmaFund.fund_name.ilike("%international%"), literal("Global")),
    (EsmaFund.fund_name.ilike("%europ%"), literal("Europe")),
    (EsmaFund.fund_name.ilike("%euro %"), literal("Europe")),
    (EsmaFund.fund_name.ilike("%stoxx%"), literal("Europe")),
    else_=literal("Europe"),
)


def _build_esma_query(
    q: str | None,
    geography: str | None,
    domicile: str | None,
    currency: str | None,
) -> Select[Any]:
    """Build a select for esma_funds — only funds with Yahoo tickers (investable)."""
    stmt = (
        select(
            literal(None).label("instrument_id"),
            literal("esma").label("source"),
            literal("fund").label("instrument_type"),
            EsmaFund.fund_name.label("name"),
            EsmaFund.isin.label("isin"),
            EsmaFund.yahoo_ticker.label("ticker"),
            literal("alternatives").label("asset_class"),
            _esma_geo_case.label("geography"),
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
        .outerjoin(EsmaManager, EsmaFund.esma_manager_id == EsmaManager.esma_id)
        .where(EsmaFund.yahoo_ticker.isnot(None))
        .where(EsmaFund.yahoo_ticker != "")
    )
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            EsmaFund.fund_name.ilike(pattern)
            | EsmaFund.isin.ilike(pattern)
            | EsmaFund.yahoo_ticker.ilike(pattern)
            | EsmaManager.company_name.ilike(pattern),
        )
    if domicile:
        stmt = stmt.where(EsmaFund.domicile == domicile)
    if geography:
        stmt = stmt.where(_esma_geo_case == geography)
    return stmt


def _build_sec_query(
    q: str | None,
    geography: str | None,
    instrument_type: str | None,
) -> Select[Any]:
    """Build a select for US tradeable securities from sec_cusip_ticker_map.

    These are equities, ETFs, closed-end funds, REITs, and ADRs held by
    major institutional investors (13F filers). All have tickers for
    YFinance pricing.
    """
    type_case = case(
        (SecCusipTickerMap.security_type == "Common Stock", literal("equity")),
        (SecCusipTickerMap.security_type == "ETP", literal("fund")),
        (SecCusipTickerMap.security_type == "Closed-End Fund", literal("fund")),
        (SecCusipTickerMap.security_type == "Open-End Fund", literal("fund")),
        (SecCusipTickerMap.security_type == "ADR", literal("equity")),
        (SecCusipTickerMap.security_type == "REIT", literal("equity")),
        (SecCusipTickerMap.security_type == "MLP", literal("equity")),
        else_=literal("equity"),
    )

    asset_class_case = case(
        (SecCusipTickerMap.security_type == "ETP", literal("fund")),
        (SecCusipTickerMap.security_type == "Closed-End Fund", literal("fund")),
        (SecCusipTickerMap.security_type == "Open-End Fund", literal("fund")),
        (SecCusipTickerMap.security_type == "REIT", literal("real_estate")),
        else_=literal("equity"),
    )

    stmt = (
        select(
            literal(None).label("instrument_id"),
            literal("sec").label("source"),
            type_case.label("instrument_type"),
            SecCusipTickerMap.issuer_name.label("name"),
            literal(None).label("isin"),
            SecCusipTickerMap.ticker.label("ticker"),
            asset_class_case.label("asset_class"),
            literal("US").label("geography"),
            literal("US").label("domicile"),
            literal("USD").label("currency"),
            SecCusipTickerMap.security_type.label("strategy"),
            literal(None).label("aum"),
            literal(None).label("manager_name"),
            literal(None).label("manager_crd"),
            literal(None).label("esma_manager_id"),
            literal(None).label("approval_status"),
            literal(None).label("block_id"),
            SecCusipTickerMap.security_type.label("structure"),
        )
        .where(SecCusipTickerMap.is_tradeable.is_(True))
    )
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            SecCusipTickerMap.issuer_name.ilike(pattern)
            | SecCusipTickerMap.ticker.ilike(pattern)
            | (SecCusipTickerMap.cusip == q),
        )
    if instrument_type:
        stmt = stmt.where(type_case == instrument_type)
    if geography and geography not in ("US", "Global"):
        stmt = stmt.where(literal(False))
    return stmt


@router.get(
    "/search",
    response_model=InstrumentSearchPage,
    summary="Global instrument search across internal universe, ESMA, and SEC",
)
@route_cache(ttl=60, key_prefix="screener:search")
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
            ),
        )

    # ESMA (if source=esma, or source is None and instrument_type is fund-like or None)
    if source == "esma" or (
        source is None
        and instrument_type in (None, "fund")
        and block_id is None
        and approval_status is None
    ):
        queries.append(_build_esma_query(q, geography, domicile, currency))

    # SEC/US tradeable securities (if source=sec, or source is None and compatible type)
    if source == "sec" or (
        source is None
        and instrument_type in (None, "fund", "equity")
        and block_id is None
        and approval_status is None
    ):
        queries.append(_build_sec_query(q, geography, instrument_type))

    if not queries:
        return InstrumentSearchPage(items=[], total=0, page=page, page_size=page_size, has_next=False)

    combined = union_all(*queries).subquery("combined")

    # Count + paginate in one roundtrip using window function
    offset = (page - 1) * page_size
    total_col = sa_func.count().over().label("_total")
    data_stmt = (
        select(combined, total_col)
        .order_by(combined.c.name)
        .offset(offset)
        .limit(page_size)
    )
    rows_raw = (await db.execute(data_stmt)).all()

    total = rows_raw[0]._total if rows_raw else 0
    rows = rows_raw

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
            ),
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
@route_cache(ttl=300, key_prefix="screener:facets")
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
    # Internal facets (join InstrumentOrg for org-scoped approval_status)
    base = (
        select(Instrument, InstrumentOrg.approval_status.label("org_approval_status"))
        .join(InstrumentOrg, InstrumentOrg.instrument_id == Instrument.instrument_id)
        .where(Instrument.is_active.is_(True))
    )
    if q:
        pattern = f"%{q}%"
        base = base.where(
            Instrument.name.ilike(pattern) | Instrument.isin.ilike(pattern) | Instrument.ticker.ilike(pattern),
        )
    if instrument_type:
        base = base.where(Instrument.instrument_type == instrument_type)
    if asset_class:
        base = base.where(Instrument.asset_class == asset_class)
    if geography:
        base = base.where(Instrument.geography == geography)

    result = await db.execute(base)
    rows = result.all()

    _GEO_DISPLAY_MAP = {
        "north_america": "US",
        "dm_europe": "Europe",
        "dm_asia": "Asia",
        "emerging": "Emerging Markets",
        "global": "Global",
    }

    type_counts: dict[str, int] = {}
    geo_counts: dict[str, int] = {}
    ac_counts: dict[str, int] = {}
    dom_counts: dict[str, int] = {}
    cur_counts: dict[str, int] = {}
    strat_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {"internal": 0, "esma": 0, "sec": 0}
    total_approved = 0

    for row in rows:
        inst = row[0]
        type_counts[inst.instrument_type] = type_counts.get(inst.instrument_type, 0) + 1
        geo_display = _GEO_DISPLAY_MAP.get(inst.geography, inst.geography)
        geo_counts[geo_display] = geo_counts.get(geo_display, 0) + 1
        ac_counts[inst.asset_class] = ac_counts.get(inst.asset_class, 0) + 1
        cur_counts[inst.currency] = cur_counts.get(inst.currency, 0) + 1
        source_counts["internal"] += 1
        if row.org_approval_status == "approved":
            total_approved += 1
        attrs = inst.attributes or {}
        dom = attrs.get("domicile")
        if dom:
            dom_counts[dom] = dom_counts.get(dom, 0) + 1
        strat = attrs.get("strategy")
        if strat:
            strat_counts[strat] = strat_counts.get(strat, 0) + 1

    # ESMA geography facets (only tickered funds)
    if source != "internal":
        esma_geo_stmt = (
            select(_esma_geo_case, sa_func.count())
            .select_from(EsmaFund)
            .where(EsmaFund.yahoo_ticker.isnot(None))
            .where(EsmaFund.yahoo_ticker != "")
            .group_by(_esma_geo_case)
        )
        if q:
            esma_geo_stmt = esma_geo_stmt.where(
                EsmaFund.fund_name.ilike(f"%{q}%") | EsmaFund.isin.ilike(f"%{q}%"),
            )
        esma_total = 0
        for geo_label, cnt in (await db.execute(esma_geo_stmt)).all():
            geo_counts[geo_label] = geo_counts.get(geo_label, 0) + cnt
            esma_total += cnt
        source_counts["esma"] = esma_total
        type_counts["fund"] = type_counts.get("fund", 0) + esma_total

    # SEC tradeable securities facets
    if source not in ("internal", "esma"):
        sec_count_stmt = (
            select(sa_func.count())
            .select_from(SecCusipTickerMap)
            .where(SecCusipTickerMap.is_tradeable.is_(True))
        )
        if q:
            sec_count_stmt = sec_count_stmt.where(
                SecCusipTickerMap.issuer_name.ilike(f"%{q}%")
                | SecCusipTickerMap.ticker.ilike(f"%{q}%"),
            )
        sec_count = (await db.execute(sec_count_stmt)).scalar() or 0
        source_counts["sec"] = sec_count
        geo_counts["US"] = geo_counts.get("US", 0) + sec_count

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
    status_code=status.HTTP_201_CREATED,
    summary="Import an ESMA fund into instruments_universe",
)
async def import_esma_fund(
    isin: str,
    body: EsmaImportRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    org_id: uuid.UUID = Depends(get_org_id),
    actor: Actor = Depends(get_actor),
) -> dict[str, object]:
    _require_investment_role(actor)

    from app.domains.wealth.services.esma_import_service import import_esma_fund_to_universe

    instrument = await import_esma_fund_to_universe(
        db, org_id, isin, block_id=body.block_id, strategy=body.strategy,
    )
    await db.commit()

    return {
        "instrument_id": str(instrument.instrument_id),
        "name": instrument.name,
        "isin": instrument.isin,
        "status": "imported",
    }


# ── Unified Import ─────────────────────────────────────────────────────

_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


@router.post(
    "/import/{identifier}",
    status_code=status.HTTP_201_CREATED,
    summary="Import a fund by ISIN (ESMA) or ticker (SEC) into instruments_universe",
)
async def import_fund(
    identifier: str,
    body: EsmaImportRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    org_id: uuid.UUID = Depends(get_org_id),
    actor: Actor = Depends(get_actor),
) -> dict[str, object]:
    """Auto-detect identifier format and route to the correct importer."""
    if _ISIN_RE.match(identifier.upper()):
        return await import_esma_fund(
            isin=identifier.upper(), body=body, db=db, org_id=org_id, actor=actor,
        )
    return await import_sec_security(
        ticker=identifier.upper(), body=body, db=db, org_id=org_id, actor=actor,
    )


# ── SEC Import ──────────────────────────────────────────────────────────


@router.post(
    "/import-sec/{ticker}",
    status_code=status.HTTP_201_CREATED,
    summary="Import a US security into instruments_universe",
)
async def import_sec_security(
    ticker: str,
    body: EsmaImportRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    org_id: uuid.UUID = Depends(get_org_id),
    actor: Actor = Depends(get_actor),
) -> dict[str, object]:
    _require_investment_role(actor)

    # Check if instrument already exists globally by ticker
    existing = (await db.execute(
        select(Instrument).where(
            Instrument.ticker == ticker.upper(),
        ),
    )).scalar_one_or_none()
    if existing:
        # Check if already linked to this org
        existing_link = (await db.execute(
            select(InstrumentOrg).where(
                InstrumentOrg.instrument_id == existing.instrument_id,
                InstrumentOrg.organization_id == org_id,
            ),
        )).scalar_one_or_none()
        if existing_link:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Instrument with ticker {ticker} already exists in your universe",
            )
        # Link existing global instrument to this org
        org_link = InstrumentOrg(
            organization_id=org_id,
            instrument_id=existing.instrument_id,
            block_id=body.block_id,
            approval_status="pending",
        )
        db.add(org_link)
        await db.commit()
        return {
            "instrument_id": str(existing.instrument_id),
            "name": existing.name,
            "ticker": existing.ticker,
            "status": "imported",
        }

    # Lookup from sec_cusip_ticker_map
    sec_row = (await db.execute(
        select(SecCusipTickerMap).where(
            SecCusipTickerMap.ticker == ticker.upper(),
            SecCusipTickerMap.is_tradeable.is_(True),
        ).limit(1),
    )).scalar_one_or_none()
    if not sec_row:
        # Fallback: mutual fund tickers are in sec_fund_classes, not cusip_ticker_map
        from types import SimpleNamespace

        from app.shared.models import SecFundClass as _FcFallback
        from app.shared.models import SecRegisteredFund as _RfFallback

        fc_fallback = (await db.execute(
            select(_FcFallback).where(_FcFallback.ticker == ticker.upper()).limit(1),
        )).scalar_one_or_none()
        if not fc_fallback:
            raise HTTPException(status_code=404, detail=f"Tradeable security with ticker {ticker} not found")
        rf_fallback = (await db.execute(
            select(_RfFallback).where(_RfFallback.cik == fc_fallback.cik),
        )).scalar_one_or_none()
        sec_row = SimpleNamespace(  # type: ignore[assignment]  # duck-types as SecCusipTickerMap
            ticker=ticker.upper(),
            issuer_name=rf_fallback.fund_name if rf_fallback else (fc_fallback.series_name or ticker),
            security_type="Open-End Fund",
            cusip=None, exchange=None, figi=None, composite_figi=None,
            is_tradeable=True,
        )

    assert sec_row is not None  # guaranteed: either from DB or SimpleNamespace fallback

    # Map security_type to instrument_type
    _type_map = {
        "Common Stock": "equity", "ETP": "fund", "Closed-End Fund": "fund",
        "Open-End Fund": "fund", "ADR": "equity", "REIT": "equity", "MLP": "equity",
    }
    inst_type = _type_map.get(sec_row.security_type or "", "equity")
    asset_class = "fund" if inst_type == "fund" else "equity"

    # Resolve SEC registered fund linkage (CIK + universe) for N-PORT data
    sec_cik: str | None = None
    sec_universe: str | None = None
    sec_crd: str | None = None
    fund_manager_name = sec_row.issuer_name
    enrichment_attrs: dict[str, object] = {}
    if inst_type == "fund":
        from app.shared.models import SecEtf, SecFundClass, SecRegisteredFund

        reg_fund = (await db.execute(
            select(SecRegisteredFund).where(
                SecRegisteredFund.ticker == sec_row.ticker,
            ).limit(1),
        )).scalar_one_or_none()

        # Fallback: search sec_fund_classes by ticker → find parent CIK
        if not reg_fund:
            fc_row = (await db.execute(
                select(SecFundClass).where(
                    SecFundClass.ticker == sec_row.ticker,
                ).limit(1),
            )).scalar_one_or_none()
            if fc_row:
                reg_fund = (await db.execute(
                    select(SecRegisteredFund).where(
                        SecRegisteredFund.cik == fc_row.cik,
                    ),
                )).scalar_one_or_none()

        # Fallback: search sec_etfs by ticker
        if not reg_fund:
            etf_row = (await db.execute(
                select(SecEtf).where(SecEtf.ticker == sec_row.ticker).limit(1),
            )).scalar_one_or_none()
            if etf_row:
                enrichment_attrs["sec_universe"] = "etf"
                enrichment_attrs["strategy_label"] = etf_row.strategy_label
                enrichment_attrs["is_index"] = etf_row.is_index
                if etf_row.net_operating_expenses is not None:
                    enrichment_attrs["expense_ratio_pct"] = float(etf_row.net_operating_expenses)
                if etf_row.tracking_difference_net is not None:
                    enrichment_attrs["tracking_difference_net"] = float(etf_row.tracking_difference_net)
                enrichment_attrs["index_tracked"] = etf_row.index_tracked

        # Fallback: search sec_bdcs by ticker
        if not reg_fund and not enrichment_attrs.get("sec_universe"):
            from app.shared.models import SecBdc

            bdc_row = (await db.execute(
                select(SecBdc).where(SecBdc.ticker == sec_row.ticker).limit(1),
            )).scalar_one_or_none()
            if bdc_row:
                enrichment_attrs["sec_universe"] = "bdc"
                enrichment_attrs["strategy_label"] = bdc_row.strategy_label
                if bdc_row.net_operating_expenses is not None:
                    enrichment_attrs["expense_ratio_pct"] = float(bdc_row.net_operating_expenses)
                enrichment_attrs["investment_focus"] = bdc_row.investment_focus
                enrichment_attrs["is_externally_managed"] = bdc_row.is_externally_managed

        # Note: sec_money_market_funds has no ticker column — MMFs are not
        # importable via ticker. They appear in the catalog for browsing only.

        if reg_fund:
            sec_cik = reg_fund.cik
            sec_universe = "registered_us"
            sec_crd = reg_fund.crd_number
            fund_manager_name = sec_row.issuer_name

            # Enrich with N-CEN flags
            enrichment_attrs["strategy_label"] = reg_fund.strategy_label
            enrichment_attrs["is_index"] = reg_fund.is_index
            enrichment_attrs["is_target_date"] = reg_fund.is_target_date
            enrichment_attrs["is_fund_of_fund"] = reg_fund.is_fund_of_fund
            if reg_fund.inception_date:
                enrichment_attrs["fund_inception_date"] = str(reg_fund.inception_date)

            # Enrich with XBRL per-share-class data (best class for this ticker)
            class_rows = (await db.execute(
                select(SecFundClass).where(SecFundClass.cik == sec_cik),
            )).scalars().all()
            if class_rows:
                # Prefer the class matching the imported ticker
                best = next(
                    (c for c in class_rows if c.ticker == sec_row.ticker),
                    max(class_rows, key=lambda c: float(c.net_assets or 0)),
                )
                if best.expense_ratio_pct is not None:
                    enrichment_attrs["expense_ratio_pct"] = float(best.expense_ratio_pct)
                if best.holdings_count is not None:
                    enrichment_attrs["holdings_count"] = best.holdings_count
                if best.portfolio_turnover_pct is not None:
                    enrichment_attrs["portfolio_turnover_pct"] = float(best.portfolio_turnover_pct)

            # Resolve manager name from sec_managers if available
            if reg_fund.crd_number:
                from app.shared.models import SecManager
                mgr = (await db.execute(
                    select(SecManager.firm_name).where(
                        SecManager.crd_number == reg_fund.crd_number,
                    ),
                )).scalar_one_or_none()
                if mgr:
                    fund_manager_name = mgr

    # ── Resolve L1 screening attributes from SEC data ────────────
    resolved_universe = sec_universe or enrichment_attrs.get("sec_universe")
    _UNIVERSE_TO_STRUCTURE = {
        "registered_us": "Mutual Fund",
        "etf": "ETF",
        "bdc": "BDC",
        "money_market": "Money Market",
    }
    resolved_structure = _UNIVERSE_TO_STRUCTURE.get(str(resolved_universe))

    # AUM: pick first non-null from SEC tables already queried
    resolved_aum: float | None = None
    if inst_type == "fund":
        if reg_fund and reg_fund.monthly_avg_net_assets is not None:
            resolved_aum = float(reg_fund.monthly_avg_net_assets)
        elif reg_fund and reg_fund.daily_avg_net_assets is not None:
            resolved_aum = float(reg_fund.daily_avg_net_assets)
        elif enrichment_attrs.get("sec_universe") == "etf":
            # etf_row was set above when enrichment_attrs["sec_universe"] == "etf"
            etf_aum = locals().get("etf_row")
            if etf_aum and getattr(etf_aum, "monthly_avg_net_assets", None) is not None:
                resolved_aum = float(etf_aum.monthly_avg_net_assets)
            elif etf_aum and getattr(etf_aum, "daily_avg_net_assets", None) is not None:
                resolved_aum = float(etf_aum.daily_avg_net_assets)
        elif enrichment_attrs.get("sec_universe") == "bdc":
            bdc_aum = locals().get("bdc_row")
            if bdc_aum and getattr(bdc_aum, "monthly_avg_net_assets", None) is not None:
                resolved_aum = float(bdc_aum.monthly_avg_net_assets)
            elif bdc_aum and getattr(bdc_aum, "daily_avg_net_assets", None) is not None:
                resolved_aum = float(bdc_aum.daily_avg_net_assets)
        # Fallback: XBRL net_assets from best share class
        if resolved_aum is None and enrichment_attrs.get("expense_ratio_pct") is not None:
            from app.shared.models import SecFundClass as _Fc
            _fc_aum = (await db.execute(
                select(_Fc.net_assets).where(
                    _Fc.ticker == sec_row.ticker,
                ).limit(1),
            )).scalar_one_or_none()
            if _fc_aum is not None:
                resolved_aum = float(_fc_aum)

    # Track record: compute from inception_date
    resolved_track_years: float | None = None
    inception_str = enrichment_attrs.get("fund_inception_date")
    if inception_str:
        try:
            inception_dt = dt.date.fromisoformat(str(inception_str))
            resolved_track_years = round(
                (dt.date.today() - inception_dt).days / 365.25, 1,
            )
        except (ValueError, TypeError):
            pass
    # Fallback: XBRL perf_inception_date
    if resolved_track_years is None and inst_type == "fund":
        from app.shared.models import SecFundClass as _Fc2
        _fc_inception = (await db.execute(
            select(_Fc2.perf_inception_date).where(
                _Fc2.ticker == sec_row.ticker,
            ).limit(1),
        )).scalar_one_or_none()
        if _fc_inception is not None:
            resolved_track_years = round(
                (dt.date.today() - _fc_inception).days / 365.25, 1,
            )

    instrument = Instrument(
        instrument_type=inst_type,
        name=sec_row.issuer_name,
        isin=None,
        ticker=sec_row.ticker,
        asset_class=asset_class,
        geography="north_america",
        currency="USD",
        attributes={
            "cusip": sec_row.cusip,
            "security_type": sec_row.security_type,
            "exchange": sec_row.exchange,
            "figi": sec_row.figi,
            "composite_figi": sec_row.composite_figi,
            "source": "sec",
            "strategy": body.strategy,
            # chk_fund_attrs requires these keys when instrument_type = 'fund'
            "manager_name": fund_manager_name,
            "aum_usd": resolved_aum,
            "inception_date": inception_str,
            # L1 screening attributes
            "domicile": "US",
            "structure": resolved_structure,
            "track_record_years": resolved_track_years,
            # SEC linkage for N-PORT fund-level data
            "sec_cik": sec_cik,
            "sec_crd": sec_crd,
            "sec_universe": resolved_universe,
            # Enrichment from N-CEN + XBRL
            **enrichment_attrs,
        },
    )
    db.add(instrument)
    await db.flush()

    # Create org-scoped link
    org_link = InstrumentOrg(
        organization_id=org_id,
        instrument_id=instrument.instrument_id,
        block_id=body.block_id,
        approval_status="pending",
    )
    db.add(org_link)
    await db.commit()
    await db.refresh(instrument)

    return {
        "instrument_id": str(instrument.instrument_id),
        "name": instrument.name,
        "ticker": instrument.ticker,
        "status": "imported",
    }


# ── Unified Fund Catalog ──────────────────────────────────────────────


def _build_disclosure(
    universe: str,
    has_holdings: bool,
    has_nav: bool,
    has_13f_overlay: bool = False,
    has_prospectus: bool = False,
    fund_type: str | None = None,
) -> DisclosureMatrix:
    """Build DisclosureMatrix from universe type and computed flags."""
    if fund_type == "money_market":
        return DisclosureMatrix(
            has_holdings=False,
            has_nav_history=False,
            has_quant_metrics=False,
            has_fund_details=True,
            has_style_analysis=False,
            has_13f_overlay=False,
            has_peer_analysis=True,
            holdings_source=None,
            nav_source=None,
            aum_source="nport",
        )
    if universe == "registered_us":
        return DisclosureMatrix(
            has_holdings=has_holdings,
            has_nav_history=has_nav,
            has_quant_metrics=has_nav,
            has_fund_details=has_prospectus,
            has_style_analysis=has_holdings,
            has_13f_overlay=has_13f_overlay,
            has_peer_analysis=True,
            holdings_source="nport" if has_holdings else None,
            nav_source="yfinance" if has_nav else None,
            aum_source="nport",
        )
    if universe == "private_us":
        return DisclosureMatrix(
            has_holdings=False,
            has_nav_history=False,
            has_quant_metrics=False,
            has_fund_details=True,
            has_style_analysis=False,
            has_13f_overlay=has_13f_overlay,
            has_peer_analysis=False,
            holdings_source=None,
            nav_source=None,
            aum_source="schedule_d",
        )
    # ucits_eu
    return DisclosureMatrix(
        has_holdings=False,
        has_nav_history=has_nav,
        has_quant_metrics=has_nav,
        has_fund_details=False,
        has_style_analysis=False,
        has_13f_overlay=False,
        has_peer_analysis=has_nav,
        holdings_source=None,
        nav_source="yfinance" if has_nav else None,
        aum_source="yfinance" if has_nav else None,
    )


# ── Global Securities Discovery (Mandate 1: no RLS, no instruments_universe) ──


class SecurityItem(BaseModel):
    """A tradeable security from the global SEC CUSIP/ticker map."""

    cusip: str
    ticker: str | None = None
    name: str
    security_type: str
    exchange: str | None = None
    asset_class: str  # equity | real_estate
    figi: str | None = None
    is_tradeable: bool = True


class SecurityPage(BaseModel):
    items: list[SecurityItem]
    total: int
    page: int
    page_size: int
    has_next: bool


class SecurityFacets(BaseModel):
    security_types: list[FacetItem] = []
    exchanges: list[FacetItem] = []
    total: int = 0


@router.get(
    "/securities",
    response_model=SecurityPage,
    summary="Global equity/ETF discovery from SEC CUSIP map (no RLS)",
)
@route_cache(ttl=120, key_prefix="screener:securities", global_key=True)
async def get_global_securities(
    q: str | None = Query(None, description="Search by name, ticker, or CUSIP"),
    security_type: str | None = Query(
        None, description="Common Stock, ETP, ADR, REIT, MLP, Closed-End Fund",
    ),
    exchange: str | None = Query(None, description="NYSE, NASDAQ, etc."),
    asset_class: str | None = Query(
        None, description="equity or real_estate",
    ),
    sort: str = Query("name_asc", description="name_asc | name_desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_with_rls),
) -> SecurityPage:
    """Query sec_cusip_ticker_map directly — global, no tenant filter.

    This is the correct screener endpoint for equity/ETF discovery.
    instruments_universe (RLS) is the DESTINATION, not the source.
    """
    ac_case = case(
        (SecCusipTickerMap.security_type == "REIT", literal("real_estate")),
        else_=literal("equity"),
    )

    stmt = (
        select(
            SecCusipTickerMap.cusip,
            SecCusipTickerMap.ticker,
            SecCusipTickerMap.issuer_name.label("name"),
            SecCusipTickerMap.security_type,
            SecCusipTickerMap.exchange,
            ac_case.label("asset_class"),
            SecCusipTickerMap.figi,
            SecCusipTickerMap.is_tradeable,
            sa_func.count().over().label("_total"),
        )
        .where(SecCusipTickerMap.is_tradeable.is_(True))
    )

    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            SecCusipTickerMap.issuer_name.ilike(pattern)
            | SecCusipTickerMap.ticker.ilike(pattern)
            | (SecCusipTickerMap.cusip == q.upper()),
        )
    if security_type:
        stmt = stmt.where(SecCusipTickerMap.security_type == security_type)
    if exchange:
        stmt = stmt.where(SecCusipTickerMap.exchange == exchange)
    if asset_class:
        stmt = stmt.where(ac_case == asset_class)

    order = SecCusipTickerMap.issuer_name.asc() if sort == "name_asc" else SecCusipTickerMap.issuer_name.desc()
    offset = (page - 1) * page_size
    stmt = stmt.order_by(order).offset(offset).limit(page_size)

    rows = (await db.execute(stmt)).all()
    total = rows[0]._total if rows else 0

    items = [
        SecurityItem(
            cusip=r.cusip,
            ticker=r.ticker,
            name=r.name or "",
            security_type=r.security_type or "unknown",
            exchange=r.exchange,
            asset_class=r.asset_class,
            figi=r.figi,
            is_tradeable=r.is_tradeable,
        )
        for r in rows
    ]

    return SecurityPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_next=(offset + page_size) < total,
    )


@router.get(
    "/securities/facets",
    response_model=SecurityFacets,
    summary="Facet counts for global securities",
)
@route_cache(ttl=300, key_prefix="screener:securities:facets", global_key=True)
async def get_securities_facets(
    q: str | None = Query(None),
    db: AsyncSession = Depends(get_db_with_rls),
) -> SecurityFacets:
    stmt = (
        select(
            SecCusipTickerMap.security_type,
            SecCusipTickerMap.exchange,
            sa_func.count().label("cnt"),
        )
        .where(SecCusipTickerMap.is_tradeable.is_(True))
        .group_by(SecCusipTickerMap.security_type, SecCusipTickerMap.exchange)
    )
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            SecCusipTickerMap.issuer_name.ilike(pattern)
            | SecCusipTickerMap.ticker.ilike(pattern),
        )

    rows = (await db.execute(stmt)).all()

    type_counts: dict[str, int] = {}
    exchange_counts: dict[str, int] = {}
    grand_total = 0

    for r in rows:
        cnt = r.cnt
        grand_total += cnt
        st = r.security_type or "unknown"
        type_counts[st] = type_counts.get(st, 0) + cnt
        ex = r.exchange or "Other"
        exchange_counts[ex] = exchange_counts.get(ex, 0) + cnt

    def to_facets(counts: dict[str, int]) -> list[FacetItem]:
        return sorted(
            [FacetItem(value=k, label=k, count=v) for k, v in counts.items() if v > 0],
            key=lambda f: -f.count,
        )

    return SecurityFacets(
        security_types=to_facets(type_counts),
        exchanges=to_facets(exchange_counts),
        total=grand_total,
    )


@router.get(
    "/catalog",
    response_model=UnifiedCatalogPage,
    summary="Unified fund catalog across US registered, US private, and EU UCITS",
)
@route_cache(ttl=120, key_prefix="screener:catalog", global_key=True)
async def get_catalog(
    q: str | None = Query(None, description="Text search (name, ticker, ISIN, manager)"),
    region: str | None = Query(None, description="US or EU"),
    fund_universe: str | None = Query(None, description="Comma-separated categories: mutual_fund,etf,closed_end,bdc,hedge_fund,private_fund,ucits"),
    fund_type: str | None = Query(None, description="Additional fund_type filter within universe"),
    strategy_label: str | None = Query(None, description="Comma-separated strategy labels"),
    investment_geography: str | None = Query(None, description="Comma-separated: US,Europe,Emerging Markets,Asia Pacific,Global,Latin America"),
    aum_min: float | None = Query(None, ge=0, description="Minimum AUM in USD"),
    has_nav: bool | None = Query(None, description="Only funds with NAV history (ticker)"),
    has_aum: bool | None = Query(None, description="Only funds with AUM > 0"),
    domicile: str | None = Query(None),
    manager: str | None = Query(None, description="Manager name text search"),
    sort: str = Query("name_asc", description="name_asc | name_desc | aum_desc | aum_asc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    max_expense_ratio: float | None = Query(None, ge=0, le=10, description="Max expense ratio %"),
    min_return_1y: float | None = Query(None, description="Min avg annual return 1Y %"),
    min_return_10y: float | None = Query(None, description="Min avg annual return 10Y %"),
    db: AsyncSession = Depends(get_db_with_rls),
) -> UnifiedCatalogPage:
    filters = CatalogFilters(
        q=q,
        region=region,
        fund_universe=fund_universe,
        fund_type=fund_type,
        strategy_label=strategy_label,
        investment_geography=investment_geography,
        aum_min=aum_min,
        has_nav=has_nav,
        has_aum=has_aum,
        domicile=domicile,
        manager=manager,
        sort=sort,
        page=page,
        page_size=page_size,
        max_expense_ratio=max_expense_ratio,
        min_return_1y=min_return_1y,
        min_return_10y=min_return_10y,
    )

    stmt = build_catalog_query(filters)
    if stmt is None:
        return UnifiedCatalogPage(
            items=[], total=0, page=page, page_size=page_size, has_next=False,
        )

    rows = (await db.execute(stmt)).all()

    total = rows[0]._total if rows else 0
    offset = (page - 1) * page_size

    items: list[UnifiedFundItem] = []
    for r in rows:
        aum_val: float | None = None
        if r.aum is not None:
            try:
                aum_val = float(r.aum)
            except (ValueError, TypeError):
                pass

        inception: str | None = None
        if r.inception_date is not None:
            try:
                inception = r.inception_date
            except (ValueError, TypeError):
                pass

        items.append(
            UnifiedFundItem(
                external_id=str(r.external_id),
                universe=r.universe,
                name=r.name or "",
                ticker=r.ticker,
                isin=r.isin,
                series_id=getattr(r, "series_id", None),
                series_name=getattr(r, "series_name", None),
                class_id=getattr(r, "class_id", None),
                class_name=getattr(r, "class_name", None),
                region=r.region,
                fund_type=r.fund_type or "unknown",
                strategy_label=getattr(r, "strategy_label", None),
                investment_geography=getattr(r, "investment_geography", None),
                domicile=r.domicile,
                currency=r.currency,
                manager_name=r.manager_name,
                manager_id=r.manager_id,
                aum=aum_val,
                inception_date=inception,
                total_shareholder_accounts=r.total_shareholder_accounts,
                investor_count=r.investor_count,
                vintage_year=getattr(r, "vintage_year", None),
                expense_ratio_pct=float(r.expense_ratio_pct) if getattr(r, "expense_ratio_pct", None) is not None else None,
                avg_annual_return_1y=float(r.avg_annual_return_1y) if getattr(r, "avg_annual_return_1y", None) is not None else None,
                avg_annual_return_10y=float(r.avg_annual_return_10y) if getattr(r, "avg_annual_return_10y", None) is not None else None,
                is_index=bool(r.is_index) if getattr(r, "is_index", None) is not None else None,
                is_target_date=bool(r.is_target_date) if getattr(r, "is_target_date", None) is not None else None,
                is_fund_of_fund=bool(r.is_fund_of_fund) if getattr(r, "is_fund_of_fund", None) is not None else None,
                disclosure=_build_disclosure(
                    universe=r.universe,
                    has_holdings=bool(r.has_holdings),
                    has_nav=bool(r.has_nav),
                    has_13f_overlay=bool(getattr(r, "has_13f_overlay", False)),
                    has_prospectus=(
                        getattr(r, "expense_ratio_pct", None) is not None
                        or getattr(r, "avg_annual_return_1y", None) is not None
                    ),
                    fund_type=r.fund_type,
                ),
            ),
        )

    # Batch-enrich MMF items with money market specific fields
    mmf_ext_ids = [item.external_id for item in items if item.fund_type == "money_market"]
    if mmf_ext_ids:
        mmf_result = await db.execute(
            select(
                sec_money_market_funds.c.series_id,
                sec_money_market_funds.c.mmf_category,
                sec_money_market_funds.c.seven_day_gross_yield,
                sec_money_market_funds.c.weighted_avg_maturity,
                sec_money_market_funds.c.weighted_avg_life,
            ).where(sec_money_market_funds.c.series_id.in_(mmf_ext_ids))
        )
        mmf_map = {r.series_id: r for r in mmf_result.all()}
        for item in items:
            if item.fund_type == "money_market" and item.external_id in mmf_map:
                mmf = mmf_map[item.external_id]
                item.mmf_category = mmf.mmf_category
                item.seven_day_gross_yield = (
                    float(mmf.seven_day_gross_yield)
                    if mmf.seven_day_gross_yield is not None
                    else None
                )
                item.weighted_avg_maturity = mmf.weighted_avg_maturity
                item.weighted_avg_life = mmf.weighted_avg_life

    # Batch-enrich nav_status — check which tickers are already imported
    tickers_to_check = [
        item.ticker for item in items if item.ticker and item.disclosure.has_nav_history
    ]
    imported_tickers: set[str] = set()
    if tickers_to_check:
        nav_result = await db.execute(
            select(Instrument.ticker)
            .where(Instrument.ticker.in_(tickers_to_check))
            .where(Instrument.is_active == True)  # noqa: E712
        )
        imported_tickers = {r[0] for r in nav_result.all()}

    for item in items:
        if not item.disclosure.has_nav_history:
            item.disclosure.nav_status = "unavailable"
        elif item.ticker and item.ticker in imported_tickers:
            item.disclosure.nav_status = "available"
        elif item.ticker:
            item.disclosure.nav_status = "pending_import"
        else:
            item.disclosure.nav_status = "unavailable"

    return UnifiedCatalogPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_next=(offset + page_size) < total,
    )


@router.get(
    "/catalog/facets",
    response_model=CatalogFacets,
    summary="Facet counts for the unified fund catalog filters",
)
@route_cache(ttl=300, key_prefix="screener:catalog:facets", global_key=True)
async def get_catalog_facets(
    q: str | None = Query(None),
    region: str | None = Query(None),
    fund_universe: str | None = Query(None),
    fund_type: str | None = Query(None),
    strategy_label: str | None = Query(None),
    investment_geography: str | None = Query(None),
    aum_min: float | None = Query(None, ge=0),
    has_nav: bool | None = Query(None),
    has_aum: bool | None = Query(None),
    domicile: str | None = Query(None),
    manager: str | None = Query(None),
    db: AsyncSession = Depends(get_db_with_rls),
) -> CatalogFacets:
    filters = CatalogFilters(
        q=q,
        region=region,
        fund_universe=fund_universe,
        fund_type=fund_type,
        strategy_label=strategy_label,
        investment_geography=investment_geography,
        aum_min=aum_min,
        has_nav=has_nav,
        has_aum=has_aum,
        domicile=domicile,
        manager=manager,
    )

    stmt = build_catalog_facets_query(filters)
    if stmt is None:
        return CatalogFacets(total=0)

    rows = (await db.execute(stmt)).all()

    universe_counts: dict[str, int] = {}
    region_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    strategy_counts: dict[str, int] = {}
    domicile_counts: dict[str, int] = {}
    geography_counts: dict[str, int] = {}
    grand_total = 0

    for r in rows:
        cnt = r.cnt
        grand_total += cnt

        u = r.universe or "unknown"
        universe_counts[u] = universe_counts.get(u, 0) + cnt

        reg = r.region or "unknown"
        region_counts[reg] = region_counts.get(reg, 0) + cnt

        ft = r.fund_type or "unknown"
        type_counts[ft] = type_counts.get(ft, 0) + cnt

        sl = r.strategy_label
        if sl:
            strategy_counts[sl] = strategy_counts.get(sl, 0) + cnt

        dom = r.domicile
        if dom:
            domicile_counts[dom] = domicile_counts.get(dom, 0) + cnt

        geo = getattr(r, "investment_geography", None)
        if geo:
            geography_counts[geo] = geography_counts.get(geo, 0) + cnt

    _UNIVERSE_LABELS = {
        "registered_us": "US Registered",
        "private_us": "US Private",
        "ucits_eu": "EU UCITS",
    }

    def to_facets(counts: dict[str, int], labels: dict[str, str] | None = None) -> list[CatalogFacetItem]:
        return sorted(
            [
                CatalogFacetItem(
                    value=k,
                    label=(labels or {}).get(k, k),
                    count=v,
                )
                for k, v in counts.items()
                if v > 0
            ],
            key=lambda f: -f.count,
        )

    return CatalogFacets(
        universes=to_facets(universe_counts, _UNIVERSE_LABELS),
        regions=to_facets(region_counts),
        fund_types=to_facets(type_counts),
        strategy_labels=to_facets(strategy_counts),
        geographies=to_facets(geography_counts),
        domiciles=to_facets(domicile_counts),
        total=grand_total,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Fund detail — enriched single-fund lookup by external_id
# ═══════════════════════════════════════════════════════════════════════════


class FundDetailOut(UnifiedFundItem):
    """Extended fund detail (superset of UnifiedFundItem)."""
    pass


@router.get(
    "/catalog/{external_id}/detail",
    response_model=FundDetailOut,
    summary="Enriched fund detail by external_id",
)
async def get_catalog_fund_detail(
    external_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
) -> FundDetailOut:
    """Return a single fund's enriched detail from the catalog.

    Queries all 5 branches (registered_us, ETF, BDC, private, UCITS) with
    external_id filter to find the matching fund. Returns the same schema
    as catalog items but with all fee/performance/N-CEN fields populated.
    """
    from app.domains.wealth.queries.catalog_sql import build_catalog_query

    # Build catalog query filtering by exact external_id
    filters = CatalogFilters(external_id=external_id, page=1, page_size=1, has_nav=None)
    stmt = build_catalog_query(filters)
    if stmt is None:
        raise HTTPException(status_code=404, detail="Fund not found")

    rows = (await db.execute(stmt)).all()

    if not rows:
        raise HTTPException(status_code=404, detail="Fund not found")

    r = rows[0]
    aum_val = float(r.aum) if r.aum is not None else None

    detail = FundDetailOut(
        external_id=str(r.external_id),
        universe=r.universe,
        name=r.name or "",
        ticker=r.ticker,
        isin=r.isin,
        series_id=getattr(r, "series_id", None),
        series_name=getattr(r, "series_name", None),
        class_id=getattr(r, "class_id", None),
        class_name=getattr(r, "class_name", None),
        region=r.region,
        fund_type=r.fund_type or "unknown",
        strategy_label=getattr(r, "strategy_label", None),
        investment_geography=getattr(r, "investment_geography", None),
        domicile=r.domicile,
        currency=r.currency,
        manager_name=r.manager_name,
        manager_id=r.manager_id,
        aum=aum_val,
        inception_date=r.inception_date,
        total_shareholder_accounts=r.total_shareholder_accounts,
        investor_count=r.investor_count,
        vintage_year=getattr(r, "vintage_year", None),
        expense_ratio_pct=float(r.expense_ratio_pct) if getattr(r, "expense_ratio_pct", None) is not None else None,
        avg_annual_return_1y=float(r.avg_annual_return_1y) if getattr(r, "avg_annual_return_1y", None) is not None else None,
        avg_annual_return_10y=float(r.avg_annual_return_10y) if getattr(r, "avg_annual_return_10y", None) is not None else None,
        is_index=bool(r.is_index) if getattr(r, "is_index", None) is not None else None,
        is_target_date=bool(r.is_target_date) if getattr(r, "is_target_date", None) is not None else None,
        is_fund_of_fund=bool(r.is_fund_of_fund) if getattr(r, "is_fund_of_fund", None) is not None else None,
        disclosure=_build_disclosure(
            universe=r.universe,
            has_holdings=bool(r.has_holdings),
            has_nav=bool(r.has_nav),
            has_13f_overlay=bool(getattr(r, "has_13f_overlay", False)),
            has_prospectus=(
                getattr(r, "expense_ratio_pct", None) is not None
                or getattr(r, "avg_annual_return_1y", None) is not None
            ),
            fund_type=r.fund_type,
        ),
    )

    # Enrich nav_status for detail route
    if detail.disclosure.has_nav_history and detail.ticker:
        nav_check = await db.execute(
            select(Instrument.ticker)
            .where(Instrument.ticker == detail.ticker)
            .where(Instrument.is_active == True)  # noqa: E712
            .limit(1)
        )
        if nav_check.scalar_one_or_none():
            detail.disclosure.nav_status = "available"
        else:
            detail.disclosure.nav_status = "pending_import"

    return detail


@router.get(
    "/catalog/{external_id}/fact-sheet",
    response_model=FundFactSheet,
    summary="Comprehensive fact-sheet data for a single fund",
)
async def get_fund_fact_sheet(
    external_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
) -> FundFactSheet:
    """Return comprehensive data for a fund fact sheet.

    Aggregates:
    - Base catalog detail (identity, fees, N-CEN)
    - Management team (ADV Part 2B)
    - Top 50 holdings (N-PORT)
    - Annual return history (RR1)
    - NAV history chart data (nav_timeseries)
    """
    # 1. Get base detail (reuses existing logic)
    detail = await get_catalog_fund_detail(external_id, db)

    # 2. Gather additional evidence via sync thread (orchestrates complex global SEC joins)
    from app.core.db.session import sync_session_factory
    from vertical_engines.wealth.dd_report.sec_injection import (
        gather_fund_enrichment,
        gather_nport_sector_history,
        gather_prospectus_returns,
        gather_prospectus_stats,
        gather_sec_adv_data,
        gather_sec_nport_data,
    )

    def _resolve_cik(sync_db: Any) -> str | None:
        """Resolve fund CIK from external_id (which may be class_id, series_id, or CIK)."""
        if detail.universe != "registered_us":
            return None
        ext = detail.external_id
        from app.shared.models import SecFundClass, SecRegisteredFund
        # 1. Try as class_id → CIK
        row = sync_db.query(SecFundClass.cik).filter(SecFundClass.class_id == ext).first()
        if row:
            return str(row[0])
        # 2. Try as series_id → CIK
        row = sync_db.query(SecFundClass.cik).filter(SecFundClass.series_id == ext).first()
        if row:
            return str(row[0])
        # 3. Try as CIK directly
        row = sync_db.query(SecRegisteredFund.cik).filter(SecRegisteredFund.cik == ext).first()
        if row:
            return str(row[0])
        return None

    def _gather_evidence():
        with sync_session_factory() as sync_db:
            # Resolve actual fund CIK from external_id (may be class_id or series_id)
            fund_cik = _resolve_cik(sync_db)
            manager_name = detail.manager_name

            # Fix: resolver CRD diretamente de sec_registered_funds — não confiar no manager_id da MV
            # mv_unified_funds.manager_id pode ser NULL se o join a sec_managers foi filtrado
            crd_from_db: str | None = None
            if fund_cik:
                from app.shared.models import SecRegisteredFund
                crd_row = (
                    sync_db.query(SecRegisteredFund.crd_number)
                    .filter(
                        SecRegisteredFund.cik == fund_cik,
                        SecRegisteredFund.crd_number.isnot(None),
                    )
                    .first()
                )
                if crd_row:
                    crd_from_db = crd_row[0]

            # CRD do DB tem prioridade; manager_id da MV é fallback
            effective_crd = crd_from_db or detail.manager_id

            # Team and Manager profile
            adv_data = gather_sec_adv_data(sync_db, manager_name=manager_name, crd_number=effective_crd)

            # Holdings (N-PORT) — increase limit to 50
            nport_data = gather_sec_nport_data(sync_db, fund_cik=fund_cik, holdings_limit=50)
            sector_history = gather_nport_sector_history(sync_db, fund_cik=fund_cik)

            # Fix: resolver series_id a partir do external_id (que pode ser um class_id)
            # quando a MV não tiver populado series_id corretamente
            correct_series_id = detail.series_id
            if not correct_series_id and fund_cik and detail.external_id:
                from app.shared.models import SecFundClass
                fc_row = (
                    sync_db.query(SecFundClass.series_id)
                    .filter(SecFundClass.class_id == detail.external_id)
                    .first()
                )
                if fc_row:
                    correct_series_id = fc_row[0]

            # Returns and Stats (pass series_id when available for direct lookup)
            prop_stats = gather_prospectus_stats(sync_db, fund_cik=fund_cik, series_id=correct_series_id)
            prop_returns = gather_prospectus_returns(sync_db, fund_cik=fund_cik, series_id=correct_series_id)
            
            # Enrichment (Classes)
            enrichment = gather_fund_enrichment(sync_db, fund_cik=fund_cik, sec_universe=detail.universe)
            
            return {
                "adv": adv_data,
                "nport": nport_data,
                "sector_history": sector_history,
                "stats": prop_stats,
                "returns": prop_returns,
                "enrichment": enrichment,
            }

    evidence = await asyncio.to_thread(_gather_evidence)

    # 3. Gather NAV History and Risk Metrics (Async)
    nav_history: list[NavPoint] = []
    scoring_metrics: dict[str, Any] | None = None
    
    # Find instrument_id if not already in detail
    inst_id = detail.instrument_id
    if not inst_id and detail.ticker:
        res = await db.execute(
            select(Instrument.instrument_id).where(Instrument.ticker == detail.ticker).limit(1)
        )
        inst_id = res.scalar_one_or_none()

    if inst_id:
        from app.domains.wealth.models.nav import NavTimeseries
        from app.domains.wealth.models.risk import FundRiskMetrics
        
        # NAV History
        if detail.ticker and detail.disclosure.nav_status == "available":
            nav_res = await db.execute(
                select(NavTimeseries.nav_date, NavTimeseries.nav)
                .where(NavTimeseries.instrument_id == inst_id)
                .order_by(NavTimeseries.nav_date.asc())
                .limit(1000)
            )
            nav_history = [NavPoint(nav_date=r.nav_date, nav=float(r.nav)) for r in nav_res.all()]
            
        # Risk Metrics / Scoring
        metrics_res = await db.execute(
            select(FundRiskMetrics).where(FundRiskMetrics.instrument_id == inst_id).limit(1)
        )
        m = metrics_res.scalar_one_or_none()
        if m:
            scoring_metrics = {
                "manager_score": m.manager_score,
                "score_components": m.score_components,
                "peer_percentiles": {
                    "sharpe": m.peer_sharpe_pctl,
                    "sortino": m.peer_sortino_pctl,
                    "return": m.peer_return_pctl,
                    "drawdown": m.peer_drawdown_pctl,
                },
                "peer_count": m.peer_count,
                "peer_strategy": m.peer_strategy_label,
            }

    # 4. Map evidence to Fact Sheet schema
    adv = evidence["adv"]
    nport = evidence["nport"]
    enrichment = evidence["enrichment"]

    team = [
        TeamMember(
            person_name=t["person_name"],
            title=t["title"],
            role=t["role"],
            education=t["education"],
            certifications=t["certifications"],
            years_experience=t["years_experience"],
            bio_summary=t["bio_summary"],
        )
        for t in adv.get("adv_team", [])
    ]

    holdings = [
        FundHolding(
            name=h["name"],
            cusip=h["cusip"],
            sector=h["sector"],
            pct_of_nav=h["pct_of_nav"],
            market_value=float(h["market_value"]) if h.get("market_value") else None,
        )
        for h in nport.get("top_holdings", [])[:50]
    ]

    return FundFactSheet(
        fund=detail,
        team=team,
        top_holdings=holdings,
        annual_returns=evidence["returns"],
        nav_history=nav_history,
        sector_history=evidence["sector_history"],
        prospectus_stats=evidence["stats"],
        share_classes=enrichment.get("share_classes", []),
        scoring_metrics=scoring_metrics,
    )
