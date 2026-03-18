"""AI Deep Review V4 sub-router — trigger, status, reset, validate."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_engine.validation.deep_review_validation_runner import run_deep_review_validation_sample
from ai_engine.validation.eval_runner import run_ic_memo_eval
from ai_engine.validation.validation_schema import (
    EvalRunRequest,
    EvalRunResponse,
    ValidationSampleRequest,
    ValidationSampleResponse,
)
from app.core.db.session import get_sync_db_with_rls
from app.core.security.clerk_auth import Actor, require_roles
from app.domains.credit.modules.ai._helpers import _utcnow
from app.domains.credit.modules.ai.schemas import (
    DeepReviewV4BatchResponse,
    DeepReviewV4Request,
)
from app.domains.credit.modules.deals.models import Deal
from app.shared.enums import Role
from vertical_engines.credit.deep_review import async_run_all_deals_deep_review_v4

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/pipeline/deals/{deal_id}/deep-review-v4")
async def trigger_deal_deep_review_v4(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    body: DeepReviewV4Request | None = None,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.INVESTMENT_TEAM])),
) -> dict:
    """Kick off V4 deep review asynchronously."""
    import logging

    from sqlalchemy import text as _sa_text

    log = logging.getLogger("ai.deep_review_v4")
    actor = body.actor_id if body else "ai-engine"
    force = body.force if body else False

    try:
        db.execute(
            _sa_text(
                "UPDATE pipeline_deals "
                "SET intelligence_status = CAST(:s AS intelligence_status_enum) "
                "WHERE id = :id AND fund_id = :fid",
            ),
            {"s": "PROCESSING", "id": str(deal_id), "fid": str(fund_id)},
        )
        db.commit()
        log.info("V4_STATUS_PROCESSING deal_id=%s", deal_id)
    except Exception:
        db.rollback()

    from app.services.azure.pipeline_dispatch import dispatch_deep_review

    result = await dispatch_deep_review(
        background_tasks=background_tasks,
        fund_id=fund_id,
        deal_id=deal_id,
        actor=actor,
        force=force,
    )

    if result.get("status") == "already_in_progress":
        return JSONResponse(
            status_code=409,
            content={
                "dealId": str(deal_id),
                "status": "already_in_progress",
                "message": result.get("message", "A deep review is already running for this deal."),
            },
        )

    return JSONResponse(
        status_code=202,
        content={
            "dealId": str(deal_id),
            "status": "accepted",
            "dispatch": result.get("dispatch", "unknown"),
            "message": "Deep review started. Poll /deep-review-status for progress.",
        },
    )


@router.post("/pipeline/deep-review-v4", response_model=DeepReviewV4BatchResponse)
async def trigger_pipeline_deep_review_v4(
    fund_id: uuid.UUID,
    body: DeepReviewV4Request | None = None,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.INVESTMENT_TEAM])),
) -> DeepReviewV4BatchResponse:
    """Run V4 deep review for ALL pipeline deals (async parallel DAG)."""
    actor = body.actor_id if body else "ai-engine"
    force = body.force if body else False
    try:
        result = await async_run_all_deals_deep_review_v4(
            db, fund_id=fund_id, actor_id=actor, force=force,
        )
    except Exception as exc:
        logger.error(
            "deep-review-v4-batch FAILED fund_id=%s: %s",
            fund_id, exc, exc_info=True,
        )
        db.rollback()
        result = {
            "asOf": _utcnow(),
            "totalDeals": 0,
            "reviewed": 0,
            "errors": 1,
            "results": [],
        }
    return DeepReviewV4BatchResponse(**result)


@router.get("/pipeline/deals/{deal_id}/deep-review-status")
def get_deep_review_status(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> dict:
    """Lightweight status check for deep review progress."""
    from sqlalchemy import func as _sa_func

    from app.domains.credit.modules.ai.models import MemoChapter

    deal = db.execute(
        select(Deal).where(Deal.fund_id == fund_id, Deal.id == deal_id),
    ).scalar_one_or_none()
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")

    chapter_count = db.execute(
        select(_sa_func.count(MemoChapter.id))
        .where(
            MemoChapter.deal_id == deal_id,
            MemoChapter.fund_id == fund_id,
            MemoChapter.is_current == True,  # noqa: E712
        ),
    ).scalar() or 0

    return {
        "dealId": str(deal_id),
        "intelligenceStatus": deal.intelligence_status,
        "chaptersCompleted": chapter_count,
        "intelligenceGeneratedAt": (
            deal.intelligence_generated_at.isoformat()
            if deal.intelligence_generated_at
            else None
        ),
    }


@router.post("/pipeline/deals/{deal_id}/reset-status")
def reset_deal_intelligence_status(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.INVESTMENT_TEAM])),
) -> dict:
    """Reset a stuck deal back to PENDING."""
    from sqlalchemy import text as _sa_text

    deal = db.execute(
        select(Deal).where(Deal.fund_id == fund_id, Deal.id == deal_id),
    ).scalar_one_or_none()
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")

    if deal.intelligence_status not in ("PROCESSING", "FAILED"):
        return {
            "dealId": str(deal_id),
            "intelligenceStatus": deal.intelligence_status,
            "reset": False,
            "message": f"Status is already {deal.intelligence_status}, no reset needed.",
        }

    try:
        db.execute(
            _sa_text(
                "UPDATE pipeline_deals "
                "SET intelligence_status = CAST(:s AS intelligence_status_enum) "
                "WHERE id = :id AND fund_id = :fid",
            ),
            {"s": "PENDING", "id": str(deal_id), "fid": str(fund_id)},
        )
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to reset status")

    return {
        "dealId": str(deal_id),
        "intelligenceStatus": "PENDING",
        "reset": True,
        "message": "Status reset to PENDING.",
    }


@router.post("/pipeline/deals/reset-all-stuck")
def reset_all_stuck_deals(
    fund_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.INVESTMENT_TEAM])),
) -> dict:
    """Bulk-reset all deals stuck in PROCESSING back to PENDING."""
    from sqlalchemy import text as _sa_text

    result = db.execute(
        _sa_text(
            "UPDATE pipeline_deals "
            "SET intelligence_status = CAST(:s AS intelligence_status_enum) "
            "WHERE fund_id = :fid "
            "AND intelligence_status = CAST(:from_s AS intelligence_status_enum)",
        ),
        {"s": "PENDING", "fid": str(fund_id), "from_s": "PROCESSING"},
    )
    db.commit()
    count = result.rowcount

    return {
        "fundId": str(fund_id),
        "resetCount": count,
        "message": f"Reset {count} stuck deal(s) from PROCESSING to PENDING.",
    }


@router.post("/pipeline/deep-review/validate-sample", response_model=ValidationSampleResponse)
def validate_deep_review_sample(
    fund_id: uuid.UUID,
    body: ValidationSampleRequest,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.INVESTMENT_TEAM])),
) -> ValidationSampleResponse:
    """Run V4 deep review quality benchmark for up to 3 deals."""
    report = run_deep_review_validation_sample(
        db,
        fund_id=fund_id,
        deal_ids=body.deal_ids,
        sample_size=body.sample_size,
        actor_id=body.actor_id or "ai-engine",
    )
    return ValidationSampleResponse(**report.model_dump())


@router.post("/pipeline/deep-review/evaluate", response_model=EvalRunResponse)
def evaluate_ic_memo_framework(
    fund_id: uuid.UUID,
    body: EvalRunRequest,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.INVESTMENT_TEAM])),
) -> EvalRunResponse:
    """Run the hybrid IC memo eval framework."""
    report = run_ic_memo_eval(
        db,
        fund_id=fund_id,
        deal_ids=body.deal_ids,
        sample_size=body.sample_size,
        actor_id=body.actor_id or "validation-harness",
        trigger_type=body.trigger_type,
        run_mode=body.run_mode,
        golden_set_name=body.golden_set_name,
        force_rerun=body.force_rerun,
    )
    logger.info(
        "IC_MEMO_EVAL_COMPLETE run_id=%s classification=%s deals=%d",
        report.run_id,
        report.classification,
        report.summary.deals_evaluated,
    )
    return EvalRunResponse(
        run_id=report.run_id,
        classification=report.classification,
        classification_reason=report.classification_reason,
        status=report.status,
        started_at=report.started_at,
        completed_at=report.completed_at,
        summary=report.summary,
        deal_summaries=report.deal_summaries,
    )
