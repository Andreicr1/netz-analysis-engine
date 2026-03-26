"""Rebalancing — tactical proposal application route.

POST /rebalancing/proposals/{proposal_id}/apply

Applies a pending rebalance proposal: updates ModelPortfolio weights,
creates a new PortfolioSnapshot, inserts a NAV composition breakpoint,
and marks the proposal as applied with audit trail.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.models.model_portfolio import ModelPortfolio
from app.domains.wealth.models.model_portfolio_nav import ModelPortfolioNav
from app.domains.wealth.models.portfolio import PortfolioSnapshot
from app.domains.wealth.models.rebalance import RebalanceEvent
from app.domains.wealth.schemas.portfolio import PortfolioSnapshotRead

logger = structlog.get_logger()

router = APIRouter(prefix="/rebalancing", tags=["rebalancing"])


@router.post(
    "/proposals/{proposal_id}/apply",
    response_model=PortfolioSnapshotRead,
    summary="Apply a rebalance proposal",
    description=(
        "Applies pending rebalance proposal weights to the model portfolio. "
        "Creates a new PortfolioSnapshot and a NAV composition breakpoint "
        "for the portfolio_nav_synthesizer to detect."
    ),
)
async def apply_rebalance_proposal(
    proposal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
    org_id: str = Depends(get_org_id),
) -> PortfolioSnapshotRead:
    """Apply a pending rebalance proposal.

    Steps:
    1. Validate proposal is pending and belongs to caller's org (RLS)
    2. Update ModelPortfolio.fund_selection_schema with new weights
    3. Create new PortfolioSnapshot with trigger_status='rebalance_apply'
    4. Insert ModelPortfolioNav breakpoint (daily_return = 0.0)
    5. Mark proposal as 'applied' with audit trail
    6. Return the created PortfolioSnapshot
    """
    # ── 1. Load and validate proposal ──
    stmt = (
        select(RebalanceEvent)
        .where(RebalanceEvent.event_id == proposal_id)
        .with_for_update()
    )
    result = await db.execute(stmt)
    proposal = result.scalar_one_or_none()

    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rebalance proposal {proposal_id} not found",
        )

    if proposal.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Proposal is '{proposal.status}', expected 'pending'",
        )

    if not proposal.weights_after:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Proposal has no weights_after — cannot apply",
        )

    # ── 2. Load the target model portfolio ──
    portfolio_stmt = (
        select(ModelPortfolio)
        .where(ModelPortfolio.profile == proposal.profile)
        .with_for_update()
    )
    portfolio_result = await db.execute(portfolio_stmt)
    portfolio = portfolio_result.scalar_one_or_none()

    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No model portfolio found for profile '{proposal.profile}'",
        )

    # Snapshot the old state for audit
    old_fund_selection = portfolio.fund_selection_schema

    # Build new fund_selection_schema from proposal weights
    new_fund_selection = _apply_weights_to_selection(
        old_fund_selection, proposal.weights_after,
    )
    portfolio.fund_selection_schema = new_fund_selection

    # ── 3. Create PortfolioSnapshot ──
    today = date.today()

    # Aggregate fund weights to block-level for snapshot.weights
    block_weights = _aggregate_block_weights(new_fund_selection)

    snapshot = PortfolioSnapshot(
        organization_id=org_id,
        profile=proposal.profile,
        snapshot_date=today,
        weights=block_weights,
        fund_selection=new_fund_selection,
        cvar_current=proposal.cvar_after,
        cvar_limit=None,  # will be recomputed by portfolio_eval worker
        trigger_status="ok",
        consecutive_breach_days=0,
    )
    db.add(snapshot)
    await db.flush()
    await db.refresh(snapshot)

    # ── 4. Insert NAV composition breakpoint ──
    # daily_return = 0.0 marks the composition change for the
    # portfolio_nav_synthesizer to detect and reprocess from this date
    nav_breakpoint = pg_insert(ModelPortfolioNav).values(
        portfolio_id=portfolio.id,
        nav_date=today,
        nav=Decimal("0"),  # placeholder — worker recalculates
        daily_return=Decimal("0.0"),
        organization_id=org_id,
    )
    nav_breakpoint = nav_breakpoint.on_conflict_do_update(
        index_elements=["portfolio_id", "nav_date"],
        set_={
            "daily_return": Decimal("0.0"),
        },
    )
    await db.execute(nav_breakpoint)

    # ── 5. Mark proposal as applied ──
    proposal.status = "applied"
    proposal.approved_by = actor.actor_id
    proposal.weights_after = proposal.weights_after  # preserve

    # Audit trail
    await write_audit_event(
        db,
        actor_id=actor.actor_id,
        action="UPDATE",
        entity_type="rebalance_event",
        entity_id=proposal.event_id,
        before={"status": "pending", "fund_selection_schema": old_fund_selection},
        after={"status": "applied", "fund_selection_schema": new_fund_selection},
    )

    await db.flush()

    logger.info(
        "rebalance_proposal_applied",
        proposal_id=str(proposal_id),
        profile=proposal.profile,
        portfolio_id=str(portfolio.id),
        snapshot_date=str(today),
        actor=actor.actor_id,
    )

    # ── 6. Return snapshot ──
    out = PortfolioSnapshotRead.model_validate(snapshot)
    out.computed_at = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
    return out


def _apply_weights_to_selection(
    old_selection: dict[str, Any] | None,
    new_weights: dict[str, Any],
) -> dict[str, Any]:
    """Merge new block weights into existing fund_selection_schema.

    new_weights is a dict {block_id: weight} from WeightProposal.
    This redistributes the block-level weights proportionally across
    existing funds within each block.
    """
    if not old_selection:
        return {"funds": [], "rebalanced_at": datetime.now(UTC).isoformat()}

    old_funds = old_selection.get("funds", [])
    if not old_funds:
        return {"funds": [], "rebalanced_at": datetime.now(UTC).isoformat()}

    # Group current funds by block
    block_funds: dict[str, list[dict[str, Any]]] = {}
    for f in old_funds:
        bid = f.get("block_id", "unknown")
        block_funds.setdefault(bid, []).append(f)

    # Compute current total weight per block
    block_totals: dict[str, float] = {}
    for bid, funds in block_funds.items():
        block_totals[bid] = sum(f.get("weight", 0.0) for f in funds)

    # Redistribute within each block proportionally
    new_funds: list[dict[str, Any]] = []
    for bid, funds in block_funds.items():
        new_block_weight = new_weights.get(bid)
        if new_block_weight is None:
            # Block not in proposal — keep as is
            new_funds.extend(funds)
            continue

        old_total = block_totals.get(bid, 0.0)
        if old_total <= 0:
            new_funds.extend(funds)
            continue

        scale = new_block_weight / old_total
        for f in funds:
            updated = {**f, "weight": f.get("weight", 0.0) * scale}
            new_funds.append(updated)

    result = {**old_selection, "funds": new_funds}
    result["rebalanced_at"] = datetime.now(UTC).isoformat()
    return result


def _aggregate_block_weights(fund_selection: dict[str, Any]) -> dict[str, float]:
    """Sum fund weights by block_id for PortfolioSnapshot.weights."""
    block_weights: dict[str, float] = {}
    for f in fund_selection.get("funds", []):
        bid = f.get("block_id", "unknown")
        block_weights[bid] = block_weights.get(bid, 0.0) + f.get("weight", 0.0)
    return block_weights
