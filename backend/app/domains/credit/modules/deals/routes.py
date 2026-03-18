from __future__ import annotations

import logging
import re
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from app.core.db.session import get_sync_db_with_rls
from app.core.security.clerk_auth import Actor, get_actor, require_readonly_allowed
from app.domains.credit.modules.deals import service
from app.domains.credit.modules.deals.models import DealDocument, PipelineDeal
from app.domains.credit.modules.deals.schemas import (
    DealApproveOut,
    DealApproveRequest,
    DealContextPatch,
    DealCreate,
    DealDecisionCreate,
    DealDecisionOut,
    DealEventOut,
    DealOut,
    DealStagePatch,
    Page,
    QualificationRunRequest,
    QualificationRunResponse,
)
from app.services.blob_storage import upload_bytes

logger = logging.getLogger(__name__)

PIPELINE_CONTAINER = "investment-pipeline-intelligence"
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


def _slugify(name: str) -> str:
    """Convert deal name to a URL/blob-friendly slug."""
    slug = name.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "deal"


def _deal_folder_name(deal: PipelineDeal) -> str:
    """Return the deal's blob-storage folder name.

    If the deal already has a ``deal_folder_path``, extract the last
    segment (this preserves the Title-Case name used by the ingestion
    pipeline, e.g. ``"Arzan - Workforce Housing"``).  Otherwise fall
    back to the raw deal name — **no lowercasing or slug-mangling** so
    that manually-created deals match the same convention.
    """
    if deal.deal_folder_path:
        parts = deal.deal_folder_path.rstrip("/").split("/")
        return parts[-1] if len(parts) > 1 else parts[0]
    return deal.deal_name or deal.title or str(deal.id)


def _build_and_save_deal_context(deal: PipelineDeal, payload: DealCreate) -> None:
    """Build deal_context.json from deal record + payload extras, save to blob (best-effort)."""
    folder_name = _deal_folder_name(deal)
    ctx = service.build_deal_context_dict(deal, payload)
    if not ctx:
        return
    import json
    blob_name = f"{folder_name}/deal_context.json"
    try:
        upload_bytes(
            container=PIPELINE_CONTAINER,
            blob_name=blob_name,
            data=json.dumps(ctx, indent=2, default=str).encode("utf-8"),
            content_type="application/json",
            overwrite=True,
        )
        logger.info("Saved deal_context.json for deal %s at %s", deal.id, blob_name)
    except Exception:
        logger.warning("Failed to save deal_context.json for deal %s — continuing anyway", deal.id, exc_info=True)


@router.post("", response_model=DealOut, status_code=status.HTTP_201_CREATED)
def create_deal(
    fund_id: uuid.UUID,
    payload: DealCreate,
    db: Session = Depends(get_sync_db_with_rls),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
) -> DealOut:
    deal = service.create_deal(db, fund_id=fund_id, actor=actor, data=payload)

    # Best-effort: create blob folder structure for the deal
    # Use the deal name as-is (Title Case) to match existing convention
    folder_name = deal.deal_name or deal.title or str(deal.id)
    deal_folder_path = f"{PIPELINE_CONTAINER}/{folder_name}"
    try:
        for subfolder in PIPELINE_DEAL_SUBFOLDERS:
            blob_name = f"{folder_name}/{subfolder}/.keep"
            upload_bytes(
                container=PIPELINE_CONTAINER,
                blob_name=blob_name,
                data=b"",
                content_type="text/plain",
                overwrite=True,
            )
        # Update deal with folder path
        deal.deal_folder_path = deal_folder_path
        db.commit()
        db.refresh(deal)
        logger.info("Created blob folders for deal %s at %s", deal.id, deal_folder_path)
    except Exception:
        logger.warning("Failed to create blob folders for deal %s — continuing anyway", deal.id, exc_info=True)
        # Still try to set the folder path even if blob creation failed
        try:
            deal.deal_folder_path = deal_folder_path
            db.commit()
            db.refresh(deal)
        except Exception:
            logger.warning("Failed to update deal_folder_path for deal %s", deal.id, exc_info=True)

    # Best-effort: build and save deal_context.json to blob
    _build_and_save_deal_context(deal, payload)

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
):
    """Upload a document to a deal's blob folder with category-based organization."""
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

    # Derive folder name — preserves Title Case from blob storage
    folder_name = _deal_folder_name(deal)

    blob_name = f"{folder_name}/{category}/{file.filename}"

    # Read file data
    data = await file.read()

    # Upload to blob storage
    try:
        upload_bytes(
            container=PIPELINE_CONTAINER,
            blob_name=blob_name,
            data=data,
            content_type=file.content_type or "application/octet-stream",
            overwrite=True,
        )
    except Exception as exc:
        logger.error("Failed to upload blob %s: %s", blob_name, exc, exc_info=True)
        raise HTTPException(status_code=502, detail="Failed to upload file to blob storage")

    # Create or update document record in DB
    existing_doc = db.execute(
        select(DealDocument).where(
            DealDocument.deal_id == deal_id,
            DealDocument.blob_path == blob_name,
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
            blob_container=PIPELINE_CONTAINER,
            blob_path=blob_name,
            status="registered",
            created_by=actor.actor_id,
            updated_by=actor.actor_id,
        )
        db.add(doc)

    db.commit()
    db.refresh(doc)

    return {
        "document_id": str(doc.id),
        "blob_path": blob_name,
        "category": category,
        "filename": file.filename,
    }


@router.patch("/{deal_id}/context")
def patch_deal_context(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    payload: DealContextPatch,
    db: Session = Depends(get_sync_db_with_rls),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
):
    """Merge investment parameters into the deal's deal_context.json on blob (best-effort).

    This endpoint does NOT create new DB columns — all data lives in blob only.
    """
    import json

    stmt = select(PipelineDeal).where(
        PipelineDeal.fund_id == fund_id,
        PipelineDeal.id == deal_id,
    )
    deal = db.execute(stmt).scalar_one_or_none()
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")

    # Derive slug
    if deal.deal_folder_path:
        parts = deal.deal_folder_path.rstrip("/").split("/")
        slug = parts[-1] if len(parts) > 1 else parts[0]
    else:
        slug = _slugify(deal.deal_name or deal.title or str(deal.id))

    blob_name = f"{slug}/deal_context.json"

    # Load existing deal_context.json (if any)
    existing_ctx: dict = {}
    try:
        from app.services.blob_storage import blob_uri, download_bytes
        data = download_bytes(blob_uri=blob_uri(PIPELINE_CONTAINER, blob_name))
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
        upload_bytes(
            container=PIPELINE_CONTAINER,
            blob_name=blob_name,
            data=json.dumps(existing_ctx, indent=2, default=str).encode("utf-8"),
            content_type="application/json",
            overwrite=True,
        )
    except Exception:
        logger.warning("Failed to save deal_context.json for deal %s — continuing anyway", deal.id, exc_info=True)
        raise HTTPException(status_code=502, detail="Failed to save deal context to blob storage")

    return {"status": "ok", "blob_path": blob_name}


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

