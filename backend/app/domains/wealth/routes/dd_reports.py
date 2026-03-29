"""DD Report API routes — trigger, list, read, regenerate, SSE stream.

All endpoints use get_db_with_rls and response_model + model_validate().
Generation runs via asyncio.to_thread() with sync Session (fix #33).
SSE stream uses tenant-scoped channels (fix #27).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db.audit import get_audit_log, write_audit_event
from app.core.jobs.sse import create_job_stream
from app.core.jobs.tracker import (
    publish_event,
    publish_terminal_event,
    refresh_job_owner_ttl,
    register_job_owner,
    verify_job_owner,
)
from app.core.security.clerk_auth import Actor, CurrentUser, get_current_user, require_role
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.enums import DDReportStatus
from app.domains.wealth.models.dd_report import DDReport
from app.domains.wealth.routes.common import _get_content_semaphore, require_content_slot
from app.domains.wealth.schemas.dd_report import (
    AuditEventRead,
    DDReportApproveRequest,
    DDReportCreate,
    DDReportListItem,
    DDReportRead,
    DDReportRegenerate,
    DDReportRejectRequest,
    DDReportSummary,
)
from app.shared.enums import Role

logger = structlog.get_logger()

router = APIRouter(prefix="/dd-reports", tags=["dd-reports"])

# ---------------------------------------------------------------------------
#  DD-specific concurrency cap (max 3 simultaneous report generations)
# ---------------------------------------------------------------------------
# CRITICAL: No module-level asyncio primitives (CLAUDE.md rule).
_dd_generation_semaphore: asyncio.Semaphore | None = None
_MAX_CONCURRENT_DD_REPORTS = 3


def _get_dd_semaphore() -> asyncio.Semaphore:
    """Return (or lazily create) the DD report generation semaphore."""
    global _dd_generation_semaphore
    if _dd_generation_semaphore is None:
        _dd_generation_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_DD_REPORTS)
    return _dd_generation_semaphore


async def _require_dd_slot() -> None:
    """Try to acquire a DD generation slot without blocking.

    Raises HTTP 429 if all slots are occupied. Callers must release
    the slot by calling ``_get_dd_semaphore().release()`` in a finally block.
    """
    sem = _get_dd_semaphore()
    if sem.locked():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Too many concurrent DD report generations "
                f"(limit: {_MAX_CONCURRENT_DD_REPORTS}). "
                "Please retry shortly."
            ),
        )
    await sem.acquire()


@router.get(
    "/",
    response_model=list[DDReportListItem],
    summary="List all DD Reports for the tenant",
)
async def list_all_dd_reports(
    report_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[DDReportListItem]:
    """List all DD Reports across all instruments for the current tenant."""
    from app.domains.wealth.models.instrument import Instrument

    query = (
        select(DDReport, Instrument.name, Instrument.ticker)
        .outerjoin(Instrument, DDReport.instrument_id == Instrument.instrument_id)
        .where(DDReport.is_current.is_(True))
    )
    if report_status:
        query = query.where(DDReport.status == report_status)
    query = query.order_by(DDReport.created_at.desc()).limit(limit)

    result = await db.execute(query)
    rows = result.all()
    return [
        DDReportListItem(
            **DDReportSummary.model_validate(report).model_dump(),
            instrument_name=inst_name or "",
            instrument_ticker=inst_ticker,
        )
        for report, inst_name, inst_ticker in rows
    ]


@router.post(
    "/funds/{fund_id}",
    response_model=DDReportSummary,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger DD Report generation for a fund",
)
async def trigger_dd_report(
    fund_id: uuid.UUID,
    body: DDReportCreate | None = None,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: str = Depends(get_org_id),
) -> DDReportSummary:
    """Trigger async DD Report generation.

    Creates a draft report record and dispatches generation to a
    background thread via asyncio.to_thread().
    """
    from app.domains.wealth.models.fund import Fund
    from app.domains.wealth.models.instrument import Instrument

    # Verify fund exists — check instruments_universe first, then legacy funds_universe
    inst_result = await db.execute(
        select(Instrument).where(Instrument.instrument_id == fund_id),
    )
    instrument = inst_result.scalar_one_or_none()
    if not instrument:
        fund_result = await db.execute(
            select(Fund).where(Fund.fund_id == fund_id),
        )
        fund = fund_result.scalar_one_or_none()
        if not fund:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Fund {fund_id} not found",
            )

    # Mark previous report as not current
    existing_result = await db.execute(
        select(DDReport).where(
            DDReport.instrument_id == fund_id,
            DDReport.organization_id == org_id,
            DDReport.is_current.is_(True),
        ),
    )
    existing = existing_result.scalar_one_or_none()

    if existing and existing.status == DDReportStatus.generating:
        # Auto-recover stuck reports: if generating for > 15 min, mark as failed
        from datetime import timedelta
        stuck_threshold = datetime.now(UTC) - timedelta(minutes=15)
        if existing.created_at and existing.created_at.replace(tzinfo=UTC) < stuck_threshold:
            logger.warning("dd_report_stuck_recovery", report_id=str(existing.id), fund_id=str(fund_id))
            existing.status = DDReportStatus.failed.value
            existing.is_current = False
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="DD Report generation already in progress for this fund",
            )

    if existing:
        existing.is_current = False

    # Determine version
    max_version_result = await db.execute(
        select(DDReport.version)
        .where(
            DDReport.instrument_id == fund_id,
            DDReport.organization_id == org_id,
        )
        .order_by(DDReport.version.desc())
        .limit(1),
    )
    max_version_row = max_version_result.scalar_one_or_none()
    next_version = (max_version_row + 1) if max_version_row else 1

    # Create report record
    report = DDReport(
        instrument_id=fund_id,
        organization_id=org_id,
        version=next_version,
        status=DDReportStatus.generating.value,
        is_current=True,
        config_snapshot=body.config_overrides if body else None,
        created_by=user.actor_id,
    )
    db.add(report)
    await db.flush()

    report_id = report.id

    # Register job for SSE
    job_id = f"dd:{org_id}:{report_id}"
    await register_job_owner(job_id, str(org_id))

    # Backpressure: reject if too many concurrent content tasks
    await require_content_slot()
    # DD-specific concurrency cap
    await _require_dd_slot()

    # Dispatch generation (fire-and-forget background task).
    # Both semaphore slots are released inside _run_generation's finally block.
    asyncio.create_task(
        _run_generation(
            report_id=str(report_id),
            fund_id=str(fund_id),
            org_id=str(org_id),
            actor_id=user.actor_id,
            config=body.config_overrides if body else None,
            job_id=job_id,
        ),
    )

    await db.commit()

    return DDReportSummary.model_validate(report)


@router.get(
    "/funds/{fund_id}",
    response_model=list[DDReportSummary],
    summary="List DD Reports for a fund",
)
async def list_dd_reports(
    fund_id: uuid.UUID,
    report_status: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[DDReportSummary]:
    """List all DD Reports for a fund (version history)."""
    query = select(DDReport).where(DDReport.instrument_id == fund_id)
    if report_status:
        query = query.where(DDReport.status == report_status)
    query = query.order_by(DDReport.version.desc())
    result = await db.execute(query)
    reports = result.scalars().all()
    return [DDReportSummary.model_validate(r) for r in reports]


@router.get(
    "/{report_id}/audit-trail",
    response_model=list[AuditEventRead],
    summary="Get audit trail for a DD Report",
)
async def get_dd_report_audit_trail(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    _actor: Actor = Depends(require_role(Role.INVESTMENT_TEAM)),
) -> list[AuditEventRead]:
    """Get the full audit trail for a DD Report (approve/reject history)."""
    events = await get_audit_log(db, entity_id=str(report_id), entity_type="DDReport")
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


@router.get(
    "/{report_id}",
    response_model=DDReportRead,
    summary="Get full DD Report with chapters",
)
async def get_dd_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> DDReportRead:
    """Get a DD Report with all chapters loaded."""
    result = await db.execute(
        select(DDReport)
        .options(selectinload(DDReport.chapters))
        .where(DDReport.id == report_id),
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DD Report {report_id} not found",
        )

    return DDReportRead.model_validate(report)


@router.post(
    "/{report_id}/regenerate",
    response_model=DDReportSummary,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Regenerate DD Report chapters",
)
async def regenerate_dd_report(
    report_id: uuid.UUID,
    body: DDReportRegenerate | None = None,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: str = Depends(get_org_id),
) -> DDReportSummary:
    """Force regeneration of specific chapters or entire report."""
    result = await db.execute(
        select(DDReport).where(DDReport.id == report_id),
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DD Report {report_id} not found",
        )

    if report.status == DDReportStatus.generating:
        # Auto-recover stuck reports: if generating for > 15 min, allow re-trigger
        from datetime import timedelta
        stuck_threshold = datetime.now(UTC) - timedelta(minutes=15)
        if report.created_at and report.created_at.replace(tzinfo=UTC) < stuck_threshold:
            logger.warning("dd_report_stuck_recovery_regenerate", report_id=str(report_id))
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="DD Report generation already in progress",
            )

    report.status = DDReportStatus.generating.value
    await db.flush()

    job_id = f"dd:{org_id}:{report_id}"
    await register_job_owner(job_id, str(org_id))

    # Backpressure: reject if too many concurrent content tasks
    await require_content_slot()
    # DD-specific concurrency cap
    await _require_dd_slot()

    # Both semaphore slots are released inside _run_generation's finally block.
    asyncio.create_task(
        _run_generation(
            report_id=str(report_id),
            fund_id=str(report.instrument_id),
            org_id=str(org_id),
            actor_id=user.actor_id,
            config=report.config_snapshot,
            job_id=job_id,
            force=True,
        ),
    )

    await db.commit()
    return DDReportSummary.model_validate(report)


@router.post(
    "/{report_id}/approve",
    response_model=DDReportSummary,
    summary="Approve a DD Report for investor distribution",
)
async def approve_dd_report(
    report_id: uuid.UUID,
    body: DDReportApproveRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(require_role(Role.INVESTMENT_TEAM)),
) -> DDReportSummary:
    """Approve a DD report. Requires IC role. Self-approval blocked."""
    result = await db.execute(
        select(DDReport)
        .options(selectinload(DDReport.chapters))
        .where(DDReport.id == report_id),
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DD Report {report_id} not found",
        )

    if report.status != DDReportStatus.pending_approval:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Report status is '{report.status}', expected 'pending_approval'",
        )

    if actor.actor_id == report.created_by:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Self-approval is not allowed",
        )

    old_status = report.status
    # BL-17: Detect override — user action contradicts AI recommendation
    is_override = report.decision_anchor in ("REJECT", "CONDITIONAL")
    report.status = DDReportStatus.approved.value
    report.approved_by = actor.actor_id
    report.approved_at = datetime.now(UTC)
    report.rejection_reason = None
    logger.info(
        "dd_report_approved",
        report_id=str(report_id),
        approved_by=actor.actor_id,
        rationale=body.rationale,
        is_override=is_override,
    )
    await write_audit_event(
        db,
        actor_id=actor.actor_id,
        action="dd_report.approve.override" if is_override else "dd_report.approve",
        entity_type="DDReport",
        entity_id=str(report.id),
        before={
            "status": old_status,
            "decision_anchor": report.decision_anchor,
            "confidence_score": str(report.confidence_score) if report.confidence_score else None,
        },
        after={"status": "approved", "rationale": body.rationale},
    )

    # Update instrument approval_status in instruments_org (org-scoped)
    from app.domains.wealth.models.instrument_org import InstrumentOrg
    from app.domains.wealth.models.universe_approval import UniverseApproval

    io_result = await db.execute(
        select(InstrumentOrg).where(InstrumentOrg.instrument_id == report.instrument_id),
    )
    instrument_org = io_result.scalar_one_or_none()
    if instrument_org:
        instrument_org.approval_status = "approved"

    # Create UniverseApproval record for audit trail
    approval = UniverseApproval(
        instrument_id=report.instrument_id,
        organization_id=report.organization_id,
        analysis_report_id=report.id,
        decision="approved",
        rationale=body.rationale,
        created_by=report.created_by,
        decided_by=actor.actor_id,
        decided_at=datetime.now(UTC),
    )
    db.add(approval)

    await db.commit()

    return DDReportSummary.model_validate(report)


@router.post(
    "/{report_id}/reject",
    response_model=DDReportSummary,
    summary="Reject a DD Report back to draft",
)
async def reject_dd_report(
    report_id: uuid.UUID,
    body: DDReportRejectRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(require_role(Role.INVESTMENT_TEAM)),
) -> DDReportSummary:
    """Reject a DD report back to draft with rationale."""
    result = await db.execute(
        select(DDReport).where(DDReport.id == report_id),
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DD Report {report_id} not found",
        )

    if report.status != DDReportStatus.pending_approval:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Report status is '{report.status}', expected 'pending_approval'",
        )

    old_status = report.status
    # BL-17: Detect override — user rejects despite AI recommending APPROVE
    is_override = report.decision_anchor == "APPROVE"
    report.status = DDReportStatus.draft.value
    report.rejection_reason = body.reason
    report.approved_by = None
    report.approved_at = None
    await write_audit_event(
        db,
        actor_id=actor.actor_id,
        action="dd_report.reject.override" if is_override else "dd_report.reject",
        entity_type="DDReport",
        entity_id=str(report.id),
        before={
            "status": old_status,
            "decision_anchor": report.decision_anchor,
            "confidence_score": str(report.confidence_score) if report.confidence_score else None,
        },
        after={"status": "draft", "rejection_reason": body.reason},
    )

    # Revert instrument approval_status to pending in instruments_org (org-scoped)
    from app.domains.wealth.models.instrument_org import InstrumentOrg

    io_result = await db.execute(
        select(InstrumentOrg).where(InstrumentOrg.instrument_id == report.instrument_id),
    )
    instrument_org = io_result.scalar_one_or_none()
    if instrument_org and instrument_org.approval_status == "approved":
        instrument_org.approval_status = "pending"

    await db.commit()

    return DDReportSummary.model_validate(report)


@router.get(
    "/{report_id}/stream",
    summary="SSE stream for DD Report generation progress",
)
async def stream_dd_report(
    report_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    org_id: str = Depends(get_org_id),
) -> Any:
    """SSE stream providing real-time DD Report generation progress.

    Channel: wealth:dd:{organization_id}:{report_id}
    Events: chapter_started, chapter_completed, critic_started,
            critic_verdict, report_completed, report_failed
    """
    job_id = f"dd:{org_id}:{report_id}"

    # Verify ownership before subscribing (Security — fix #27)
    if not await verify_job_owner(job_id, org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Report does not belong to your organization",
        )

    return await create_job_stream(request, job_id)


async def _run_generation(
    *,
    report_id: str,
    fund_id: str,
    org_id: str,
    actor_id: str,
    config: dict[str, Any] | None,
    job_id: str,
    force: bool = False,
) -> None:
    """Background task: run DD Report generation in a sync thread.

    Creates a sync Session inside the thread (fix #33).
    Publishes SSE events for progress tracking.
    Releases the content-generation semaphore slot on completion.

    ASYNC-01: Refreshes ownership TTL every 20 minutes so long-running
    DD reports remain stream-authorizable beyond the default 1-hour TTL.
    Terminal events use publish_terminal_event() to schedule cleanup.
    """
    # ASYNC-01: background task that refreshes the ownership TTL every
    # 20 minutes while the job is active.  Cancelled in the finally block.
    ttl_refresh_task: asyncio.Task[None] | None = None

    async def _periodic_ttl_refresh() -> None:
        """Refresh ownership TTL every 20 min until cancelled."""
        try:
            while True:
                await asyncio.sleep(20 * 60)  # 20 minutes
                await refresh_job_owner_ttl(job_id)
        except asyncio.CancelledError:
            pass

    try:
        ttl_refresh_task = asyncio.create_task(_periodic_ttl_refresh())

        await publish_event(job_id, "generation_started", {
            "report_id": report_id,
            "fund_id": fund_id,
        })

        # Import here to avoid circular imports
        from ai_engine.llm import call_openai as _call_openai
        from vertical_engines.wealth.dd_report import DDReportEngine

        engine = DDReportEngine(config=config, call_openai_fn=_call_openai)

        # Run sync generation in a thread
        result = await asyncio.to_thread(
            _sync_generate,
            engine=engine,
            report_id=report_id,
            fund_id=fund_id,
            org_id=org_id,
            actor_id=actor_id,
            force=force,
        )

        if result.status == "failed":
            await publish_terminal_event(job_id, "report_failed", {
                "report_id": report_id,
                "error": result.error or "Generation failed",
            })
        else:
            await publish_terminal_event(job_id, "report_completed", {
                "report_id": report_id,
                "status": result.status,
                "confidence_score": result.confidence_score,
                "decision_anchor": result.decision_anchor,
            })

    except Exception as exc:
        logger.exception("dd_report_background_failed", report_id=report_id)
        await publish_terminal_event(job_id, "report_failed", {
            "report_id": report_id,
            "error": str(exc),
        })
    finally:
        if ttl_refresh_task is not None:
            ttl_refresh_task.cancel()
        _get_content_semaphore().release()
        _get_dd_semaphore().release()


def _sync_generate(
    *,
    engine: Any,
    report_id: str,
    fund_id: str,
    org_id: str,
    actor_id: str,
    force: bool,
) -> Any:
    """Sync wrapper: creates a sync Session inside the thread (fix #33).

    ORM objects must NOT be shared with the async context. The DDReportEngine
    returns a frozen DDReportResult dataclass that is safe to cross back.
    """
    from app.core.db.session import sync_session_factory

    with sync_session_factory() as db:
        db.expire_on_commit = False
        from sqlalchemy import text
        safe_oid = str(org_id).replace("'", "")
        db.execute(text(f"SET LOCAL app.current_organization_id = '{safe_oid}'"))
        result = engine.generate(
            db,
            instrument_id=fund_id,
            actor_id=actor_id,
            organization_id=org_id,
            force=force,
        )
        db.commit()

    return result
