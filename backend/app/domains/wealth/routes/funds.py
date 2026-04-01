"""DEPRECATED: Fund CRUD routes — kept for backward compatibility.

The Fund model is being replaced by the Instrument model
(instruments_universe table). These routes remain functional
but new code should use the Instrument equivalents.

All responses include a ``Deprecation`` header (RFC 8594) and
``Sunset`` header pointing clients to the /instruments endpoints.
See SR-4 audit finding.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import CurrentUser, get_current_user
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.models.fund import Fund
from app.domains.wealth.models.risk import FundRiskMetrics
from app.domains.wealth.schemas.fund import FundRead
from app.domains.wealth.schemas.risk import FundRiskRead

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


