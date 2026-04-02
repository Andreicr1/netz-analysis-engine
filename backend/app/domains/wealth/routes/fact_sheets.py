"""Fact-Sheet API routes — generate, list, download.

Feature-gated by ``FEATURE_WEALTH_FACT_SHEETS``.
All endpoints use get_db_with_rls and Clerk JWT authentication.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import settings
from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.models.model_portfolio import ModelPortfolio
from app.domains.wealth.routes.common import _get_content_semaphore, require_content_slot
from app.domains.wealth.schemas.fact_sheet import FactSheetGenerate
from app.shared.enums import Role

logger = structlog.get_logger()

router = APIRouter(prefix="/fact-sheets", tags=["fact-sheets"])


def _require_feature() -> None:
    """Raise 501 if fact-sheet feature is disabled."""
    if not settings.feature_wealth_fact_sheets:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Fact-sheet feature is not enabled",
        )


def _require_ic_role(actor: Actor) -> None:
    """Verify actor has INVESTMENT_TEAM or ADMIN role."""
    if not actor.has_role(Role.INVESTMENT_TEAM):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Investment Committee role required",
        )


@router.post(
    "/model-portfolios/{portfolio_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate fact-sheet PDF for a model portfolio",
)
async def generate_fact_sheet(
    portfolio_id: uuid.UUID,
    body: FactSheetGenerate | None = None,
    language: Literal["pt", "en"] = Query(default="pt", description="PDF language"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
    org_id: str = Depends(get_org_id),
) -> dict[str, Any]:
    """Trigger on-demand fact-sheet generation.

    Returns storage path and metadata for the generated PDF.
    """
    _require_feature()
    _require_ic_role(actor)

    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )

    if not portfolio.fund_selection_schema:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Portfolio has no fund selection. Run /construct first.",
        )

    fmt = body.format if body else "executive"

    # Backpressure: reject if too many concurrent content tasks
    await require_content_slot()

    def _generate() -> dict[str, Any]:
        from app.core.db.session import sync_session_factory

        with sync_session_factory() as sync_db, sync_db.begin():
            sync_db.expire_on_commit = False
            from sqlalchemy import text
            sync_db.execute(
                text("SELECT set_config('app.current_organization_id', :oid, true)"),
                {"oid": str(org_id)},
            )
            return _run_fact_sheet_generation(
                sync_db,
                portfolio_id=str(portfolio_id),
                organization_id=str(org_id),
                format=fmt,
                language=language,
            )

    try:
        gen_result = await asyncio.to_thread(_generate)

        # Async storage write (moved from sync thread — no more throwaway event loop)
        pdf_bytes = gen_result.pop("_pdf_bytes", None)
        if pdf_bytes:
            from app.services.storage_client import get_storage_client
            storage = get_storage_client()
            await storage.write(gen_result["storage_path"], pdf_bytes, content_type="application/pdf")

            # Persist permanent record
            try:
                from app.core.db.engine import async_session_factory
                from app.core.tenancy.middleware import set_rls_context
                from app.domains.wealth.models.generated_report import WealthGeneratedReport

                fact_job_id = f"fs-{portfolio_id}-{uuid.uuid4().hex[:8]}"
                async with async_session_factory() as record_db:
                    await set_rls_context(record_db, uuid.UUID(str(org_id)))
                    report_record = WealthGeneratedReport(
                        organization_id=uuid.UUID(str(org_id)),
                        portfolio_id=portfolio_id,
                        report_type="fact_sheet",
                        job_id=fact_job_id,
                        storage_path=gen_result["storage_path"],
                        display_filename=f"fact-sheet-{portfolio_id}-{fmt}.pdf",
                        size_bytes=len(pdf_bytes),
                        status="completed",
                    )
                    record_db.add(report_record)
                    await record_db.commit()
            except Exception:
                logger.warning("fact_sheet_record_failed", exc_info=True)

        return gen_result
    finally:
        _get_content_semaphore().release()


@router.get(
    "/model-portfolios/{portfolio_id}",
    summary="List generated fact-sheets for a model portfolio",
)
async def list_fact_sheets(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: str = Depends(get_org_id),
) -> dict[str, Any]:
    """List available fact-sheet PDFs for a portfolio."""
    _require_feature()

    # Check portfolio exists
    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )

    # List from storage
    from app.services.storage_client import get_storage_client

    storage = get_storage_client()
    prefix = f"gold/{org_id}/wealth/fact_sheets/{portfolio_id}"
    files = await storage.list_files(prefix)

    fact_sheets = []
    for f in files:
        if f.endswith(".pdf"):
            parts = f.split("/")
            # gold/{org_id}/wealth/fact_sheets/{portfolio_id}/{as_of}/{lang}/{format}.pdf
            if len(parts) >= 8:
                fact_sheets.append({
                    "path": f,
                    "as_of": parts[-3],
                    "language": parts[-2],
                    "format": parts[-1].replace(".pdf", ""),
                })

    return {"portfolio_id": str(portfolio_id), "fact_sheets": fact_sheets}


@router.get(
    "/{fact_sheet_path:path}/download",
    summary="Download a fact-sheet PDF",
)
async def download_fact_sheet(
    fact_sheet_path: str,
    user: CurrentUser = Depends(get_current_user),
    org_id: str = Depends(get_org_id),
) -> Response:
    """Download a fact-sheet PDF by storage path."""
    _require_feature()

    # Prevent path traversal attacks
    if ".." in fact_sheet_path:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid path",
        )

    # Verify path belongs to this org
    parts = fact_sheet_path.split("/")
    if len(parts) < 2 or parts[1] != str(org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    from app.services.storage_client import get_storage_client

    storage = get_storage_client()
    try:
        data = await storage.read(fact_sheet_path)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fact-sheet not found",
        )

    filename = fact_sheet_path.rsplit("/", maxsplit=1)[-1]
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/dd-reports/{report_id}/download",
    summary="Download DD Report PDF",
)
async def download_dd_report_pdf(
    report_id: uuid.UUID,
    language: Literal["pt", "en"] = Query(default="pt", description="PDF language"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: str = Depends(get_org_id),
) -> Response:
    """Generate and download a DD Report as PDF."""
    from sqlalchemy.orm import selectinload

    from app.domains.wealth.models.dd_report import DDReport

    result = await db.execute(
        select(DDReport)
        .options(selectinload(DDReport.chapters))
        .where(DDReport.id == report_id),
    )
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DD Report {report_id} not found",
        )

    if report.status not in ("completed", "pending_approval", "approved", "published"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"DD Report is not ready for download (status: {report.status})",
        )

    # Get fund name
    from app.domains.wealth.models.fund import Fund

    fund_result = await db.execute(
        select(Fund.name).where(Fund.fund_id == report.instrument_id),
    )
    fund_name_row = fund_result.scalar_one_or_none()
    fund_name = fund_name_row or "Unknown Fund"

    # Check R2 cache first (set on approval)
    if report.storage_path:
        try:
            from app.services.storage_client import get_storage_client
            storage = get_storage_client()
            cached_bytes = await storage.read(report.storage_path)
            if cached_bytes:
                safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", fund_name)
                filename = f"dd_report_{safe_name}_{language}.pdf"
                return Response(
                    content=cached_bytes,
                    media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'},
                )
        except Exception:
            logger.warning("dd_report_cache_miss", report_id=str(report_id), exc_info=True)
            # Fall through to on-demand generation

    # Generate PDF (prefer Playwright async, fallback to ReportLab)
    chapters_data = [
        {
            "chapter_tag": ch.chapter_tag,
            "chapter_order": ch.chapter_order,
            "content_md": ch.content_md,
        }
        for ch in sorted(report.chapters, key=lambda c: c.chapter_order)
    ]

    confidence = float(report.confidence_score) if report.confidence_score else None

    try:
        from ai_engine.pdf.generate_dd_report_pdf import generate_dd_report_pdf_async

        pdf_bytes = await generate_dd_report_pdf_async(
            fund_name=fund_name,
            report_id=str(report_id),
            chapters=chapters_data,
            confidence_score=confidence,
            decision_anchor=report.decision_anchor,
            language=language,
        )
    except Exception:
        logger.warning("playwright_dd_report_fallback_to_reportlab", exc_info=True)
        from ai_engine.pdf.generate_dd_report_pdf import generate_dd_report_pdf

        pdf_buf = generate_dd_report_pdf(
            fund_name=fund_name,
            report_id=str(report_id),
            chapters=chapters_data,
            confidence_score=confidence,
            decision_anchor=report.decision_anchor,
            language=language,
        )
        pdf_bytes = pdf_buf.read()

    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", fund_name)
    filename = f"dd_report_{safe_name}_{language}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Helpers ──────────────────────────────────────────────────────────


def _run_fact_sheet_generation(
    db: Any,
    *,
    portfolio_id: str,
    organization_id: str,
    format: str,
    language: str,
) -> dict[str, Any]:
    """Run fact-sheet generation in sync thread."""
    from ai_engine.pipeline.storage_routing import gold_fact_sheet_path
    from vertical_engines.wealth.fact_sheet import FactSheetEngine

    engine = FactSheetEngine()
    as_of = date.today()

    pdf_buf = engine.generate(
        db,
        portfolio_id=portfolio_id,
        organization_id=organization_id,
        format=format,
        language=language,
        as_of=as_of,
    )

    # Build storage path
    storage_path = gold_fact_sheet_path(
        org_id=uuid.UUID(organization_id),
        vertical="wealth",
        portfolio_id=portfolio_id,
        as_of_date=as_of.isoformat(),
        language=language,
        filename=f"{format}.pdf",
    )

    # Return bytes + path — async storage write happens in the calling async context
    return {
        "portfolio_id": portfolio_id,
        "format": format,
        "language": language,
        "as_of": as_of.isoformat(),
        "storage_path": storage_path,
        "_pdf_bytes": pdf_buf.read(),
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "completed",
    }
