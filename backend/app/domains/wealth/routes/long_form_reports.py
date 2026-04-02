"""Long-Form Report API route — trigger generation with SSE progress.

POST /reporting/model-portfolios/{portfolio_id}/long-form-report
  → dispatches async generation, returns SSE stream with per-chapter progress.
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
            detail=f"Too many concurrent long-form reports (max {_MAX_CONCURRENT})",
        )
    await sem.acquire()

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
        ),
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


@router.get(
    "/model-portfolios/{portfolio_id}/long-form-report/{job_id}/pdf",
    summary="Download Long-Form Report PDF",
    description="Download generated PDF. Job must be in 'done' status.",
)
async def download_long_form_pdf(
    portfolio_id: uuid.UUID,
    job_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_org_id),
) -> Response:
    """Return PDF bytes as application/pdf."""
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

    filename = f"long-form-dd-{portfolio_id}-{job_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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

            # Generate PDF after chapters complete
            pdf_storage_key = ""
            if result.status != "failed":
                try:
                    from vertical_engines.wealth.long_form_report.pdf_renderer import (
                        LongFormPDFRenderer,
                    )

                    renderer = LongFormPDFRenderer()
                    pdf_bytes = await renderer.render(
                        result, db=db, organization_id=organization_id,
                    )
                    if pdf_bytes:
                        from ai_engine.pipeline.storage_routing import (
                            gold_long_form_report_path,
                        )

                        pdf_storage_key = gold_long_form_report_path(
                            org_id=uuid.UUID(organization_id),
                            portfolio_id=portfolio_id,
                            job_id=job_id,
                        )
                        from app.services.storage_client import create_storage_client

                        storage = create_storage_client()
                        await storage.write(pdf_storage_key, pdf_bytes)

                        # Persist PDF key in Redis for download endpoint
                        import redis.asyncio as aioredis

                        from app.core.jobs.tracker import get_redis_pool

                        pool = get_redis_pool()
                        r = aioredis.Redis(connection_pool=pool)
                        try:
                            await r.set(
                                f"job:{job_id}:pdf_key",
                                pdf_storage_key,
                                ex=86400,  # 24h TTL
                            )
                        finally:
                            await r.aclose()

                        logger.info(
                            "long_form_pdf_stored",
                            key=pdf_storage_key,
                            size_bytes=len(pdf_bytes),
                        )

                        # Persist permanent record (survives Redis TTL)
                        try:
                            async with async_session_factory() as record_db:
                                await set_rls_context(record_db, uuid.UUID(organization_id))
                                from app.domains.wealth.models.generated_report import (
                                    WealthGeneratedReport,
                                )

                                report_record = WealthGeneratedReport(
                                    organization_id=uuid.UUID(organization_id),
                                    portfolio_id=uuid.UUID(portfolio_id),
                                    report_type="long_form_dd",
                                    job_id=job_id,
                                    storage_path=pdf_storage_key,
                                    display_filename=f"long-form-dd-{portfolio_id}.pdf",
                                    size_bytes=len(pdf_bytes),
                                    status="completed",
                                )
                                record_db.add(report_record)
                                await record_db.commit()
                        except Exception:
                            logger.warning("long_form_report_record_failed", exc_info=True)
                except Exception:
                    logger.warning("long_form_pdf_generation_failed", exc_info=True)

            await publish_terminal_event(
                job_id,
                "done" if result.status != "failed" else "error",
                {
                    "status": result.status,
                    "chapters_completed": sum(
                        1 for ch in result.chapters if ch.status == "completed"
                    ),
                    "total_chapters": len(result.chapters),
                    "pdf_storage_key": pdf_storage_key,
                    "error": result.error,
                },
            )

    except Exception as exc:
        logger.exception("long_form_report_background_failed", job_id=job_id)
        await publish_terminal_event(job_id, "error", {"error": str(exc)})
    finally:
        semaphore.release()


# ── History / permanent download endpoints ────────────────────────


@router.get(
    "/model-portfolios/{portfolio_id}/long-form-report/history",
    summary="List all generated long-form reports for a portfolio",
)
async def list_long_form_reports(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_org_id),
) -> list[dict]:
    from app.domains.wealth.models.generated_report import WealthGeneratedReport

    stmt = (
        select(WealthGeneratedReport)
        .where(
            WealthGeneratedReport.portfolio_id == portfolio_id,
            WealthGeneratedReport.report_type == "long_form_dd",
            WealthGeneratedReport.status == "completed",
        )
        .order_by(WealthGeneratedReport.generated_at.desc())
        .limit(24)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    return [
        {
            "id": str(r.id),
            "job_id": r.job_id,
            "display_filename": r.display_filename,
            "generated_at": r.generated_at.isoformat(),
            "size_bytes": r.size_bytes,
        }
        for r in rows
    ]


@router.get(
    "/model-portfolios/{portfolio_id}/long-form-report/download/{report_id}",
    summary="Download a historical long-form report PDF by record ID",
)
async def download_long_form_report_by_id(
    portfolio_id: uuid.UUID,
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_org_id),
) -> Response:
    from app.domains.wealth.models.generated_report import WealthGeneratedReport

    stmt = select(WealthGeneratedReport).where(
        WealthGeneratedReport.id == report_id,
        WealthGeneratedReport.portfolio_id == portfolio_id,
        WealthGeneratedReport.report_type == "long_form_dd",
    )
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(status_code=404, detail="Report not found")

    from app.services.storage_client import create_storage_client

    storage = create_storage_client()
    pdf_bytes = await storage.read(record.storage_path)

    if pdf_bytes is None:
        raise HTTPException(status_code=404, detail="PDF file not found in storage")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{record.display_filename}"',
        },
    )
