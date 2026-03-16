"""Asset Universe API routes — approval workflow with governance controls.

All endpoints use get_db_with_rls and response_model + model_validate().
IC role required for approval/rejection. Self-approval prevention enforced.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.schemas.universe import (
    UniverseApprovalDecision,
    UniverseApprovalRead,
    UniverseAssetRead,
)
from app.shared.enums import Role

logger = structlog.get_logger()

router = APIRouter(prefix="/universe", tags=["universe"])


@router.get(
    "",
    response_model=list[UniverseAssetRead],
    summary="List approved funds in the universe",
)
async def list_universe(
    block_id: str | None = Query(None, description="Filter by allocation block"),
    geography: str | None = Query(None, description="Filter by geography"),
    asset_class: str | None = Query(None, description="Filter by asset class"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: str = Depends(get_org_id),
) -> list[UniverseAssetRead]:
    """List all approved and active funds in the investment universe."""
    from vertical_engines.wealth.asset_universe import UniverseService

    svc = UniverseService()

    def _list() -> list:
        from app.core.db.session import sync_session_factory

        with sync_session_factory() as sync_db:
            sync_db.expire_on_commit = False
            assets = svc.list_universe(
                sync_db,
                organization_id=org_id,
                block_id=block_id,
                geography=geography,
                asset_class=asset_class,
            )
            return [
                UniverseAssetRead(
                    instrument_id=a.instrument_id,
                    fund_name=a.fund_name,
                    block_id=a.block_id,
                    geography=a.geography,
                    asset_class=a.asset_class,
                    approval_status=a.approval_status,
                    approval_decision=a.approval_decision,
                    approved_at=a.approved_at,
                )
                for a in assets
            ]

    return await asyncio.to_thread(_list)


@router.get(
    "/pending",
    response_model=list[UniverseApprovalRead],
    summary="List pending universe approvals",
)
async def list_pending_approvals(
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: str = Depends(get_org_id),
) -> list[UniverseApprovalRead]:
    """List all pending approval requests for the organization."""
    from vertical_engines.wealth.asset_universe import UniverseService

    svc = UniverseService()

    def _list_pending() -> list:
        from app.core.db.session import sync_session_factory

        with sync_session_factory() as sync_db:
            sync_db.expire_on_commit = False
            approvals = svc.list_pending(sync_db, organization_id=org_id)
            return [UniverseApprovalRead.model_validate(a) for a in approvals]

    return await asyncio.to_thread(_list_pending)


@router.post(
    "/funds/{instrument_id}/approve",
    response_model=UniverseApprovalRead,
    summary="Approve a fund for the universe",
)
async def approve_fund(
    instrument_id: uuid.UUID,
    body: UniverseApprovalDecision,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
    org_id: str = Depends(get_org_id),
) -> UniverseApprovalRead:
    """Approve or watchlist a fund for the investment universe.

    Requires INVESTMENT_TEAM or ADMIN role.
    Self-approval is blocked: the person who submitted the fund cannot approve it.
    """
    _require_ic_role(actor)

    from vertical_engines.wealth.asset_universe import UniverseService
    from vertical_engines.wealth.asset_universe.fund_approval import SelfApprovalError

    svc = UniverseService()

    def _approve() -> UniverseApprovalRead:
        from app.core.db.session import sync_session_factory

        with sync_session_factory() as sync_db:
            sync_db.expire_on_commit = False
            # Find current pending approval for this fund
            from sqlalchemy import select

            from app.domains.wealth.models.universe_approval import UniverseApproval

            result = sync_db.execute(
                select(UniverseApproval).where(
                    UniverseApproval.instrument_id == instrument_id,
                    UniverseApproval.organization_id == org_id,
                    UniverseApproval.is_current.is_(True),
                ).with_for_update()
            )
            approval = result.scalar_one_or_none()
            if approval is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No pending approval found for fund {instrument_id}",
                )
            if approval.decision != "pending":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Approval already decided: {approval.decision}",
                )

            decision = body.decision if body.decision in ("approved", "watchlist") else "approved"
            try:
                updated = svc.approve_fund(
                    sync_db,
                    approval_id=approval.id,
                    decision=decision,
                    rationale=body.rationale,
                    decided_by=actor.actor_id,
                )
            except SelfApprovalError:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Self-approval is not allowed",
                )

            sync_db.commit()
            return UniverseApprovalRead.model_validate(updated)

    return await asyncio.to_thread(_approve)


@router.post(
    "/funds/{instrument_id}/reject",
    response_model=UniverseApprovalRead,
    summary="Reject a fund from the universe",
)
async def reject_fund(
    instrument_id: uuid.UUID,
    body: UniverseApprovalDecision,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
    org_id: str = Depends(get_org_id),
) -> UniverseApprovalRead:
    """Reject a fund from the investment universe.

    Requires INVESTMENT_TEAM or ADMIN role.
    Self-approval prevention applies: the submitter cannot reject.
    """
    _require_ic_role(actor)

    from vertical_engines.wealth.asset_universe import UniverseService
    from vertical_engines.wealth.asset_universe.fund_approval import SelfApprovalError

    svc = UniverseService()

    def _reject() -> UniverseApprovalRead:
        from app.core.db.session import sync_session_factory

        with sync_session_factory() as sync_db:
            sync_db.expire_on_commit = False
            from sqlalchemy import select

            from app.domains.wealth.models.universe_approval import UniverseApproval

            result = sync_db.execute(
                select(UniverseApproval).where(
                    UniverseApproval.instrument_id == instrument_id,
                    UniverseApproval.organization_id == org_id,
                    UniverseApproval.is_current.is_(True),
                ).with_for_update()
            )
            approval = result.scalar_one_or_none()
            if approval is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No pending approval found for fund {instrument_id}",
                )
            if approval.decision != "pending":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Approval already decided: {approval.decision}",
                )

            try:
                updated = svc.approve_fund(
                    sync_db,
                    approval_id=approval.id,
                    decision="rejected",
                    rationale=body.rationale,
                    decided_by=actor.actor_id,
                )
            except SelfApprovalError:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Self-approval is not allowed",
                )

            sync_db.commit()
            return UniverseApprovalRead.model_validate(updated)

    return await asyncio.to_thread(_reject)


def _require_ic_role(actor: Actor) -> None:
    """Verify actor has INVESTMENT_TEAM or ADMIN role."""
    if not actor.has_role(Role.INVESTMENT_TEAM):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Investment Committee role required for universe approvals",
        )
