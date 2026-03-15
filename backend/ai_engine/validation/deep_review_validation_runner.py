"""Deep Review Validation Runner — 3-deal controlled benchmark.

Runs V4 for a sample of pipeline deals, evaluates output quality,
and produces a structured institutional validation report.

Hard constraints:
  • Maximum 3 deals per run
  • Read-only against existing artifacts — does NOT overwrite
  • Session-isolated per deal (same pattern as batch runners)
  • Audit-safe persistence into ``deep_review_validation_runs`` table

Note: V3 pipeline has been deprecated.  The runner now evaluates V4
quality only (V3 fields are set to None for backward-compat).
"""
from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_engine.validation.deep_review_comparator import compare_v3_vs_v4
from ai_engine.validation.delta_metrics import (
    compute_aggregate_score,
    compute_engine_quality_score,
    compute_institutional_decision,
)
from ai_engine.validation.validation_schema import (
    DealValidationResult,
    DeepReviewValidationReport,
)

logger = logging.getLogger(__name__)

_MAX_SAMPLE = 3


def run_ic_memo_eval_framework(*args, **kwargs):
    """Compatibility wrapper for the new hybrid IC memo eval framework."""
    from ai_engine.validation.eval_runner import run_ic_memo_eval

    return run_ic_memo_eval(*args, **kwargs)


# ═══════════════════════════════════════════════════════════════════
#  Public entry point
# ═══════════════════════════════════════════════════════════════════

def run_deep_review_validation_sample(
    db: Session,
    *,
    fund_id: uuid.UUID,
    deal_ids: list[uuid.UUID] | None = None,
    sample_size: int = 3,
    actor_id: str = "validation-harness",
) -> DeepReviewValidationReport:
    """Run the V3-vs-V4 benchmark for up to 3 pipeline deals.

    Parameters
    ----------
    db : Session
        Database session (caller manages transaction boundaries).
    fund_id : UUID
        Fund scope.
    deal_ids : list[UUID], optional
        Explicit deal IDs to benchmark.  If None, auto-selects.
    sample_size : int
        Number of deals to benchmark (capped at 3).
    actor_id : str
        Audit trail actor.

    Returns
    -------
    DeepReviewValidationReport

    """
    from app.domains.credit.modules.deals.models import PipelineDeal as Deal

    sample_size = min(sample_size, _MAX_SAMPLE)
    now = dt.datetime.now(dt.UTC)
    run_id = uuid.uuid4()

    logger.info(
        "VALIDATION_START run_id=%s fund_id=%s sample_size=%d explicit_deals=%s",
        run_id, fund_id, sample_size, deal_ids,
    )

    # ── Resolve deal list ────────────────────────────────────────
    if deal_ids:
        selected_ids = deal_ids[:sample_size]
    else:
        rows = db.execute(
            select(Deal.id)
            .where(
                Deal.fund_id == fund_id,
                Deal.deal_folder_path.is_not(None),
            )
            .order_by(Deal.created_at.asc())
            .limit(sample_size),
        ).scalars().all()
        selected_ids = list(rows)

    if not selected_ids:
        report = DeepReviewValidationReport(
            run_id=run_id,
            started_at=now,
            completed_at=dt.datetime.now(dt.UTC),
            deals_tested=0,
            winner="N/A",
            institutional_decision="No eligible deals found for validation.",
        )
        return report

    # ── Run per-deal benchmarks (session-isolated) ───────────────
    SessionLocal = async_session_factory
    deal_results: list[DealValidationResult] = []

    for deal_id in selected_ids:
        try:
            with SessionLocal() as session:
                result = _benchmark_single_deal(
                    session,
                    fund_id=fund_id,
                    deal_id=deal_id,
                    actor_id=actor_id,
                )
                # Commit only the V3/V4 runs (if they succeeded and wrote data)
                if result.v3_error is None or result.v4_error is None:
                    session.commit()
                deal_results.append(result)
        except Exception as exc:
            logger.warning("VALIDATION_DEAL_FAILED deal=%s error=%s", deal_id, exc)
            deal_results.append(
                DealValidationResult(
                    deal_id=str(deal_id),
                    v3_error=str(exc),
                    v4_error=str(exc),
                ),
            )

    # ── Compute aggregate score ──────────────────────────────────
    aggregate = compute_aggregate_score(deal_results)
    decision = compute_institutional_decision(aggregate)

    completed_at = dt.datetime.now(dt.UTC)
    report = DeepReviewValidationReport(
        run_id=run_id,
        started_at=now,
        completed_at=completed_at,
        deals_tested=len(deal_results),
        deal_results=deal_results,
        aggregate_score=aggregate,
        winner=aggregate.engine_winner,
        institutional_decision=decision,
    )

    # ── Persist to audit table ───────────────────────────────────
    _persist_validation_run(db, report)
    db.commit()

    logger.info(
        "VALIDATION_COMPLETE run_id=%s deals=%d winner=%s confidence=%.2f",
        run_id, len(deal_results), aggregate.engine_winner, aggregate.confidence,
    )

    return report


# ═══════════════════════════════════════════════════════════════════
#  Per-deal benchmark
# ═══════════════════════════════════════════════════════════════════

def _benchmark_single_deal(
    db: Session,
    *,
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    actor_id: str,
) -> DealValidationResult:
    """Run V4 for one deal and evaluate quality.

    V3 has been deprecated — v3 fields are set to None for backward
    compatibility with the DealValidationResult schema.
    """
    from app.domains.credit.modules.ai.models import (
        MemoChapter,
        MemoEvidencePack,
    )
    from vertical_engines.credit.deep_review import run_deal_deep_review_v4

    deal_name: str | None = None
    v4_result: dict[str, Any] | None = None
    v4_error: str | None = None

    # ── Run V4 ───────────────────────────────────────────────────
    try:
        v4_result = run_deal_deep_review_v4(
            db, fund_id=fund_id, deal_id=deal_id, actor_id=actor_id, force=True,
        )
        if v4_result.get("error"):
            v4_error = v4_result["error"]
        deal_name = v4_result.get("dealName")
    except Exception as exc:
        logger.warning("V4_RUN_FAILED deal=%s: %s", deal_id, exc)
        v4_error = str(exc)

    # If V4 failed, return early
    if v4_result is None:
        return DealValidationResult(
            deal_id=str(deal_id),
            deal_name=deal_name,
            v3_error="V3 deprecated",
            v4_error=v4_error,
        )

    # ── Load persisted V4 artifacts for quality evaluation ─────────
    v4_evidence_pack: dict[str, Any] | None = None
    v4_chapters: list[dict[str, Any]] = []

    try:
        # V4 evidence pack
        pack_row = db.execute(
            select(MemoEvidencePack).where(
                MemoEvidencePack.deal_id == deal_id,
                MemoEvidencePack.fund_id == fund_id,
                MemoEvidencePack.is_current == True,  # noqa: E712
            ).order_by(MemoEvidencePack.generated_at.desc()).limit(1),
        ).scalar_one_or_none()
        if pack_row:
            v4_evidence_pack = pack_row.evidence_json

            # V4 chapters
            ch_rows = db.execute(
                select(MemoChapter).where(
                    MemoChapter.evidence_pack_id == pack_row.id,
                    MemoChapter.is_current == True,  # noqa: E712
                ).order_by(MemoChapter.chapter_number),
            ).scalars().all()
            v4_chapters = [
                {
                    "chapter_number": ch.chapter_number,
                    "chapter_tag": ch.chapter_tag,
                    "chapter_title": ch.chapter_title,
                    "content_md": ch.content_md,
                    "model_version": ch.model_version,
                    "token_count_output": ch.token_count_output,
                }
                for ch in ch_rows
            ]
    except Exception as exc:
        logger.warning("ARTIFACT_LOAD_PARTIAL deal=%s: %s", deal_id, exc)

    # ── Compute delta (V3 side is empty — V3 deprecated) ─────────
    v4_safe = v4_result or {}

    delta = compare_v3_vs_v4(
        {}, v4_safe,
        v3_risk_flags=[],
        v3_im_draft=None,
        v4_evidence_pack=v4_evidence_pack,
        v4_chapters=v4_chapters,
    )

    engine_score = compute_engine_quality_score(delta)

    return DealValidationResult(
        deal_id=str(deal_id),
        deal_name=deal_name,
        v3_version_tag=None,
        v4_version_tag=v4_safe.get("versionTag") or v4_safe.get("pipelineVersion"),
        v3_error="V3 deprecated",
        v4_error=v4_error,
        delta=delta,
        engine_score=engine_score,
    )


# ═══════════════════════════════════════════════════════════════════
#  Audit Persistence
# ═══════════════════════════════════════════════════════════════════

def _persist_validation_run(
    db: Session,
    report: DeepReviewValidationReport,
) -> None:
    """Persist each deal result into the audit table."""
    from app.domains.credit.modules.ai.models import DeepReviewValidationRun

    for dr in report.deal_results:
        row = DeepReviewValidationRun(
            id=uuid.uuid4(),
            fund_id=None,
            run_id=report.run_id,
            created_by="validation-harness",
            updated_by="validation-harness",
            deal_id=uuid.UUID(dr.deal_id) if dr.deal_id else None,
            v3_version_tag=dr.v3_version_tag,
            v4_version_tag=dr.v4_version_tag,
            delta_json=dr.delta.model_dump(mode="json") if dr.delta else {},
            winner=dr.engine_score.engine_winner if dr.engine_score else "N/A",
            engine_score_json=dr.engine_score.model_dump(mode="json") if dr.engine_score else {},
            aggregate_winner=report.winner,
            institutional_decision=report.institutional_decision,
        )
        db.add(row)

    logger.info(
        "VALIDATION_PERSISTED run_id=%s rows=%d", report.run_id, len(report.deal_results),
    )
