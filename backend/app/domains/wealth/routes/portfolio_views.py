"""Portfolio Views API routes — CRUD for IC Black-Litterman views.

Views are org-scoped and attached to a model portfolio.
IC role required for creation and deletion.
"""

from __future__ import annotations

import uuid
from datetime import date

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.models.model_portfolio import ModelPortfolio
from app.domains.wealth.models.portfolio_view import PortfolioView
from app.domains.wealth.schemas.portfolio_view import (
    PortfolioViewCreate,
    PortfolioViewRead,
)
from app.shared.enums import Role

logger = structlog.get_logger()

router = APIRouter(
    prefix="/model-portfolios/{portfolio_id}/views",
    tags=["portfolio-views"],
)


def _require_ic_role(actor: Actor) -> None:
    if not actor.has_role(Role.INVESTMENT_TEAM):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Investment Committee role required",
        )


async def _get_portfolio_or_404(
    db: AsyncSession, portfolio_id: uuid.UUID,
) -> ModelPortfolio:
    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )
    return portfolio


@router.post(
    "",
    response_model=PortfolioViewRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a portfolio view for Black-Litterman",
)
async def create_view(
    portfolio_id: uuid.UUID,
    body: PortfolioViewCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
    org_id: str = Depends(get_org_id),
) -> PortfolioViewRead:
    _require_ic_role(actor)
    await _get_portfolio_or_404(db, portfolio_id)

    if body.view_type == "relative" and body.peer_instrument_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Relative views require peer_instrument_id",
        )

    view = PortfolioView(
        organization_id=org_id,
        portfolio_id=portfolio_id,
        asset_instrument_id=body.asset_instrument_id,
        peer_instrument_id=body.peer_instrument_id,
        view_type=body.view_type,
        expected_return=body.expected_return,
        confidence=body.confidence,
        rationale=body.rationale,
        created_by=actor.actor_id,
        effective_from=body.effective_from,
        effective_to=body.effective_to,
    )
    db.add(view)
    await db.flush()
    await db.refresh(view)
    return PortfolioViewRead.model_validate(view)


@router.get(
    "",
    response_model=list[PortfolioViewRead],
    summary="List active portfolio views",
)
async def list_views(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[PortfolioViewRead]:
    await _get_portfolio_or_404(db, portfolio_id)
    today = date.today()

    stmt = (
        select(PortfolioView)
        .where(
            PortfolioView.portfolio_id == portfolio_id,
            PortfolioView.effective_from <= today,
        )
        .where(
            (PortfolioView.effective_to.is_(None))
            | (PortfolioView.effective_to >= today),
        )
        .order_by(PortfolioView.created_at.desc())
    )
    result = await db.execute(stmt)
    return [PortfolioViewRead.model_validate(v) for v in result.scalars().all()]


@router.delete(
    "/{view_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a portfolio view",
)
async def delete_view(
    portfolio_id: uuid.UUID,
    view_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> None:
    _require_ic_role(actor)

    result = await db.execute(
        select(PortfolioView).where(
            PortfolioView.id == view_id,
            PortfolioView.portfolio_id == portfolio_id,
        ),
    )
    view = result.scalar_one_or_none()
    if view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"View {view_id} not found",
        )

    await db.delete(view)
    await db.flush()
