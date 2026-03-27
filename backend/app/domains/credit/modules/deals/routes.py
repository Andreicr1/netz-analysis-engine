from __future__ import annotations

import datetime as dt
import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from ai_engine.pipeline.storage_routing import bronze_deal_path
from app.core.db.session import get_sync_db_with_rls
from app.core.security.clerk_auth import Actor, get_actor, require_readonly_allowed
from app.domains.credit.deals.models.deals import Deal
from app.domains.credit.modules.deals import cashflow_service as cf_svc
from app.domains.credit.modules.deals import service
from app.domains.credit.modules.deals.models import DealCashflow, DealDocument, PipelineDeal
from app.domains.credit.modules.deals.schemas import (
    DealApproveOut,
    DealApproveRequest,
    DealCashflowCreate,
    DealCashflowOut,
    DealContextPatch,
    DealCreate,
    DealDecisionCreate,
    DealDecisionOut,
    DealEventOut,
    DealOut,
    DealPerformanceOut,
    DealStagePatch,
    MonitoringMetricsOut,
    Page,
    QualificationRunRequest,
    QualificationRunResponse,
)
from app.services.storage_client import StorageClient, get_storage_client

logger = logging.getLogger(__name__)

PIPELINE_DEAL_SUBFOLDERS = ["legal", "regulatory", "operational", "presentations", "financial", "memos"]

router = APIRouter(prefix="/pipeline/deals", tags=["deals"])


def _limit(limit: int = Query(50, ge=1, le=200)) -> int:
    return limit


def _offset(offset: int = Query(0, ge=0, le=10_000)) -> int:
    return offset


@router.get("", response_model=Page[DealOut])
def list_deals(
    fund_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
    stage: str | None = Query(default=None),
    is_archived: bool | None = Query(default=None),
    rejection_reason_code: str | None = Query(default=None),
) -> Page[DealOut]:
    items = service.list_deals(
        db,
        fund_id=fund_id,
        limit=limit,
        offset=offset,
        stage=stage,
        is_archived=is_archived,
        rejection_reason_code=rejection_reason_code,
    )
    return Page(items=[DealOut.model_validate(x) for x in items], limit=limit, offset=offset)



async def _build_and_save_deal_context(
    deal: PipelineDeal, payload: DealCreate, *, org_id: uuid.UUID, storage: StorageClient,
) -> None:
    """Build deal_context.json from deal record + payload extras, save to storage (best-effort)."""
    ctx = service.build_deal_context_dict(deal, payload)
    if not ctx:
        return
    import json
    path = bronze_deal_path(org_id, str(deal.id), "deal_context.json")
    try:
        await storage.write(
            path,
            json.dumps(ctx, indent=2, default=str).encode("utf-8"),
            content_type="application/json",
        )
        logger.info("Saved deal_context.json for deal %s at %s", deal.id, path)
    except Exception:
        logger.warning("Failed to save deal_context.json for deal %s — continuing anyway", deal.id, exc_info=True)


@router.post("", response_model=DealOut, status_code=status.HTTP_201_CREATED)
async def create_deal(
    fund_id: uuid.UUID,
    payload: DealCreate,
    db: Session = Depends(get_sync_db_with_rls),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    storage: StorageClient = Depends(get_storage_client),
) -> DealOut:
    deal = service.create_deal(db, fund_id=fund_id, actor=actor, data=payload)
    org_id = actor.organization_id
    deal_id_str = str(deal.id)

    # Best-effort: create storage folder structure for the deal
    # Build base path directly — bronze_deal_path requires a non-empty filename
    deal_folder_path = f"bronze/{org_id}/credit/pipeline/deals/{deal_id_str}"
    try:
        for subfolder in PIPELINE_DEAL_SUBFOLDERS:
            keep_path = f"{deal_folder_path}/{subfolder}/.keep"
            await storage.write(keep_path, b"")
        # Update deal with folder path
        deal.deal_folder_path = deal_folder_path
        db.commit()
        db.refresh(deal)
        logger.info("Created storage folders for deal %s at %s", deal.id, deal_folder_path)
    except Exception:
        logger.warning("Failed to create storage folders for deal %s — continuing anyway", deal.id, exc_info=True)
        # Still try to set the folder path even if storage creation failed
        try:
            deal.deal_folder_path = deal_folder_path
            db.commit()
            db.refresh(deal)
        except Exception:
            logger.warning("Failed to update deal_folder_path for deal %s", deal.id, exc_info=True)

    # Best-effort: build and save deal_context.json to storage
    await _build_and_save_deal_context(deal, payload, org_id=org_id, storage=storage)

    return deal


@router.post("/{deal_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_deal_document(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    category: str = Query(default="other"),
    file: UploadFile = File(...),
    db: Session = Depends(get_sync_db_with_rls),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    storage: StorageClient = Depends(get_storage_client),
):
    """Upload a document to a deal's storage folder with category-based organization."""
    # Validate category
    valid_categories = PIPELINE_DEAL_SUBFOLDERS + ["other"]
    if category not in valid_categories:
        category = "other"

    # Find the deal
    stmt = select(PipelineDeal).where(
        PipelineDeal.fund_id == fund_id,
        PipelineDeal.id == deal_id,
    )
    deal = db.execute(stmt).scalar_one_or_none()
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")

    org_id = actor.organization_id
    # Use bronze_deal_path for category subfolder, then append filename
    # (filename is user input — StorageClient._validate_path rejects traversal)
    category_path = bronze_deal_path(org_id, str(deal_id), category)
    storage_path = f"{category_path}/{file.filename}"

    # Read file data
    data = await file.read()

    # Upload to storage
    try:
        await storage.write(
            storage_path,
            data,
            content_type=file.content_type or "application/octet-stream",
        )
    except Exception as exc:
        logger.error("Failed to upload %s: %s", storage_path, exc, exc_info=True)
        raise HTTPException(status_code=502, detail="Failed to upload file to storage")

    # Create or update document record in DB
    existing_doc = db.execute(
        select(DealDocument).where(
            DealDocument.deal_id == deal_id,
            DealDocument.blob_path == storage_path,
        ),
    ).scalar_one_or_none()

    if existing_doc:
        existing_doc.document_type = category.upper()
        existing_doc.filename = file.filename
        existing_doc.status = "registered"
        doc = existing_doc
    else:
        doc = DealDocument(
            fund_id=fund_id,
            deal_id=deal_id,
            document_type=category.upper(),
            filename=file.filename,
            blob_container="storage",
            blob_path=storage_path,
            status="registered",
            created_by=actor.actor_id,
            updated_by=actor.actor_id,
        )
        db.add(doc)

    db.commit()
    db.refresh(doc)

    return {
        "document_id": str(doc.id),
        "blob_path": storage_path,
        "category": category,
        "filename": file.filename,
    }


@router.patch("/{deal_id}/context")
async def patch_deal_context(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    payload: DealContextPatch,
    db: Session = Depends(get_sync_db_with_rls),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    storage: StorageClient = Depends(get_storage_client),
):
    """Merge investment parameters into the deal's deal_context.json in storage (best-effort).

    This endpoint does NOT create new DB columns — all data lives in storage only.
    """
    import json

    stmt = select(PipelineDeal).where(
        PipelineDeal.fund_id == fund_id,
        PipelineDeal.id == deal_id,
    )
    deal = db.execute(stmt).scalar_one_or_none()
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")

    org_id = actor.organization_id
    path = bronze_deal_path(org_id, str(deal_id), "deal_context.json")

    # Load existing deal_context.json (if any)
    existing_ctx: dict = {}
    try:
        data = await storage.read(path)
        existing_ctx = json.loads(data.decode("utf-8"))
    except Exception:
        logger.debug("No existing deal_context.json for deal %s — will create new", deal_id)

    # Merge investment_context fields from payload
    inv_ctx = existing_ctx.get("investment_context", {})
    patch_data = payload.model_dump(exclude_none=True)

    if "geography" in patch_data:
        existing_ctx["geography"] = patch_data["geography"]
    if "currency" in patch_data:
        inv_ctx["currency"] = patch_data["currency"]
    if "commitment_usd" in patch_data:
        inv_ctx.setdefault("commitment", {})["amount_usd"] = patch_data["commitment_usd"]
    if "portfolio_weight_max" in patch_data:
        inv_ctx.setdefault("commitment", {})["portfolio_weight_max"] = patch_data["portfolio_weight_max"]
    if "return_target_net" in patch_data:
        inv_ctx["return_target"] = {"net_irr": patch_data["return_target_net"]}
    if "redemption_terms" in patch_data:
        inv_ctx.setdefault("liquidity_terms", {})["redemption"] = patch_data["redemption_terms"]
    if "liquidity_gate" in patch_data:
        inv_ctx.setdefault("liquidity_terms", {})["gate"] = patch_data["liquidity_gate"]
    if "borrower" in patch_data:
        existing_ctx["borrower"] = patch_data["borrower"]

    if inv_ctx:
        existing_ctx["investment_context"] = inv_ctx

    # Save merged context
    try:
        await storage.write(
            path,
            json.dumps(existing_ctx, indent=2, default=str).encode("utf-8"),
            content_type="application/json",
        )
    except Exception:
        logger.warning("Failed to save deal_context.json for deal %s — continuing anyway", deal.id, exc_info=True)
        raise HTTPException(status_code=502, detail="Failed to save deal context to storage")

    return {"status": "ok", "blob_path": path}


@router.patch("/{deal_id}/stage", response_model=DealOut)
def patch_deal_stage(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    payload: DealStagePatch,
    db: Session = Depends(get_sync_db_with_rls),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
) -> DealOut:
    try:
        deal = service.patch_stage(db, fund_id=fund_id, actor=actor, deal_id=deal_id, patch=payload)
        return DealOut.model_validate(deal)
    except NoResultFound:
        raise HTTPException(status_code=404, detail="Deal not found")


@router.post("/{deal_id}/decisions", response_model=DealDecisionOut, status_code=status.HTTP_201_CREATED)
def create_decision(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    payload: DealDecisionCreate,
    db: Session = Depends(get_sync_db_with_rls),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
) -> DealDecisionOut:
    try:
        decision = service.decide(db, fund_id=fund_id, actor=actor, deal_id=deal_id, payload=payload)
        return DealDecisionOut.model_validate(decision)
    except NoResultFound:
        raise HTTPException(status_code=404, detail="Deal not found")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid outcome")


@router.post("/qualification/run", response_model=QualificationRunResponse)
def run_qualification(
    fund_id: uuid.UUID,
    payload: QualificationRunRequest,
    db: Session = Depends(get_sync_db_with_rls),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
) -> QualificationRunResponse:
    if payload.deal_id is None:
        raise HTTPException(status_code=400, detail="deal_id is required")
    try:
        deal, results, auto_archived = service.run_qualification(db, fund_id=fund_id, actor=actor, req=payload)
    except NoResultFound:
        raise HTTPException(status_code=404, detail="Deal not found")
    return QualificationRunResponse(deal=deal, results=results, auto_archived=auto_archived)


@router.post("/{deal_id}/approve", response_model=DealApproveOut, status_code=status.HTTP_201_CREATED)
def approve_deal(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    payload: DealApproveRequest,
    db: Session = Depends(get_sync_db_with_rls),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
) -> DealApproveOut:
    try:
        deal, active_investment_id = service.approve_pipeline_deal(
            db, fund_id=fund_id, actor=actor, deal_id=deal_id, payload=payload,
        )
    except NoResultFound:
        raise HTTPException(status_code=404, detail="Deal not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return DealApproveOut(
        pipeline_deal=deal,
        portfolio_deal_id=deal.approved_deal_id,
        active_investment_id=active_investment_id,
        approved_at=deal.approved_at,
        approved_by=deal.approved_by,
    )


@router.get("/{deal_id}/events", response_model=Page[DealEventOut])
def list_pipeline_deal_events(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
) -> Page[DealEventOut]:
    items = service.list_deal_events(
        db, fund_id=fund_id, pipeline_deal_id=deal_id, limit=limit, offset=offset,
    )
    return Page(items=[DealEventOut.model_validate(x) for x in items], limit=limit, offset=offset)


# ── Deal Cashflows ───────────────────────────────────────────────────

VALID_FLOW_TYPES = {
    "disbursement", "capital_call", "repayment_principal",
    "repayment_interest", "distribution", "fee",
}


def _get_deal_or_404(db: Session, *, fund_id: uuid.UUID, deal_id: uuid.UUID) -> Deal:
    stmt = select(Deal).where(Deal.id == deal_id, Deal.fund_id == fund_id)
    deal = db.execute(stmt).scalar_one_or_none()
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


@router.get("/{deal_id}/cashflows", response_model=Page[DealCashflowOut])
def list_deal_cashflows(
    deal_id: uuid.UUID,
    fund_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
    _actor: Actor = Depends(get_actor),
) -> Page[DealCashflowOut]:
    stmt = (
        select(DealCashflow)
        .where(DealCashflow.deal_id == deal_id, DealCashflow.fund_id == fund_id)
        .order_by(DealCashflow.flow_date.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = db.execute(stmt).scalars().all()
    total = db.execute(
        select(func.count())
        .select_from(DealCashflow)
        .where(DealCashflow.deal_id == deal_id, DealCashflow.fund_id == fund_id),
    ).scalar() or 0
    return Page(
        items=[DealCashflowOut.model_validate(r) for r in rows],
        limit=limit,
        offset=offset,
    )


@router.post("/{deal_id}/cashflows", response_model=DealCashflowOut, status_code=status.HTTP_201_CREATED)
def create_cashflow(
    deal_id: uuid.UUID,
    fund_id: uuid.UUID,
    body: DealCashflowCreate,
    db: Session = Depends(get_sync_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> DealCashflowOut:
    if body.flow_type not in VALID_FLOW_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid flow_type '{body.flow_type}'. Must be one of: {', '.join(sorted(VALID_FLOW_TYPES))}")
    _get_deal_or_404(db, fund_id=fund_id, deal_id=deal_id)
    cashflow = DealCashflow(
        deal_id=deal_id,
        fund_id=fund_id,
        flow_type=body.flow_type,
        amount=body.amount,
        currency=body.currency,
        flow_date=body.flow_date,
        description=body.description,
        reference=body.reference,
        created_by=actor.actor_id,
        updated_by=actor.actor_id,
    )
    db.add(cashflow)
    db.flush()
    return DealCashflowOut.model_validate(cashflow)


@router.patch("/{deal_id}/cashflows/{cashflow_id}", response_model=DealCashflowOut)
def update_cashflow(
    deal_id: uuid.UUID,
    cashflow_id: uuid.UUID,
    fund_id: uuid.UUID,
    body: DealCashflowCreate,
    db: Session = Depends(get_sync_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> DealCashflowOut:
    stmt = select(DealCashflow).where(
        DealCashflow.id == cashflow_id, DealCashflow.deal_id == deal_id,
    )
    cashflow = db.execute(stmt).scalar_one_or_none()
    if cashflow is None:
        raise HTTPException(status_code=404, detail="Cashflow not found")
    if body.flow_type not in VALID_FLOW_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid flow_type '{body.flow_type}'. Must be one of: {', '.join(sorted(VALID_FLOW_TYPES))}")
    cashflow.flow_type = body.flow_type
    cashflow.amount = body.amount
    cashflow.currency = body.currency
    cashflow.flow_date = body.flow_date
    cashflow.description = body.description
    cashflow.reference = body.reference
    cashflow.updated_by = actor.actor_id
    db.flush()
    return DealCashflowOut.model_validate(cashflow)


@router.delete("/{deal_id}/cashflows/{cashflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cashflow(
    deal_id: uuid.UUID,
    cashflow_id: uuid.UUID,
    fund_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> None:
    stmt = select(DealCashflow).where(
        DealCashflow.id == cashflow_id, DealCashflow.deal_id == deal_id,
    )
    cashflow = db.execute(stmt).scalar_one_or_none()
    if cashflow is None:
        raise HTTPException(status_code=404, detail="Cashflow not found")
    db.delete(cashflow)
    db.flush()


@router.get("/{deal_id}/performance", response_model=DealPerformanceOut)
def get_deal_performance(
    deal_id: uuid.UUID,
    fund_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    _actor: Actor = Depends(get_actor),
) -> DealPerformanceOut:
    metrics = cf_svc.calculate_performance(db, fund_id=fund_id, deal_id=deal_id)
    count = db.execute(
        select(func.count())
        .select_from(DealCashflow)
        .where(DealCashflow.deal_id == deal_id, DealCashflow.fund_id == fund_id),
    ).scalar() or 0
    return DealPerformanceOut(deal_id=deal_id, cashflow_count=count, **metrics)


@router.get("/{deal_id}/monitoring", response_model=MonitoringMetricsOut)
def get_deal_monitoring(
    deal_id: uuid.UUID,
    fund_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    _actor: Actor = Depends(get_actor),
) -> MonitoringMetricsOut:
    metrics = cf_svc.calculate_portfolio_monitoring_metrics(db, fund_id=fund_id, deal_id=deal_id)
    return MonitoringMetricsOut(
        deal_id=deal_id,
        computed_at=dt.datetime.now(dt.UTC),
        **metrics,
    )

