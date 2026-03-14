"""AI Extraction sub-router — pipeline ingest, extraction pipeline, ingest jobs."""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_engine.intelligence.pipeline_intelligence import run_pipeline_ingest
from app.core.db.engine import get_db
from app.core.security.auth import Actor
from app.core.security.clerk_auth import get_actor, require_readonly_allowed, require_roles
from app.domains.credit.modules.ai.schemas import PipelineIngestResponse
from app.shared.enums import Role

router = APIRouter()


@router.post("/pipeline/ingest", response_model=PipelineIngestResponse)
def ingest_pipeline_intelligence(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM])),
) -> PipelineIngestResponse:
    result = run_pipeline_ingest(db, fund_id=fund_id, actor_id=actor.actor_id)
    as_of = dt.datetime.fromisoformat(str(result["asOf"]))
    return PipelineIngestResponse(
        asOf=as_of,
        deals=int(result["deals"]),
        dealDocuments=int(result["dealDocuments"]),
        profiles=int(result["profiles"]),
        briefs=int(result["briefs"]),
        alerts=int(result["alerts"]),
    )


@router.post("/pipeline/ingest/full")
def trigger_full_pipeline_ingest(
    fund_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    batch_size: int = Query(default=50, ge=1, le=200),
    deal_ids: list[uuid.UUID] | None = Body(default=None, embed=True),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP])),
):
    """Trigger the full canonical pipeline ingest (scan -> discover -> bridge -> ingest).

    Dispatches to Service Bus when USE_SERVICE_BUS=True, otherwise runs
    in-process via BackgroundTasks.
    """
    from app.services.azure.pipeline_dispatch import dispatch_ingest

    return dispatch_ingest(
        background_tasks=background_tasks,
        fund_id=fund_id,
        deal_ids=deal_ids,
        batch_size=batch_size,
        actor_id=actor.actor_id,
    )


@router.post("/pipeline/extract/run")
def trigger_extraction_pipeline(
    background_tasks: BackgroundTasks,
    source: str = Query(
        default="deals",
        description="'deals' | 'fund-data' | 'market-data' | 'all'",
    ),
    deals_filter: str = Query(
        default="",
        description="Comma-separated partial item names (empty = all items in source)",
    ),
    dry_run: bool = Query(default=False),
    skip_bootstrap: bool = Query(default=False),
    skip_prepare: bool = Query(default=False),
    skip_embed: bool = Query(default=False),
    skip_enrich: bool = Query(default=False),
    no_index: bool = Query(default=False),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN])),
):
    """Trigger the full cu-pdf-prepare extraction pipeline.

    Dispatches to Service Bus when USE_SERVICE_BUS=True, otherwise runs
    in-process via BackgroundTasks.
    """
    from ai_engine.extraction.extraction_orchestrator import _new_job
    from app.services.azure.pipeline_dispatch import dispatch_extraction

    if source not in ("deals", "fund-data", "market-data", "all"):
        raise HTTPException(status_code=422, detail=f"Invalid source '{source}'. Use: deals | fund-data | market-data | all")

    job_id = _new_job(source, deals_filter)

    return dispatch_extraction(
        background_tasks=background_tasks,
        source=source,
        deals_filter=deals_filter,
        dry_run=dry_run,
        skip_bootstrap=skip_bootstrap,
        skip_prepare=skip_prepare,
        skip_embed=skip_embed,
        skip_enrich=skip_enrich,
        no_index=no_index,
        job_id=job_id,
        actor_id=actor.actor_id,
    )


@router.get("/pipeline/extract/status/{job_id}")
def get_extraction_status(
    job_id: str,
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM])),
):
    """Return the current status of an extraction pipeline job."""
    from ai_engine.extraction.extraction_orchestrator import get_job_status
    return get_job_status(job_id)


@router.get("/pipeline/extract/jobs")
def list_extraction_jobs(
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM])),
):
    """Return the last 50 extraction pipeline jobs, most recent first."""
    from ai_engine.extraction.extraction_orchestrator import list_pipeline_jobs
    return {"jobs": list_pipeline_jobs()}


@router.get("/pipeline/extract/sources")
def list_extraction_sources(
    source: str = Query(
        default="deals",
        description="'deals' | 'fund-data' | 'market-data'",
    ),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP])),
):
    """List item folders currently in the specified Azure Blob input container."""
    from ai_engine.extraction.extraction_orchestrator import (
        SOURCE_CONFIG,
        get_blob_service,
        list_source_folders,
    )
    if source not in SOURCE_CONFIG:
        raise HTTPException(status_code=422, detail=f"Invalid source '{source}'")
    try:
        blob_service = get_blob_service()
        container    = SOURCE_CONFIG[source]["input_container"]
        items        = list_source_folders(blob_service, container)
        return {"source": source, "container": container, "items": items, "count": len(items)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/pipeline/ingest/jobs/latest")
def get_latest_ingest_job(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
):
    """Return the most recent PipelineIngestJob for the given fund."""
    from app.domains.credit.modules.ai.ingest_job_model import PipelineIngestJob
    from app.domains.credit.modules.ai.schemas import IngestJobOut

    row = db.execute(
        select(PipelineIngestJob)
        .where(PipelineIngestJob.fund_id == str(fund_id))
        .order_by(PipelineIngestJob.started_at.desc())
        .limit(1),
    ).scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="No ingest jobs found for this fund.")

    return IngestJobOut.from_orm_row(row)


@router.get("/pipeline/ingest/jobs/{job_id}")
def get_ingest_job(
    fund_id: uuid.UUID,
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
):
    """Return a specific PipelineIngestJob by ID."""
    from app.domains.credit.modules.ai.ingest_job_model import PipelineIngestJob
    from app.domains.credit.modules.ai.schemas import IngestJobOut

    row = db.execute(
        select(PipelineIngestJob)
        .where(
            PipelineIngestJob.id == job_id,
            PipelineIngestJob.fund_id == str(fund_id),
        ),
    ).scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="Ingest job not found.")

    return IngestJobOut.from_orm_row(row)


# ── Standalone bootstrap + reanalyze endpoints ────────────────────────


@router.post("/pipeline/deals/{deal_id}/bootstrap")
def trigger_deal_bootstrap(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.INVESTMENT_TEAM])),
):
    """Run entity bootstrap for a single deal (async, returns 202).

    Extracts fund entities (aliases, vehicles, roles, key terms) from the
    deal's PDF documents using Mistral OCR + embedding filter + Cohere Rerank.
    """
    from app.domains.credit.modules.ai.models import DocumentRegistry
    from app.domains.credit.modules.deals.models import PipelineDeal

    # Look up deal name
    deal = db.execute(
        select(PipelineDeal.deal_name)
        .where(PipelineDeal.id == deal_id, PipelineDeal.fund_id == str(fund_id)),
    ).scalar_one_or_none()

    if deal is None:
        raise HTTPException(status_code=404, detail="Pipeline deal not found.")

    deal_name = deal

    # Look up blob paths for this deal's PDFs
    rows = db.execute(
        select(DocumentRegistry.container_name, DocumentRegistry.blob_path)
        .where(DocumentRegistry.fund_id == str(fund_id)),
    ).all()

    blob_pairs = [
        (r[0], r[1]) for r in rows
        if deal_name in r[1] and r[1].lower().endswith(".pdf")
    ][:5]

    if not blob_pairs:
        raise HTTPException(status_code=404, detail="No PDF documents found for this deal.")

    def _run_bootstrap():
        import asyncio

        from ai_engine.extraction.entity_bootstrap import async_bootstrap_deal

        return asyncio.run(async_bootstrap_deal(
            deal_name=deal_name,
            blob_paths=blob_pairs,
            max_pdfs=5,
        ))

    background_tasks.add_task(_run_bootstrap)

    return {
        "dealId": str(deal_id),
        "dealName": deal_name,
        "status": "accepted",
        "pdfCount": len(blob_pairs),
        "message": f"Entity bootstrap started for '{deal_name}' ({len(blob_pairs)} PDFs).",
    }


@router.post("/pipeline/deals/{deal_id}/reanalyze")
def trigger_deal_reanalyze(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.INVESTMENT_TEAM])),
):
    """Re-run AI analysis for a single deal without re-ingesting documents (async, returns 202).

    Useful after manual corrections, additional documents, or updated fund context.
    """
    from app.domains.credit.modules.deals.models import PipelineDeal

    deal = db.execute(
        select(PipelineDeal.deal_name)
        .where(PipelineDeal.id == deal_id, PipelineDeal.fund_id == str(fund_id)),
    ).scalar_one_or_none()

    if deal is None:
        raise HTTPException(status_code=404, detail="Pipeline deal not found.")

    def _run_reanalyze():
        from ai_engine.ingestion.domain_ingest_orchestrator import reanalyze_deal

        with async_session_factory() as session:
            reanalyze_deal(session, pipeline_deal_id=deal_id)

    background_tasks.add_task(_run_reanalyze)

    return {
        "dealId": str(deal_id),
        "dealName": deal,
        "status": "accepted",
        "message": f"Deal reanalysis started for '{deal}'.",
    }
