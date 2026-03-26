"""Long-Form Report API route — trigger generation with SSE progress.

POST /reporting/model-portfolios/{portfolio_id}/long-form-report
  → dispatches async generation, returns SSE stream with per-chapter progress.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jobs.sse import create_job_stream
from app.core.jobs.tracker import (
    publish_event,
    publish_terminal_event,
    register_job_owner,
    verify_job_owner,
)
from app.core.security.clerk_auth import CurrentUser, get_current_user
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.models.model_portfolio import ModelPortfolio

logger = structlog.get_logger()

router = APIRouter(prefix="/reporting", tags=["reporting"])

# Lazy semaphore (no module-level asyncio primitives)
_lfr_semaphore: asyncio.Semaphore | None = None
_MAX_CONCURRENT = 2


def _get_semaphore() -> asyncio.Semaphore:
    global _lfr_semaphore
    if _lfr_semaphore is None:
        _lfr_semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
    return _lfr_semaphore


@router.post(
    "/model-portfolios/{portfolio_id}/long-form-report",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate long-form client report (SSE)",
    description=(
        "Triggers 8-chapter long-form report generation for a model portfolio. "
        "Returns a job_id for SSE streaming of per-chapter progress."
    ),
)
async def generate_long_form_report(
    portfolio_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_org_id),
) -> dict:
    # Validate portfolio exists
    result = await db.execute(
        select(ModelPortfolio.id).where(ModelPortfolio.id == portfolio_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model portfolio not found",
        )

    # Try to acquire generation slot
    sem = _get_semaphore()
    try:
        await asyncio.wait_for(sem.acquire(), timeout=0)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many concurrent long-form reports (max {_MAX_CONCURRENT})",
        )

    # Register job for SSE
    job_id = f"lfr-{portfolio_id}-{uuid.uuid4().hex[:8]}"
    await register_job_owner(job_id, str(org_id))

    # Fire background generation
    asyncio.create_task(
        _run_generation(
            job_id=job_id,
            portfolio_id=str(portfolio_id),
            organization_id=str(org_id),
            semaphore=sem,
        )
    )

    return {"job_id": job_id, "portfolio_id": str(portfolio_id)}


@router.get(
    "/model-portfolios/{portfolio_id}/long-form-report/stream/{job_id}",
    summary="SSE stream for long-form report generation progress",
)
async def stream_long_form_report(
    portfolio_id: uuid.UUID,
    job_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_org_id),
):
    if not await verify_job_owner(job_id, str(org_id)):
        raise HTTPException(status_code=403, detail="Job not found")
    return await create_job_stream(request, job_id)


async def _run_generation(
    *,
    job_id: str,
    portfolio_id: str,
    organization_id: str,
    semaphore: asyncio.Semaphore,
) -> None:
    """Background task: run LongFormReportEngine and publish SSE events."""
    from app.core.db.engine import async_session_factory
    from app.core.tenancy.middleware import set_rls_context

    try:
        async with async_session_factory() as db:
            await set_rls_context(db, uuid.UUID(organization_id))

            from vertical_engines.wealth.long_form_report import LongFormReportEngine

            engine = LongFormReportEngine()

            await publish_event(job_id, "started", {
                "portfolio_id": portfolio_id,
                "total_chapters": 8,
            })

            result = await engine.generate(
                db,
                portfolio_id=portfolio_id,
                organization_id=organization_id,
            )

            # Publish per-chapter progress
            for ch in result.chapters:
                await publish_event(job_id, "chapter_complete", {
                    "chapter": ch.tag,
                    "order": ch.order,
                    "title": ch.title,
                    "status": ch.status,
                    "confidence": ch.confidence,
                })

            await publish_terminal_event(
                job_id,
                "done" if result.status != "failed" else "error",
                {
                    "status": result.status,
                    "chapters_completed": sum(
                        1 for ch in result.chapters if ch.status == "completed"
                    ),
                    "total_chapters": len(result.chapters),
                    "error": result.error,
                },
            )

    except Exception as exc:
        logger.exception("long_form_report_background_failed", job_id=job_id)
        await publish_terminal_event(job_id, "error", {"error": str(exc)})
    finally:
        semaphore.release()
