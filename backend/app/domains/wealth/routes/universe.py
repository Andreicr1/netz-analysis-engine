"""Asset Universe API routes — approval workflow with governance controls.

All endpoints use get_db_with_rls and response_model + model_validate().
IC role required for approval/rejection. Self-approval prevention enforced.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
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
    """Set RLS tenant context in sync sessions (asyncio.to_thread context)."""
    from sqlalchemy import text as _text

    session.execute(
        _text("SELECT set_config('app.current_organization_id', :oid, true)"),
        {"oid": str(org_id)},
    )

_APPROVE_DECISIONS = {UniverseDecision.approved.value, UniverseDecision.watchlist.value}


_CORRELATION_LOOKBACK_DAYS = 756  # ~3 years of trading days


def _parse_current_holdings(raw: str | None) -> list[uuid.UUID]:
    """Parse the ?current_holdings=uuid1,uuid2,... query param.

    Returns an empty list on empty/None input, ignores malformed
    UUIDs silently (drops them) so a single bad id never blocks the
    whole loader. The Portfolio Builder routes its holdings through
    client-side validation already; this is belt-and-suspenders.
    """
    if not raw:
        return []
    ids: list[uuid.UUID] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            ids.append(uuid.UUID(token))
        except ValueError:
            logger.debug("universe_list_ignored_bad_holding_id", token=token)
    return ids


async def _load_correlations(
    db: AsyncSession,
    *,
    candidate_ids: list[uuid.UUID],
    current_holdings: list[uuid.UUID],
) -> dict[uuid.UUID, float | None]:
    """Load NAV return series and compute candidate→portfolio correlations.

    Pulls ~3 years of `nav_timeseries.return_1d` for every candidate
    and every current holding in a single batch query, groups by
    instrument, and delegates the math to
    `quant_engine.portfolio_correlation_service.compute_portfolio_correlations`.
    """
    from datetime import date, timedelta

    from sqlalchemy import select as sa_select

    from app.domains.wealth.models.nav import NavTimeseries
    from quant_engine.portfolio_correlation_service import (
        ReturnSeries,
        compute_portfolio_correlations,
    )

    if not current_holdings:
        return {cid: None for cid in candidate_ids}

    all_ids = list(set(candidate_ids) | set(current_holdings))
    cutoff = date.today() - timedelta(days=_CORRELATION_LOOKBACK_DAYS)

    stmt = (
        sa_select(
            NavTimeseries.instrument_id,
            NavTimeseries.nav_date,
            NavTimeseries.return_1d,
        )
        .where(NavTimeseries.instrument_id.in_(all_ids))
        .where(NavTimeseries.nav_date >= cutoff)
        .where(NavTimeseries.return_1d.is_not(None))
        .order_by(NavTimeseries.instrument_id, NavTimeseries.nav_date)
    )
    result = await db.execute(stmt)

    series_by_id: dict[uuid.UUID, list[tuple[str, float]]] = {}
    for row in result:
        series_by_id.setdefault(row.instrument_id, []).append(
            (row.nav_date.isoformat(), float(row.return_1d)),
        )

    def _to_series(iid: uuid.UUID) -> ReturnSeries:
        points = series_by_id.get(iid, [])
        dates = tuple(p[0] for p in points)
        returns = tuple(p[1] for p in points)
        return ReturnSeries(instrument_id=iid, dates=dates, returns=returns)

    candidates = [_to_series(cid) for cid in candidate_ids]
    holdings = [_to_series(hid) for hid in current_holdings if hid in series_by_id]

    return compute_portfolio_correlations(
        candidates=candidates,
        holdings=holdings,
    )


@router.get(
    "",
    response_model=list[UniverseAssetRead],
    summary="List approved funds in the universe",
)
async def list_universe(
    block_id: str | None = Query(None, description="Filter by allocation block"),
    geography: str | None = Query(None, description="Filter by geography"),
    asset_class: str | None = Query(None, description="Filter by asset class"),
    current_holdings: str | None = Query(
        None,
        description=(
            "Comma-separated UUIDs of instruments currently in the Builder workspace. "
            "When provided, each response row is enriched with `correlation_to_portfolio` "
            "— the Pearson correlation of the candidate's daily return series against "
            "the equal-weight synthetic portfolio of these holdings. Used by the Flexible "
            "Columns Layout Universe column (design spec 2026-04-08)."
        ),
    ),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: str = Depends(get_org_id),
) -> list[UniverseAssetRead]:
    """List all approved and active funds in the investment universe.

    Joins mv_unified_assets for enriched metadata and universe_approvals
    for the current approval decision/timestamp. When `current_holdings`
    is supplied, enriches each row with `correlation_to_portfolio`
    computed on-the-fly from `nav_timeseries.return_1d`.
    """
    from sqlalchemy import Column, MetaData, Table, Text, func, select
    from sqlalchemy.orm import aliased
    from sqlalchemy.sql import and_

    from app.domains.wealth.models.instrument_org import InstrumentOrg
    from app.domains.wealth.models.nav import NavTimeseries
    from app.domains.wealth.models.risk import FundRiskMetrics
    from app.domains.wealth.models.universe_approval import UniverseApproval

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

    # Latest-row-per-instrument subqueries for fund_risk_metrics and
    # nav_timeseries. These use DISTINCT ON (Postgres-specific) which
    # is O(n log n) with the existing primary-key index on
    # (instrument_id, calc_date|nav_date). The alternative — a window
    # function with ROW_NUMBER — is marginally slower on the same
    # indexes and uglier to read. DISTINCT ON wins.
    latest_risk = (
        select(FundRiskMetrics)
        .distinct(FundRiskMetrics.instrument_id)
        .order_by(FundRiskMetrics.instrument_id, FundRiskMetrics.calc_date.desc())
        .subquery()
    )
    latest_risk_alias = aliased(FundRiskMetrics, latest_risk)

    latest_nav = (
        select(
            NavTimeseries.instrument_id,
            func.max(NavTimeseries.aum_usd).label("aum_usd"),
        )
        .where(NavTimeseries.aum_usd.is_not(None))
        .group_by(NavTimeseries.instrument_id)
        .subquery()
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
            UniverseApproval.decision.label("approval_decision"),
            UniverseApproval.decided_at.label("approved_at"),
            # Tier 1 density from fund_risk_metrics
            latest_risk_alias.return_3y_ann,
            latest_risk_alias.sharpe_1y,
            latest_risk_alias.max_drawdown_1y,
            latest_risk_alias.blended_momentum_score,
            latest_risk_alias.manager_score,
            # AUM from nav_timeseries (latest non-null)
            latest_nav.c.aum_usd,
        )
        .join(mv_assets, mv_assets.c.id == InstrumentOrg.instrument_id.cast(Text))
        .outerjoin(
            UniverseApproval,
            and_(
                UniverseApproval.instrument_id == InstrumentOrg.instrument_id,
                UniverseApproval.is_current.is_(True),
            ),
        )
        .outerjoin(
            latest_risk_alias,
            latest_risk_alias.instrument_id == InstrumentOrg.instrument_id,
        )
        .outerjoin(
            latest_nav,
            latest_nav.c.instrument_id == InstrumentOrg.instrument_id,
        )
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

    # Compute correlations on-the-fly when the caller supplied the
    # Builder workspace holdings. The service swallows missing series
    # and returns None for candidates without sufficient overlap, so
    # we can always `.get()` with a None fallback.
    holding_ids = _parse_current_holdings(current_holdings)
    candidate_ids = [r.instrument_id for r in rows]
    try:
        correlations = await _load_correlations(
            db,
            candidate_ids=candidate_ids,
            current_holdings=holding_ids,
        )
    except Exception as e:
        # Correlation enrichment is best-effort — the universe table
        # must still render even if nav_timeseries has a hiccup or
        # the service raises. Log and move on with None values.
        logger.warning(
            "universe_correlation_enrichment_failed",
            error=str(e),
            holding_count=len(holding_ids),
            candidate_count=len(candidate_ids),
        )
        correlations = {cid: None for cid in candidate_ids}

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
            approval_decision=r.approval_decision or "approved",
            approved_at=r.approved_at,
            # Tier 1 density — None for any field the risk worker
            # hasn't produced yet; frontend renders "—" in those cells.
            aum_usd=r.aum_usd,
            # expense_ratio + liquidity_tier are not yet in fund_risk_metrics
            # — they live on instrument.attributes JSON (enriched by
            # import_sec_security per CLAUDE.md). Populating them
            # requires joining instruments_universe.attributes, which
            # is deferred to a follow-up commit. For now they are None
            # and the UI renders em-dash. Documented in spec §6.4.
            expense_ratio=None,
            liquidity_tier=None,
            return_3y_ann=r.return_3y_ann,
            sharpe_1y=r.sharpe_1y,
            max_drawdown_1y=r.max_drawdown_1y,
            blended_momentum_score=r.blended_momentum_score,
            manager_score=r.manager_score,
            correlation_to_portfolio=correlations.get(r.instrument_id),
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


# ── Phase 3 Session A commit 4: fast-track liquid approval ────────

_LIQUID_UNIVERSES = frozenset({"registered_us", "etf", "ucits_eu", "money_market"})
_DD_REQUIRED_UNIVERSES = frozenset({"private_us", "bdc"})


class FastApproveRequest(BaseModel):
    """Request body for fast-track universe approval."""

    instrument_ids: list[uuid.UUID]
    block_id: str | None = None
    source: str = "screener_fast_path"


class FastApproveResponse(BaseModel):
    """Response body for fast-track universe approval."""

    approved: list[str]
    rejected_dd_required: list[str]


@router.post(
    "/fast-approve",
    response_model=FastApproveResponse,
    summary="Fast-track liquid fund approval from screener",
)
async def fast_approve(
    body: FastApproveRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
    org_id: str = Depends(get_org_id),
) -> FastApproveResponse:
    """Approve liquid funds directly from the screener in one click.

    Liquid funds (registered_us, etf, ucits_eu, money_market) are
    approved immediately. Private funds and BDCs are rejected with a
    ``dd_required`` marker — they need a completed DD report before
    universe approval.

    Idempotent: if a fund is already approved for this org, it is
    returned in the ``approved`` list without creating a duplicate row.
    """
    _require_ic_role(actor)

    if not body.instrument_ids:
        return FastApproveResponse(approved=[], rejected_dd_required=[])

    from sqlalchemy import select as sa_select, text as sa_text

    from app.domains.wealth.models.instrument import Instrument
    from app.domains.wealth.models.instrument_org import InstrumentOrg

    # Load instruments to check universe type
    instruments = (
        await db.execute(
            sa_select(
                Instrument.instrument_id,
                Instrument.attributes["sec_universe"].astext.label("sec_universe"),
            ).where(Instrument.instrument_id.in_(body.instrument_ids))
        )
    ).all()

    inst_map = {r.instrument_id: r.sec_universe for r in instruments}

    approved: list[str] = []
    rejected_dd: list[str] = []

    for iid in body.instrument_ids:
        universe = inst_map.get(iid)

        if universe in _DD_REQUIRED_UNIVERSES:
            rejected_dd.append(str(iid))
            continue

        # Check if already approved (idempotent)
        existing = (
            await db.execute(
                sa_select(InstrumentOrg.id).where(
                    InstrumentOrg.instrument_id == iid,
                )
            )
        ).scalar_one_or_none()

        if existing:
            # Already exists — treat as success
            approved.append(str(iid))
            continue

        # Create new instruments_org row with approved status
        new_org = InstrumentOrg(
            instrument_id=iid,
            organization_id=uuid.UUID(org_id),
            block_id=body.block_id,
            approval_status="approved",
        )
        db.add(new_org)
        approved.append(str(iid))

        await write_audit_event(
            db,
            actor_id=actor.actor_id,
            action="universe.fast_approve",
            entity_type="InstrumentOrg",
            entity_id=str(iid),
            before=None,
            after={
                "approval_status": "approved",
                "source": body.source,
                "block_id": body.block_id,
            },
        )

    if approved:
        await db.commit()

    return FastApproveResponse(
        approved=approved,
        rejected_dd_required=rejected_dd,
    )
