"""DEPRECATED: Fund CRUD routes — kept for backward compatibility.

The Fund model is being replaced by the Instrument model
(instruments_universe table). These routes remain functional
but new code should use the Instrument equivalents.
"""

import uuid
from datetime import date

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.config_service import ConfigService
from app.core.config.dependencies import get_config_service
from app.core.config.settings import settings
from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.models.fund import Fund
from app.domains.wealth.models.nav import NavTimeseries
from app.domains.wealth.models.risk import FundRiskMetrics
from app.domains.wealth.schemas.fund import FundRead, NavPoint
from app.domains.wealth.schemas.risk import FundRiskRead, FundScoreRead
from quant_engine.scoring_service import compute_fund_score
from quant_engine.talib_momentum_service import (
    compute_flow_momentum,
    compute_momentum_signals_talib,
    normalize_flow_momentum,
)

router = APIRouter(prefix="/funds")


# IMPORTANT: /scoring must be defined BEFORE /{fund_id} to avoid path shadowing
@router.get(
    "/scoring",
    response_model=list[FundScoreRead],
    summary="Fund scoring within block",
    description="Returns funds ranked by manager score within an allocation block.",
)
async def get_fund_scoring(
    block: str = Query(..., description="Allocation block ID"),
    top_n: int = Query(10, ge=1, le=100, description="Number of top funds to return"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    config_service: ConfigService = Depends(get_config_service),
    actor: Actor = Depends(get_actor),
) -> list[FundScoreRead]:
    # Batch-fetch funds and their latest risk metrics in two queries (no N+1)
    funds_stmt = select(Fund).where(Fund.block_id == block, Fund.is_active == True)
    funds_result = await db.execute(funds_stmt)
    funds = funds_result.scalars().all()

    if not funds:
        return []

    fund_ids = [f.fund_id for f in funds]
    _ = {f.fund_id: f for f in funds}  # noqa: F841 — kept for future use

    # Fetch latest risk metrics for all funds in one query using DISTINCT ON
    risk_stmt = (
        select(FundRiskMetrics)
        .where(FundRiskMetrics.instrument_id.in_(fund_ids))
        .order_by(FundRiskMetrics.instrument_id, FundRiskMetrics.calc_date.desc())
        .distinct(FundRiskMetrics.instrument_id)
    )
    risk_result = await db.execute(risk_stmt)
    risk_map = {r.instrument_id: r for r in risk_result.scalars().all()}

    # Pre-fetch NAV data for momentum computation when flag is enabled.
    # Uses a ROW_NUMBER() window function subquery to fetch at most 50 rows
    # per fund at the DB level — avoids full history scan for each fund.
    NAV_MOMENTUM_WINDOW = 50
    momentum_map: dict[uuid.UUID, float] = {}
    if settings.feature_momentum_signals:
        # Subquery: rank rows within each fund by nav_date DESC
        ranked_subq = (
            select(
                NavTimeseries,
                func.row_number()
                .over(
                    partition_by=NavTimeseries.instrument_id,
                    order_by=NavTimeseries.nav_date.desc(),
                )
                .label("rn"),
            )
            .where(
                NavTimeseries.instrument_id.in_(fund_ids),
                NavTimeseries.nav.isnot(None),
            )
            .subquery()
        )
        nav_stmt = (
            select(NavTimeseries)
            .join(
                ranked_subq,
                (NavTimeseries.instrument_id == ranked_subq.c.instrument_id)
                & (NavTimeseries.nav_date == ranked_subq.c.nav_date),
            )
            .where(ranked_subq.c.rn <= NAV_MOMENTUM_WINDOW)
            .order_by(NavTimeseries.instrument_id, NavTimeseries.nav_date.desc())
        )
        nav_result = await db.execute(nav_stmt)
        nav_rows = nav_result.scalars().all()

        # Group NAV rows by fund_id (already desc; reverse to get chronological order)
        nav_by_fund: dict[uuid.UUID, list] = {}
        for row in nav_rows:
            nav_by_fund.setdefault(row.instrument_id, []).append(row)

        for fid, rows in nav_by_fund.items():
            rows_asc = list(reversed(rows))  # already limited to 50 at DB level; restore chronological order
            close = np.array([float(r.nav) for r in rows_asc])
            signals = compute_momentum_signals_talib(close)
            nav_score = signals["momentum_score"]

            # Blend with OBV flow momentum when net flow data is available
            net_flows = np.array(
                [float(r.aum_usd) if r.aum_usd is not None else 0.0 for r in rows_asc]
            )
            if net_flows.any():
                slope = compute_flow_momentum(close, net_flows)
                flow_score = normalize_flow_momentum(slope)
                # Equal-weight blend: 50% price momentum + 50% flow momentum
                momentum_map[fid] = round(0.5 * nav_score + 0.5 * flow_score, 2)
            else:
                momentum_map[fid] = nav_score

    scoring_result = await config_service.get("liquid_funds", "scoring", actor.organization_id)
    scoring_config = scoring_result.value

    scored: list[FundScoreRead] = []
    for fund in funds:
        risk = risk_map.get(fund.fund_id)
        flows_momentum_score = momentum_map.get(fund.fund_id, 50.0)
        if risk is not None:
            score_val, components = compute_fund_score(
                risk, flows_momentum_score=flows_momentum_score, config=scoring_config
            )
        else:
            score_val, components = 50.0, {}
        scored.append(
            FundScoreRead(
                fund_id=fund.fund_id,
                name=fund.name,
                ticker=fund.ticker,
                manager_score=score_val if risk else None,
                score_components=components if risk else None,
                cvar_95_3m=risk.cvar_95_3m if risk else None,
                sharpe_1y=risk.sharpe_1y if risk else None,
                return_1y=risk.return_1y if risk else None,
            )
        )

    scored.sort(key=lambda s: s.manager_score or 0, reverse=True)
    return scored[:top_n]


@router.get(
    "",
    response_model=list[FundRead],
    summary="List fund universe",
    description="Returns funds with optional filters by block, geography, asset class.",
)
async def list_funds(
    block_id: str | None = Query(None, description="Filter by allocation block"),
    geography: str | None = Query(None, description="Filter by geography"),
    asset_class: str | None = Query(None, description="Filter by asset class"),
    is_active: bool | None = Query(True, description="Filter by active status"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[FundRead]:
    stmt = select(Fund)
    if block_id is not None:
        stmt = stmt.where(Fund.block_id == block_id)
    if geography is not None:
        stmt = stmt.where(Fund.geography == geography)
    if asset_class is not None:
        stmt = stmt.where(Fund.asset_class == asset_class)
    if is_active is not None:
        stmt = stmt.where(Fund.is_active == is_active)
    stmt = stmt.order_by(Fund.name).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return [FundRead.model_validate(row) for row in result.scalars().all()]


@router.get(
    "/{fund_id}",
    response_model=FundRead,
    summary="Fund detail",
    description="Returns full metadata for a single fund.",
)
async def get_fund(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> FundRead:
    result = await db.execute(select(Fund).where(Fund.fund_id == fund_id))
    fund = result.scalar_one_or_none()
    if fund is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fund not found")
    return FundRead.model_validate(fund)


@router.get(
    "/{fund_id}/risk",
    response_model=FundRiskRead | None,
    summary="Fund risk metrics",
    description="Returns the latest risk metrics (CVaR, VaR, returns, ratios) for a fund.",
)
async def get_fund_risk(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> FundRiskRead | None:
    stmt = (
        select(FundRiskMetrics)
        .where(FundRiskMetrics.instrument_id == fund_id)
        .order_by(FundRiskMetrics.calc_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return FundRiskRead.model_validate(row)


@router.get(
    "/{fund_id}/nav",
    response_model=list[NavPoint],
    summary="Fund NAV time-series",
    description="Returns NAV history for a fund within a date range.",
)
async def get_fund_nav(
    fund_id: uuid.UUID,
    from_date: date | None = Query(None, alias="from", description="Start date"),
    to_date: date | None = Query(None, alias="to", description="End date"),
    limit: int = Query(1000, ge=1, le=10000, description="Max rows to return"),
    offset: int = Query(0, ge=0, description="Rows to skip"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[NavPoint]:
    stmt = select(NavTimeseries).where(NavTimeseries.instrument_id == fund_id)
    if from_date is not None:
        stmt = stmt.where(NavTimeseries.nav_date >= from_date)
    if to_date is not None:
        stmt = stmt.where(NavTimeseries.nav_date <= to_date)
    stmt = stmt.order_by(NavTimeseries.nav_date).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return [NavPoint.model_validate(row) for row in result.scalars().all()]
