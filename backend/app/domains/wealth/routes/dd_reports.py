"""DD Report API routes — trigger, list, read, regenerate, SSE stream.

All endpoints use get_db_with_rls and response_model + model_validate().
Generation runs via asyncio.to_thread() with sync Session (fix #33).
SSE stream uses tenant-scoped channels (fix #27).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.jobs.sse import create_job_stream
from app.core.jobs.tracker import publish_event, register_job_owner, verify_job_owner
from app.core.security.clerk_auth import CurrentUser, get_current_user
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.models.dd_report import DDReport
from app.domains.wealth.routes.common import _get_content_semaphore, require_content_slot
from app.domains.wealth.schemas.dd_report import (
    DDReportCreate,
    DDReportRead,
    DDReportRegenerate,
    DDReportSummary,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/dd-reports", tags=["dd-reports"])


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

    # Verify fund exists and belongs to org
    fund_result = await db.execute(
        select(Fund).where(Fund.fund_id == fund_id)
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
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing and existing.status == "generating":
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
        .limit(1)
    )
    max_version_row = max_version_result.scalar_one_or_none()
    next_version = (max_version_row + 1) if max_version_row else 1

    # Create report record
    report = DDReport(
        instrument_id=fund_id,
        organization_id=org_id,
        version=next_version,
        status="generating",
        is_current=True,
        config_snapshot=body.config_overrides if body else None,
        created_by=user.user_id,
    )
    db.add(report)
    await db.flush()

    report_id = report.id

    # Register job for SSE
    job_id = f"dd:{org_id}:{report_id}"
    await register_job_owner(job_id, org_id)

    # Backpressure: reject if too many concurrent content tasks
    await require_content_slot()

    # Dispatch generation (fire-and-forget background task).
    # The semaphore slot is released inside _run_generation's finally block.
    asyncio.create_task(
        _run_generation(
            report_id=str(report_id),
            fund_id=str(fund_id),
            org_id=str(org_id),
            actor_id=user.user_id,
            config=body.config_overrides if body else None,
            job_id=job_id,
        )
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
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[DDReportSummary]:
    """List all DD Reports for a fund (version history)."""
    result = await db.execute(
        select(DDReport)
        .where(DDReport.instrument_id == fund_id)
        .order_by(DDReport.version.desc())
    )
    reports = result.scalars().all()
    return [DDReportSummary.model_validate(r) for r in reports]


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
        .where(DDReport.id == report_id)
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
        select(DDReport).where(DDReport.id == report_id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DD Report {report_id} not found",
        )

    if report.status == "generating":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="DD Report generation already in progress",
        )

    report.status = "generating"
    await db.flush()

    job_id = f"dd:{org_id}:{report_id}"
    await register_job_owner(job_id, org_id)

    # Backpressure: reject if too many concurrent content tasks
    await require_content_slot()

    # The semaphore slot is released inside _run_generation's finally block.
    asyncio.create_task(
        _run_generation(
            report_id=str(report_id),
            fund_id=str(report.instrument_id),
            org_id=str(org_id),
            actor_id=user.user_id,
            config=report.config_snapshot,
            job_id=job_id,
            force=True,
        )
    )

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
    """
    try:
        await publish_event(job_id, "generation_started", {
            "report_id": report_id,
            "fund_id": fund_id,
        })

        # Import here to avoid circular imports
        from vertical_engines.wealth.dd_report import DDReportEngine

        engine = DDReportEngine(config=config)

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
            await publish_event(job_id, "report_failed", {
                "report_id": report_id,
                "error": result.error or "Generation failed",
            })
        else:
            await publish_event(job_id, "report_completed", {
                "report_id": report_id,
                "status": result.status,
                "confidence_score": result.confidence_score,
                "decision_anchor": result.decision_anchor,
            })

    except Exception as exc:
        logger.exception("dd_report_background_failed", report_id=report_id)
        await publish_event(job_id, "report_failed", {
            "report_id": report_id,
            "error": str(exc),
        })
    finally:
        _get_content_semaphore().release()


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
        db.execute(text("SET LOCAL app.current_organization_id = :oid"), {"oid": org_id})
        result = engine.generate(
            db,
            fund_id=fund_id,
            actor_id=actor_id,
            organization_id=org_id,
            force=force,
        )
        db.commit()

    return result
