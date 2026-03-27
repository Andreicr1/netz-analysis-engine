"""DEPRECATED: Fund CRUD routes — kept for backward compatibility.

The Fund model is being replaced by the Instrument model
(instruments_universe table). These routes remain functional
but new code should use the Instrument equivalents.

All responses include a ``Deprecation`` header (RFC 8594) and
``Sunset`` header pointing clients to the /instruments endpoints.
See SR-4 audit finding.
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.config_service import ConfigService
from app.core.config.dependencies import get_config_service
from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.models.fund import Fund
from app.domains.wealth.models.nav import NavTimeseries
from app.domains.wealth.models.risk import FundRiskMetrics
from app.domains.wealth.schemas.fund import FundRead, NavPoint
from app.domains.wealth.schemas.risk import FundRiskRead, FundScoreRead
from quant_engine.scoring_service import compute_fund_score

router = APIRouter(prefix="/funds", tags=["funds (deprecated)"])

# ---------------------------------------------------------------------------
# Deprecation helpers (SR-4 audit finding)
# ---------------------------------------------------------------------------
_DEPRECATION_HEADERS = {
    "Deprecation": "true",
    "Sunset": "2026-06-30",
    "Link": '</api/v1/instruments>; rel="successor-version"',
}


def _set_deprecation_headers(response: Response) -> None:
    """Inject RFC 8594 Deprecation + Sunset headers into the response."""
    for key, value in _DEPRECATION_HEADERS.items():
        response.headers[key] = value


# IMPORTANT: /scoring must be defined BEFORE /{fund_id} to avoid path shadowing
@router.get(
    "/scoring",
    response_model=list[FundScoreRead],
    summary="[DEPRECATED] Fund scoring within block",
    description="DEPRECATED — use /instruments endpoints instead. "
    "Returns funds ranked by manager score within an allocation block.",
    deprecated=True,
)
async def get_fund_scoring(
    response: Response,
    block: str = Query(..., description="Allocation block ID"),
    top_n: int = Query(10, ge=1, le=100, description="Number of top funds to return"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    config_service: ConfigService = Depends(get_config_service),
    actor: Actor = Depends(get_actor),
) -> list[FundScoreRead]:
    _set_deprecation_headers(response)
    # Batch-fetch funds and their latest risk metrics in two queries (no N+1)
    funds_stmt = select(Fund).where(Fund.block_id == block, Fund.is_active == True)
    funds_result = await db.execute(funds_stmt)
    funds = funds_result.scalars().all()

    if not funds:
        return []

    fund_ids = [f.fund_id for f in funds]
    _ = {f.fund_id: f for f in funds}

    # Fetch latest risk metrics for all funds in one query using DISTINCT ON
    risk_stmt = (
        select(FundRiskMetrics)
        .where(FundRiskMetrics.instrument_id.in_(fund_ids))
        .order_by(FundRiskMetrics.instrument_id, FundRiskMetrics.calc_date.desc())
        .distinct(FundRiskMetrics.instrument_id)
    )
    risk_result = await db.execute(risk_stmt)
    risk_map = {r.instrument_id: r for r in risk_result.scalars().all()}

    # Momentum is pre-computed by risk_calc worker — read from FundRiskMetrics
    scoring_result = await config_service.get("liquid_funds", "scoring", actor.organization_id)
    scoring_config = scoring_result.value

    scored: list[FundScoreRead] = []
    for fund in funds:
        risk = risk_map.get(fund.fund_id)
        flows_momentum_score = (
            float(risk.blended_momentum_score)
            if risk and risk.blended_momentum_score is not None
            else 50.0
        )
        if risk is not None:
            score_val, components = compute_fund_score(
                risk, flows_momentum_score=flows_momentum_score, config=scoring_config,
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
            ),
        )

    scored.sort(key=lambda s: s.manager_score or 0, reverse=True)
    return scored[:top_n]


@router.get(
    "",
    response_model=list[FundRead],
    summary="[DEPRECATED] List fund universe",
    description="DEPRECATED — use GET /instruments instead. "
    "Returns funds with optional filters by block, geography, asset class.",
    deprecated=True,
)
async def list_funds(
    response: Response,
    block_id: str | None = Query(None, description="Filter by allocation block"),
    geography: str | None = Query(None, description="Filter by geography"),
    asset_class: str | None = Query(None, description="Filter by asset class"),
    is_active: bool | None = Query(True, description="Filter by active status"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[FundRead]:
    _set_deprecation_headers(response)
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
    summary="[DEPRECATED] Fund detail",
    description="DEPRECATED — use GET /instruments/{instrument_id} instead. "
    "Returns full metadata for a single fund.",
    deprecated=True,
)
async def get_fund(
    fund_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> FundRead:
    _set_deprecation_headers(response)
    result = await db.execute(select(Fund).where(Fund.fund_id == fund_id))
    fund = result.scalar_one_or_none()
    if fund is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fund not found")
    return FundRead.model_validate(fund)


@router.get(
    "/{fund_id}/risk",
    response_model=FundRiskRead | None,
    summary="[DEPRECATED] Fund risk metrics",
    description="DEPRECATED — use /instruments endpoints instead. "
    "Returns the latest risk metrics (CVaR, VaR, returns, ratios) for a fund.",
    deprecated=True,
)
async def get_fund_risk(
    fund_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> FundRiskRead | None:
    _set_deprecation_headers(response)
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
    summary="[DEPRECATED] Fund NAV time-series",
    description="DEPRECATED — use /instruments endpoints instead. "
    "Returns NAV history for a fund within a date range.",
    deprecated=True,
)
async def get_fund_nav(
    fund_id: uuid.UUID,
    response: Response,
    from_date: date | None = Query(None, alias="from", description="Start date"),
    to_date: date | None = Query(None, alias="to", description="End date"),
    limit: int = Query(1000, ge=1, le=10000, description="Max rows to return"),
    offset: int = Query(0, ge=0, description="Rows to skip"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[NavPoint]:
    _set_deprecation_headers(response)
    stmt = select(NavTimeseries).where(NavTimeseries.instrument_id == fund_id)
    if from_date is not None:
        stmt = stmt.where(NavTimeseries.nav_date >= from_date)
    if to_date is not None:
        stmt = stmt.where(NavTimeseries.nav_date <= to_date)
    stmt = stmt.order_by(NavTimeseries.nav_date).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return [NavPoint.model_validate(row) for row in result.scalars().all()]
