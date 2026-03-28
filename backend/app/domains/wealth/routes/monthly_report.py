"""Monthly Client Report API routes.

POST /reporting/model-portfolios/{portfolio_id}/monthly-report
  → generate report, return job_id

GET  /reporting/model-portfolios/{portfolio_id}/monthly-report/{job_id}/status
  → check generation status (via generic /jobs/{job_id}/status)

GET  /reporting/model-portfolios/{portfolio_id}/monthly-report/{job_id}/pdf
  → download PDF bytes
"""
from __future__ import annotations

import asyncio
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
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
_mcr_semaphore: asyncio.Semaphore | None = None
_MAX_CONCURRENT = 2


def _get_semaphore() -> asyncio.Semaphore:
    global _mcr_semaphore
    if _mcr_semaphore is None:
        _mcr_semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
    return _mcr_semaphore


@router.post(
    "/model-portfolios/{portfolio_id}/monthly-report",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate Monthly Client Report (SSE)",
    description="Triggers Monthly Client Report PDF generation. Returns job_id for SSE streaming.",
)
async def generate_monthly_report(
    portfolio_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_org_id),
) -> dict:
    """Trigger Monthly Client Report generation. Returns job_id."""
    # Validate portfolio exists
    result = await db.execute(
        select(ModelPortfolio.id).where(ModelPortfolio.id == portfolio_id),
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model portfolio not found",
        )

    # Try to acquire generation slot
    sem = _get_semaphore()
    if sem.locked():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many concurrent monthly reports (max {_MAX_CONCURRENT})",
        )
    await sem.acquire()

    # Register job for SSE
    job_id = f"mcr-{portfolio_id}-{uuid.uuid4().hex[:8]}"
    await register_job_owner(job_id, str(org_id))

    # Fire background generation
    asyncio.create_task(
        _run_monthly_generation(
            job_id=job_id,
            portfolio_id=str(portfolio_id),
            organization_id=str(org_id),
            semaphore=sem,
        ),
    )

    return {"job_id": job_id, "portfolio_id": str(portfolio_id)}


@router.get(
    "/model-portfolios/{portfolio_id}/monthly-report/stream/{job_id}",
    summary="SSE stream for monthly report generation progress",
)
async def stream_monthly_report(
    portfolio_id: uuid.UUID,
    job_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_org_id),
):
    if not await verify_job_owner(job_id, str(org_id)):
        raise HTTPException(status_code=403, detail="Job not found")
    return await create_job_stream(request, job_id)


@router.get(
    "/model-portfolios/{portfolio_id}/monthly-report/{job_id}/pdf",
    summary="Download Monthly Report PDF",
    description="Download generated PDF. Job must be in 'done' status.",
)
async def download_monthly_report_pdf(
    portfolio_id: uuid.UUID,
    job_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_org_id),
) -> Response:
    """Download generated Monthly Report PDF from Redis cache."""
    if not await verify_job_owner(job_id, str(org_id)):
        raise HTTPException(status_code=403, detail="Job not found")

    import redis.asyncio as aioredis

    from app.core.jobs.tracker import get_redis_pool

    pool = get_redis_pool()
    r = aioredis.Redis(connection_pool=pool)
    try:
        raw_key = await r.get(f"job:{job_id}:pdf_key")
    finally:
        await r.aclose()

    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PDF not yet available. Check job status.",
        )

    pdf_storage_key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key

    from app.services.storage_client import create_storage_client

    storage = create_storage_client()
    pdf_bytes = await storage.read(pdf_storage_key)
    if pdf_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PDF file not found in storage.",
        )

    filename = f"monthly-report-{portfolio_id}-{job_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _run_monthly_generation(
    *,
    job_id: str,
    portfolio_id: str,
    organization_id: str,
    semaphore: asyncio.Semaphore,
) -> None:
    """Background task: run MonthlyReportEngine and publish SSE events."""
    from app.core.db.engine import async_session_factory
    from app.core.tenancy.middleware import set_rls_context

    try:
        async with async_session_factory() as db:
            await set_rls_context(db, uuid.UUID(organization_id))

            from vertical_engines.wealth.monthly_report import MonthlyReportEngine

            engine = MonthlyReportEngine()

            await publish_event(job_id, "started", {
                "portfolio_id": portfolio_id,
            })

            pdf_bytes = await engine.generate(
                db,
                portfolio_id=portfolio_id,
                organization_id=organization_id,
            )

            if pdf_bytes:
                # Store PDF via StorageClient
                storage_key = (
                    f"gold/{organization_id}/wealth/reports/"
                    f"monthly-{portfolio_id}-{job_id}.pdf"
                )
                try:
                    from app.services.storage_client import create_storage_client

                    storage = create_storage_client()
                    await storage.write(storage_key, pdf_bytes)

                    # Persist PDF key in Redis for download endpoint
                    import redis.asyncio as aioredis

                    from app.core.jobs.tracker import get_redis_pool

                    pool = get_redis_pool()
                    r = aioredis.Redis(connection_pool=pool)
                    try:
                        await r.set(
                            f"job:{job_id}:pdf_key",
                            storage_key,
                            ex=86400,  # 24h TTL
                        )
                    finally:
                        await r.aclose()
                except Exception:
                    logger.warning("monthly_report_storage_failed", exc_info=True)
                    storage_key = ""

                await publish_terminal_event(job_id, "done", {
                    "status": "completed",
                    "pdf_storage_key": storage_key,
                    "size_bytes": len(pdf_bytes),
                })
            else:
                await publish_terminal_event(job_id, "error", {
                    "status": "failed",
                    "error": "PDF generation returned None",
                })

    except Exception as exc:
        logger.exception("monthly_report_background_failed", job_id=job_id)
        await publish_terminal_event(job_id, "error", {"error": str(exc)})
    finally:
        semaphore.release()
