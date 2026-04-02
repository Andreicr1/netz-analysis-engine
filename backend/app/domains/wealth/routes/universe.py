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

from app.core.db.audit import get_audit_log, write_audit_event
from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.enums import UniverseDecision
from app.domains.wealth.schemas.dd_report import AuditEventRead
from app.domains.wealth.schemas.universe import (
    UniverseApprovalDecision,
    UniverseApprovalRead,
    UniverseAssetRead,
)
from app.shared.enums import Role

logger = structlog.get_logger()

router = APIRouter(prefix="/universe", tags=["universe"])


def _set_rls_sync(session, org_id) -> None:
    """SET LOCAL for RLS in sync sessions (asyncio.to_thread context)."""
    from sqlalchemy import text as _text

    safe_oid = str(org_id).replace("'", "")
    session.execute(_text(f"SET LOCAL app.current_organization_id = '{safe_oid}'"))

_APPROVE_DECISIONS = {UniverseDecision.approved.value, UniverseDecision.watchlist.value}


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
    """List all approved and active funds in the investment universe.
    
    Refactored to join mv_unified_assets for enriched metadata (Ticker, ISIN, Geography).
    """
    from sqlalchemy import Column, MetaData, Table, Text, select

    from app.domains.wealth.models.instrument_org import InstrumentOrg

    # Dynamic reflection of mv_unified_assets
    _meta = MetaData()
    mv_assets = Table(
        "mv_unified_assets", _meta,
        Column("id", Text, primary_key=True),
        Column("name", Text),
        Column("ticker", Text),
        Column("isin", Text),
        Column("asset_class", Text),
        Column("geography", Text),
    )

    stmt = (
        select(
            InstrumentOrg.instrument_id,
            mv_assets.c.name.label("fund_name"),
            mv_assets.c.ticker,
            mv_assets.c.isin,
            InstrumentOrg.block_id,
            mv_assets.c.geography,
            mv_assets.c.asset_class,
            InstrumentOrg.approval_status,
            InstrumentOrg.approval_decision,
            InstrumentOrg.approved_at,
        )
        .join(mv_assets, mv_assets.c.id == InstrumentOrg.instrument_id.cast(Text))
        .where(InstrumentOrg.approval_status == "approved")
    )

    if block_id:
        stmt = stmt.where(InstrumentOrg.block_id == block_id)
    if geography:
        stmt = stmt.where(mv_assets.c.geography == geography)
    if asset_class:
        stmt = stmt.where(mv_assets.c.asset_class == asset_class)

    result = await db.execute(stmt)
    rows = result.all()

    return [
        UniverseAssetRead(
            instrument_id=r.instrument_id,
            fund_name=r.fund_name,
            ticker=r.ticker,
            isin=r.isin,
            block_id=r.block_id,
            geography=r.geography,
            asset_class=r.asset_class,
            approval_status=r.approval_status,
            approval_decision=r.approval_decision,
            approved_at=r.approved_at,
        )
        for r in rows
    ]


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
    """List all pending approval requests for the organization.

    Enriches each approval with fund_name, ticker, and block_id from
    Instrument + InstrumentOrg tables for UI display.
    """
    from vertical_engines.wealth.asset_universe import UniverseService

    svc = UniverseService()

    def _list_pending() -> list:
        from sqlalchemy import select as sa_select

        from app.core.db.session import sync_session_factory
        from app.domains.wealth.models.instrument import Instrument
        from app.domains.wealth.models.instrument_org import InstrumentOrg

        with sync_session_factory() as sync_db, sync_db.begin():
            sync_db.expire_on_commit = False
            _set_rls_sync(sync_db, org_id)
            approvals = svc.list_pending(sync_db, organization_id=org_id)

            # Build lookup for instrument metadata
            instrument_ids = [a.instrument_id for a in approvals]
            if instrument_ids:
                rows = sync_db.execute(
                    sa_select(
                        Instrument.instrument_id,
                        Instrument.name,
                        Instrument.ticker,
                        InstrumentOrg.block_id,
                    )
                    .outerjoin(InstrumentOrg, InstrumentOrg.instrument_id == Instrument.instrument_id)
                    .where(Instrument.instrument_id.in_(instrument_ids))
                ).all()
                meta = {r[0]: (r[1], r[2], r[3]) for r in rows}
            else:
                meta = {}

            result = []
            for a in approvals:
                data = UniverseApprovalRead.model_validate(a)
                info = meta.get(a.instrument_id)
                if info:
                    data.fund_name = info[0]
                    data.ticker = info[1]
                    data.block_id = info[2]
                result.append(data)
            return result

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

    def _approve() -> tuple[UniverseApprovalRead, str]:
        from app.core.db.session import sync_session_factory

        with sync_session_factory() as sync_db, sync_db.begin():
            sync_db.expire_on_commit = False
            _set_rls_sync(sync_db, org_id)
            # Find current pending approval for this fund
            from sqlalchemy import select

            from app.domains.wealth.models.universe_approval import UniverseApproval

            result = sync_db.execute(
                select(UniverseApproval).where(
                    UniverseApproval.instrument_id == instrument_id,
                    UniverseApproval.organization_id == org_id,
                    UniverseApproval.is_current.is_(True),
                ).with_for_update(),
            )
            approval = result.scalar_one_or_none()
            if approval is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No pending approval found for fund {instrument_id}",
                )
            if approval.decision != UniverseDecision.pending:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Approval already decided: {approval.decision}",
                )

            if body.decision not in _APPROVE_DECISIONS:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid decision '{body.decision}'. Allowed values: {sorted(_APPROVE_DECISIONS)}",
                )
            old_decision = str(approval.decision)
            decision = body.decision
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

            return UniverseApprovalRead.model_validate(updated), old_decision

    approval_result, old_decision = await asyncio.to_thread(_approve)
    await write_audit_event(
        db,
        actor_id=actor.actor_id,
        action="universe.approve",
        entity_type="UniverseApproval",
        entity_id=str(instrument_id),
        before={"decision": old_decision},
        after={"decision": body.decision, "rationale": body.rationale},
    )
    await db.commit()
    return approval_result


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

    if body.decision != UniverseDecision.rejected.value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid decision '{body.decision}' for reject endpoint. Expected 'rejected'.",
        )

    from vertical_engines.wealth.asset_universe import UniverseService
    from vertical_engines.wealth.asset_universe.fund_approval import SelfApprovalError

    svc = UniverseService()

    def _reject() -> tuple[UniverseApprovalRead, str]:
        from app.core.db.session import sync_session_factory

        with sync_session_factory() as sync_db, sync_db.begin():
            sync_db.expire_on_commit = False
            _set_rls_sync(sync_db, org_id)
            from sqlalchemy import select

            from app.domains.wealth.models.universe_approval import UniverseApproval

            result = sync_db.execute(
                select(UniverseApproval).where(
                    UniverseApproval.instrument_id == instrument_id,
                    UniverseApproval.organization_id == org_id,
                    UniverseApproval.is_current.is_(True),
                ).with_for_update(),
            )
            approval = result.scalar_one_or_none()
            if approval is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No pending approval found for fund {instrument_id}",
                )
            if approval.decision != UniverseDecision.pending:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Approval already decided: {approval.decision}",
                )

            old_decision = str(approval.decision)
            try:
                updated = svc.approve_fund(
                    sync_db,
                    approval_id=approval.id,
                    decision=UniverseDecision.rejected.value,
                    rationale=body.rationale,
                    decided_by=actor.actor_id,
                )
            except SelfApprovalError:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Self-approval is not allowed",
                )

            return UniverseApprovalRead.model_validate(updated), old_decision

    rejection_result, old_decision = await asyncio.to_thread(_reject)
    await write_audit_event(
        db,
        actor_id=actor.actor_id,
        action="universe.reject",
        entity_type="UniverseApproval",
        entity_id=str(instrument_id),
        before={"decision": old_decision},
        after={"decision": "rejected", "rationale": body.rationale},
    )
    await db.commit()
    return rejection_result


@router.get(
    "/funds/{instrument_id}/audit-trail",
    response_model=list[AuditEventRead],
    summary="Get audit trail for a universe fund approval",
)
async def get_universe_audit_trail(
    instrument_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> list[AuditEventRead]:
    """Get the full audit trail for a universe fund (approve/reject history)."""
    _require_ic_role(actor)
    events = await get_audit_log(db, entity_id=str(instrument_id), entity_type="UniverseApproval")
    return [
        AuditEventRead(
            id=str(e.id),
            action=e.action,
            actor_id=e.actor_id,
            before=e.before_state,
            after=e.after_state,
            created_at=e.created_at.isoformat() if e.created_at else None,
        )
        for e in events
    ]


def _require_ic_role(actor: Actor) -> None:
    """Verify actor has INVESTMENT_TEAM or ADMIN role."""
    if not actor.has_role(Role.INVESTMENT_TEAM):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Investment Committee role required for universe approvals",
        )
