from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import os
import re
import uuid
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_engine.model_config import get_model
from ai_engine.validation.eval_judge import evaluate_llm_judge
from ai_engine.validation.eval_metrics import (
    build_layer_aggregate,
    chapter_citations_from_pack,
    evaluate_decision_integrity_layer,
    evaluate_grounding_layer,
    evaluate_retrieval_layer,
)
from ai_engine.validation.validation_schema import (
    BaselineKind,
    BaselineReference,
    EvalChapterScore,
    EvalDealSummary,
    EvalRunMode,
    EvalRunReport,
    EvalRunSummary,
    GoldenApprovalStatus,
    GoldenDealManifest,
    LayerScore,
    MetricResult,
    MetricStatus,
    RegressionState,
    TriggerType,
)
from app.core.config import settings
from app.domains.credit.modules.ai.models import (
    DealIntelligenceProfile,
    DealUnderwritingArtifact,
    MemoChapter,
    MemoEvidencePack,
)
from app.domains.credit.modules.ai.models import (
    EvalChapterScore as EvalChapterScoreRow,
)
from app.domains.credit.modules.ai.models import (
    EvalRun as EvalRunRow,
)
from app.domains.credit.modules.deals.models import PipelineDeal

logger = logging.getLogger(__name__)

EXPECTED_CHAPTER_COUNT = 14
GOLDEN_ROOT = Path(__file__).resolve().parent / "golden_outputs"
PROMPTS_ROOT = Path(__file__).resolve().parents[1] / "prompts"
MODEL_STAGES = [
    "memo",
    "memo_mini",
    "critic",
    "critic_escalation",
    "tone_pass1",
    "tone_pass2",
    "eval_judge",
    "ch01_exec",
    "ch02_macro",
    "ch03_exit",
    "ch04_sponsor",
    "ch05_legal",
    "ch06_terms",
    "ch07_capital",
    "ch08_returns",
    "ch09_downside",
    "ch10_covenants",
    "ch11_risks",
    "ch12_peers",
    "ch13_recommendation",
    "ch14_governance_stress",
]


def run_ic_memo_eval(
    db: Session,
    *,
    fund_id: uuid.UUID,
    deal_ids: list[uuid.UUID] | None = None,
    sample_size: int = 3,
    actor_id: str = "validation-harness",
    trigger_type: TriggerType = TriggerType.MANUAL,
    run_mode: EvalRunMode = EvalRunMode.EVALUATE_EXISTING_ARTIFACTS,
    golden_set_name: str = "ic_memo_default",
    force_rerun: bool = False,
) -> EvalRunReport:
    started_at = dt.datetime.now(dt.UTC)
    run_id = uuid.uuid4()
    provider_manifest = _build_provider_manifest()
    prompt_manifest_hash = _compute_prompt_manifest_hash()
    model_manifest_hash = _compute_model_manifest_hash()

    selected_deals = _resolve_deals(
        db,
        fund_id=fund_id,
        deal_ids=deal_ids,
        sample_size=sample_size,
    )
    if not selected_deals:
        report = EvalRunReport(
            run_id=run_id,
            trigger_type=trigger_type,
            run_mode=run_mode,
            golden_set_name=golden_set_name,
            baseline_kind=BaselineKind.NONE,
            prompt_manifest_hash=prompt_manifest_hash,
            model_manifest_hash=model_manifest_hash,
            provider_manifest=provider_manifest,
            started_at=started_at,
            completed_at=dt.datetime.now(dt.UTC),
            classification=RegressionState.DATA_ISSUE,
            classification_reason="No eligible deals found for evaluation.",
            summary=EvalRunSummary(),
        )
        _persist_eval_run(db, fund_id, actor_id, report)
        db.commit()
        return report

    if run_mode == EvalRunMode.RUN_AND_EVALUATE or force_rerun:
        from vertical_engines.credit.deep_review import run_deal_deep_review_v4

        for deal in selected_deals:
            try:
                run_deal_deep_review_v4(
                    db,
                    fund_id=fund_id,
                    deal_id=deal.id,
                    actor_id=actor_id,
                    force=True,
                )
                db.commit()
            except Exception as exc:  # pragma: no cover - integration path
                db.rollback()
                logger.warning("IC_MEMO_EVAL_RERUN_FAILED deal_id=%s error=%s", deal.id, exc)

    deal_summaries: list[EvalDealSummary] = []
    for deal in selected_deals:
        deal_summaries.append(
            _evaluate_single_deal(
                db,
                run_id=run_id,
                fund_id=fund_id,
                deal=deal,
                golden_set_name=golden_set_name,
                provider_manifest=provider_manifest,
            ),
        )

    run_summary = _summarise_run(deal_summaries)
    classification, reason, blocking_layer = _classify_run(run_summary, deal_summaries)
    baseline_kind = _run_baseline_kind(deal_summaries)
    baseline_run_id = _run_baseline_run_id(deal_summaries)

    report = EvalRunReport(
        run_id=run_id,
        trigger_type=trigger_type,
        run_mode=run_mode,
        golden_set_name=golden_set_name,
        baseline_kind=baseline_kind,
        baseline_run_id=baseline_run_id,
        prompt_manifest_hash=prompt_manifest_hash,
        model_manifest_hash=model_manifest_hash,
        provider_manifest=provider_manifest,
        started_at=started_at,
        completed_at=dt.datetime.now(dt.UTC),
        classification=classification,
        classification_reason=reason,
        blocking_layer=blocking_layer,
        is_comparable=all(deal.is_comparable for deal in deal_summaries) if deal_summaries else False,
        deal_summaries=deal_summaries,
        summary=run_summary,
    )
    _persist_eval_run(db, fund_id, actor_id, report)
    db.commit()
    return report


def _resolve_deals(
    db: Session,
    *,
    fund_id: uuid.UUID,
    deal_ids: list[uuid.UUID] | None,
    sample_size: int,
) -> list[PipelineDeal]:
    if deal_ids:
        rows = db.execute(
            select(PipelineDeal)
            .where(PipelineDeal.fund_id == fund_id, PipelineDeal.id.in_(deal_ids))
            .order_by(PipelineDeal.created_at.asc()),
        ).scalars().all()
        return list(rows)[:sample_size]

    rows = db.execute(
        select(PipelineDeal)
        .where(PipelineDeal.fund_id == fund_id, PipelineDeal.deal_folder_path.is_not(None))
        .order_by(PipelineDeal.created_at.asc())
        .limit(sample_size),
    ).scalars().all()
    return list(rows)


def _evaluate_single_deal(
    db: Session,
    *,
    run_id: uuid.UUID,
    fund_id: uuid.UUID,
    deal: PipelineDeal,
    golden_set_name: str,
    provider_manifest: dict[str, Any],
) -> EvalDealSummary:
    pack = db.execute(
        select(MemoEvidencePack)
        .where(
            MemoEvidencePack.fund_id == fund_id,
            MemoEvidencePack.deal_id == deal.id,
            MemoEvidencePack.is_current == True,  # noqa: E712
        )
        .order_by(MemoEvidencePack.generated_at.desc())
        .limit(1),
    ).scalar_one_or_none()
    chapters = []
    if pack is not None:
        chapters = list(
            db.execute(
                select(MemoChapter)
                .where(
                    MemoChapter.fund_id == fund_id,
                    MemoChapter.deal_id == deal.id,
                    MemoChapter.evidence_pack_id == pack.id,
                    MemoChapter.is_current == True,  # noqa: E712
                )
                .order_by(MemoChapter.chapter_number.asc()),
            ).scalars().all(),
        )
    artifact = db.execute(
        select(DealUnderwritingArtifact)
        .where(
            DealUnderwritingArtifact.fund_id == fund_id,
            DealUnderwritingArtifact.deal_id == deal.id,
            DealUnderwritingArtifact.is_active == True,  # noqa: E712
        )
        .order_by(DealUnderwritingArtifact.generated_at.desc())
        .limit(1),
    ).scalar_one_or_none()
    profile = db.execute(
        select(DealIntelligenceProfile)
        .where(
            DealIntelligenceProfile.fund_id == fund_id,
            DealIntelligenceProfile.deal_id == deal.id,
        )
        .order_by(DealIntelligenceProfile.last_ai_refresh.desc())
        .limit(1),
    ).scalar_one_or_none()

    deal_name = deal.deal_name or deal.title
    if pack is None:
        return EvalDealSummary(
            deal_id=str(deal.id),
            deal_name=deal_name,
            chapter_count_found=0,
            classification=RegressionState.DATA_ISSUE,
            classification_reason="No current evidence pack found.",
        )

    evidence_pack = dict(pack.evidence_json or {})
    profile_metadata = dict((profile.metadata_json or {}) if profile and profile.metadata_json else {})
    chapter_summaries_map = {
        chapter.chapter_tag: (chapter.content_md or "")[:500]
        for chapter in chapters
    }
    golden_manifest = _load_golden_manifest(deal)
    chapter_scores: list[EvalChapterScore] = []

    if len(chapters) < EXPECTED_CHAPTER_COUNT:
        for chapter in chapters:
            chapter_scores.append(
                _build_data_issue_chapter(
                    run_id=run_id,
                    deal=deal,
                    chapter=chapter,
                    provider_manifest=provider_manifest,
                    reason=f"Partial memo detected: found {len(chapters)} of {EXPECTED_CHAPTER_COUNT} chapters.",
                ),
            )
        return _summarise_deal(
            deal=deal,
            chapters=chapters,
            chapter_scores=chapter_scores,
            baseline_kind=BaselineKind.NONE,
            comparable=False,
        )

    for chapter in chapters:
        chapter_citations = chapter_citations_from_pack(
            evidence_pack,
            chapter.chapter_tag,
            chapter.chapter_number,
        )
        layer1 = evaluate_retrieval_layer(
            chapter_tag=chapter.chapter_tag,
            chapter_text=chapter.content_md or "",
            evidence_pack=evidence_pack,
        )
        layer2 = evaluate_grounding_layer(
            chapter_tag=chapter.chapter_tag,
            chapter_text=chapter.content_md or "",
            evidence_pack=evidence_pack,
            chapter_citations=chapter_citations,
        )
        layer3 = evaluate_decision_integrity_layer(
            chapter_tag=chapter.chapter_tag,
            chapter_text=chapter.content_md or "",
            evidence_pack=evidence_pack,
            underwriting_artifact=_artifact_to_dict(artifact),
            profile_metadata=profile_metadata,
        )
        layer4 = _safe_layer4(
            chapter=chapter,
            evidence_pack=evidence_pack,
            profile_metadata=profile_metadata,
            chapter_summaries_map=chapter_summaries_map,
        )
        aggregate = build_layer_aggregate(layer1, layer2, layer3, layer4)
        baseline = _resolve_baseline(
            db,
            deal=deal,
            chapter=chapter,
            golden_manifest=golden_manifest,
        )
        classification, reason, comparison_summary = _classify_chapter(
            db,
            current_overall=aggregate.overall,
            baseline=baseline,
            chapter_text=chapter.content_md or "",
            chapter_tag=chapter.chapter_tag,
            deal_id=deal.id,
            golden_manifest=golden_manifest,
            layer1=layer1,
            layer2=layer2,
            layer3=layer3,
            layer4=layer4,
        )
        chapter_scores.append(
            EvalChapterScore(
                run_id=run_id,
                deal_id=str(deal.id),
                deal_name=deal_name,
                chapter_number=chapter.chapter_number,
                chapter_tag=chapter.chapter_tag,
                chapter_title=chapter.chapter_title,
                memo_version_tag=chapter.version_tag or pack.version_tag,
                model_version=chapter.model_version or pack.model_version,
                golden_version=baseline.golden_version,
                baseline=baseline,
                is_applicable_layer1=layer1.applicable,
                is_applicable_layer2=layer2.applicable,
                layer1=layer1,
                layer2=layer2,
                layer3=layer3,
                layer4=layer4,
                aggregate=aggregate,
                classification=classification,
                classification_reason=reason,
                comparison_summary=comparison_summary,
                provider_info=provider_manifest,
            ),
        )

    baseline_kind = _deal_baseline_kind(chapter_scores)
    comparable = all(ch.baseline.comparable for ch in chapter_scores) if chapter_scores else False
    return _summarise_deal(
        deal=deal,
        chapters=chapters,
        chapter_scores=chapter_scores,
        baseline_kind=baseline_kind,
        comparable=comparable,
    )


def _safe_layer4(
    *,
    chapter: MemoChapter,
    evidence_pack: dict[str, Any],
    profile_metadata: dict[str, Any],
    chapter_summaries_map: dict[str, str],
) -> LayerScore:
    try:
        return evaluate_llm_judge(
            chapter_tag=chapter.chapter_tag,
            chapter_title=chapter.chapter_title,
            chapter_text=chapter.content_md or "",
            memo_context={
                "decision_anchor": evidence_pack.get("decision_anchor", {}),
                "critic_output": evidence_pack.get("critic_output", {}),
                "policy_compliance": profile_metadata.get("policy_compliance", {}),
                "quant_summary": profile_metadata.get("quant_profile", {}),
                "chapter_summaries": chapter_summaries_map,
                "chapter_count_found": len(chapter_summaries_map),
                "chapter_count_expected": EXPECTED_CHAPTER_COUNT,
            },
        )
    except Exception as exc:  # pragma: no cover - network/config dependent
        logger.warning("IC_MEMO_EVAL_JUDGE_FAILED chapter=%s error=%s", chapter.chapter_tag, exc)
        return LayerScore(
            layer="layer4",
            applicable=True,
            status=MetricStatus.DATA_ISSUE,
            score=0.0,
            metrics=[
                MetricResult(
                    metric="chapter_coherence",
                    status=MetricStatus.DATA_ISSUE,
                    score=0.0,
                    reason=f"Judge unavailable: {exc}",
                ),
            ],
            warnings=[str(exc)],
        )


def _build_data_issue_chapter(
    *,
    run_id: uuid.UUID,
    deal: PipelineDeal,
    chapter: MemoChapter,
    provider_manifest: dict[str, Any],
    reason: str,
) -> EvalChapterScore:
    empty_layer = LayerScore(layer="layer1", applicable=True, status=MetricStatus.DATA_ISSUE, score=0.0)
    return EvalChapterScore(
        run_id=run_id,
        deal_id=str(deal.id),
        deal_name=deal.deal_name or deal.title,
        chapter_number=chapter.chapter_number,
        chapter_tag=chapter.chapter_tag,
        chapter_title=chapter.chapter_title,
        memo_version_tag=chapter.version_tag,
        model_version=chapter.model_version,
        baseline=BaselineReference(kind=BaselineKind.NONE, comparable=False),
        layer1=empty_layer,
        layer2=LayerScore(layer="layer2", applicable=True, status=MetricStatus.DATA_ISSUE, score=0.0),
        layer3=LayerScore(layer="layer3", applicable=True, status=MetricStatus.DATA_ISSUE, score=0.0),
        layer4=LayerScore(layer="layer4", applicable=True, status=MetricStatus.DATA_ISSUE, score=0.0),
        classification=RegressionState.DATA_ISSUE,
        classification_reason=reason,
        comparison_summary={},
        provider_info=provider_manifest,
    )


def _load_golden_manifest(deal: PipelineDeal) -> GoldenDealManifest | None:
    candidates = {
        _slugify(deal.deal_name or deal.title or ""),
        _slugify(Path(deal.deal_folder_path).name if deal.deal_folder_path else ""),
    }
    for slug in candidates:
        if not slug:
            continue
        manifest_path = GOLDEN_ROOT / slug / "manifest.json"
        if manifest_path.exists():
            return GoldenDealManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    return None


def _resolve_baseline(
    db: Session,
    *,
    deal: PipelineDeal,
    chapter: MemoChapter,
    golden_manifest: GoldenDealManifest | None,
) -> BaselineReference:
    if golden_manifest and golden_manifest.approval_status == GoldenApprovalStatus.APPROVED:
        chapter_record = next(
            (item for item in golden_manifest.chapters if item.chapter_tag == chapter.chapter_tag),
            None,
        )
        if chapter_record and chapter_record.text.strip():
            return BaselineReference(
                kind=BaselineKind.GOLDEN_FIXED,
                golden_version=golden_manifest.golden_version,
                comparable=True,
            )

    last_pass = db.execute(
        select(EvalChapterScoreRow)
        .where(
            EvalChapterScoreRow.deal_id == deal.id,
            EvalChapterScoreRow.chapter_tag == chapter.chapter_tag,
            EvalChapterScoreRow.classification == RegressionState.PASS.value,
        )
        .order_by(EvalChapterScoreRow.created_at.desc())
        .limit(1),
    ).scalar_one_or_none()
    if last_pass:
        return BaselineReference(
            kind=BaselineKind.LAST_PASS,
            baseline_run_id=last_pass.run_id,
            comparable=True,
        )
    return BaselineReference(kind=BaselineKind.NONE, comparable=False)


def _classify_chapter(
    db: Session,
    *,
    current_overall: float,
    baseline: BaselineReference,
    chapter_text: str,
    chapter_tag: str,
    deal_id: uuid.UUID,
    golden_manifest: GoldenDealManifest | None,
    layer1: LayerScore,
    layer2: LayerScore,
    layer3: LayerScore,
    layer4: LayerScore,
) -> tuple[RegressionState, str, dict[str, Any]]:
    blocking_layer = _first_blocking_layer(layer1, layer2, layer3)
    if blocking_layer:
        return (
            RegressionState.REGRESSION,
            f"Deterministic regression detected in {blocking_layer}.",
            {"blocking_layer": blocking_layer},
        )

    if baseline.kind == BaselineKind.GOLDEN_FIXED:
        chapter_record = None
        if golden_manifest:
            chapter_record = next(
                (item for item in golden_manifest.chapters if item.chapter_tag == chapter_tag),
                None,
            )
        if chapter_record is None or not chapter_record.text.strip():
            return RegressionState.DATA_ISSUE, "Golden baseline is missing chapter text.", {}
        similarity = _text_similarity(chapter_text, chapter_record.text)
        if similarity < 0.35:
            return RegressionState.REGRESSION, "Current chapter drifted materially from approved golden baseline.", {"text_similarity": similarity}
        if current_overall >= 0.92:
            return RegressionState.IMPROVEMENT, "Current chapter exceeds the approved golden quality threshold.", {"text_similarity": similarity}
        return RegressionState.PASS, "Current chapter is aligned with approved golden baseline.", {"text_similarity": similarity}

    if baseline.kind == BaselineKind.LAST_PASS and baseline.baseline_run_id:
        last_pass = db.execute(
            select(EvalChapterScoreRow)
            .where(
                EvalChapterScoreRow.run_id == baseline.baseline_run_id,
                EvalChapterScoreRow.deal_id == deal_id,
                EvalChapterScoreRow.chapter_tag == chapter_tag,
            )
            .limit(1),
        ).scalar_one_or_none()
        if last_pass and last_pass.aggregate_score_json:
            baseline_overall = float((last_pass.aggregate_score_json or {}).get("overall", 0.0))
            delta = round(current_overall - baseline_overall, 4)
            if delta <= -0.05:
                return RegressionState.REGRESSION, "Aggregate score fell materially versus the last PASS baseline.", {"delta": delta}
            if delta >= 0.05:
                return RegressionState.IMPROVEMENT, "Aggregate score improved materially versus the last PASS baseline.", {"delta": delta}
            return RegressionState.PASS, "Aggregate score is within tolerance versus the last PASS baseline.", {"delta": delta}

    return RegressionState.DATA_ISSUE, "No comparable baseline was available for this chapter.", {}


def _summarise_deal(
    *,
    deal: PipelineDeal,
    chapters: list[MemoChapter],
    chapter_scores: list[EvalChapterScore],
    baseline_kind: BaselineKind,
    comparable: bool,
) -> EvalDealSummary:
    aggregate_score = round(sum(ch.aggregate.overall for ch in chapter_scores) / len(chapter_scores), 4) if chapter_scores else 0.0
    classification = _deal_classification(chapter_scores, comparable)
    reason = _deal_reason(chapter_scores, comparable)
    return EvalDealSummary(
        deal_id=str(deal.id),
        deal_name=deal.deal_name or deal.title,
        memo_version_tag=chapters[0].version_tag if chapters else "",
        model_version=chapters[0].model_version if chapters else "",
        chapter_count_found=len(chapters),
        chapter_count_expected=EXPECTED_CHAPTER_COUNT,
        chapter_scores=chapter_scores,
        aggregate_score=aggregate_score,
        classification=classification,
        classification_reason=reason,
        blocking_layer=_first_blocking_from_scores(chapter_scores),
        is_comparable=comparable,
        baseline_kind=baseline_kind,
    )


def _summarise_run(deal_summaries: list[EvalDealSummary]) -> EvalRunSummary:
    layer1_scores = []
    layer2_scores = []
    layer3_scores = []
    layer4_scores = []
    chapters = 0
    for deal in deal_summaries:
        chapters += len(deal.chapter_scores)
        for chapter in deal.chapter_scores:
            if chapter.layer1.applicable:
                layer1_scores.append(chapter.layer1.score)
            if chapter.layer2.applicable:
                layer2_scores.append(chapter.layer2.score)
            if chapter.layer3.applicable:
                layer3_scores.append(chapter.layer3.score)
            if chapter.layer4.applicable:
                layer4_scores.append(chapter.layer4.score)
    averages = {
        "layer1": round(sum(layer1_scores) / len(layer1_scores), 4) if layer1_scores else 0.0,
        "layer2": round(sum(layer2_scores) / len(layer2_scores), 4) if layer2_scores else 0.0,
        "layer3": round(sum(layer3_scores) / len(layer3_scores), 4) if layer3_scores else 0.0,
        "layer4": round(sum(layer4_scores) / len(layer4_scores), 4) if layer4_scores else 0.0,
    }
    return EvalRunSummary(
        deals_evaluated=len(deal_summaries),
        chapters_evaluated=chapters,
        layer_score_averages=averages,
        aggregate_score=round(sum(deal.aggregate_score for deal in deal_summaries) / len(deal_summaries), 4) if deal_summaries else 0.0,
        regressions=sum(1 for deal in deal_summaries if deal.classification == RegressionState.REGRESSION),
        improvements=sum(1 for deal in deal_summaries if deal.classification == RegressionState.IMPROVEMENT),
        data_issues=sum(1 for deal in deal_summaries if deal.classification == RegressionState.DATA_ISSUE),
        passes=sum(1 for deal in deal_summaries if deal.classification == RegressionState.PASS),
    )


def _classify_run(
    run_summary: EvalRunSummary,
    deal_summaries: list[EvalDealSummary],
) -> tuple[RegressionState, str, str | None]:
    blocking_layer = _first_blocking_from_deals(deal_summaries)
    if run_summary.regressions > 0:
        return RegressionState.REGRESSION, "At least one evaluated deal regressed.", blocking_layer
    if run_summary.data_issues > 0 and run_summary.passes == 0 and run_summary.improvements == 0:
        return RegressionState.DATA_ISSUE, "All evaluated deals have unresolved data issues.", blocking_layer
    if run_summary.improvements > 0 and run_summary.regressions == 0:
        return RegressionState.IMPROVEMENT, "At least one evaluated deal improved and none regressed.", blocking_layer
    return RegressionState.PASS, "All evaluated deals remained within acceptable tolerance.", blocking_layer


def _persist_eval_run(
    db: Session,
    fund_id: uuid.UUID,
    actor_id: str,
    report: EvalRunReport,
) -> None:
    run_row = EvalRunRow(
        fund_id=fund_id,
        run_id=report.run_id,
        trigger_type=report.trigger_type.value,
        run_mode=report.run_mode.value,
        golden_set_name=report.golden_set_name,
        baseline_kind=report.baseline_kind.value,
        baseline_run_id=report.baseline_run_id,
        prompt_manifest_hash=report.prompt_manifest_hash,
        model_manifest_hash=report.model_manifest_hash,
        provider_manifest_json=report.provider_manifest,
        status=report.status,
        classification=report.classification.value,
        classification_reason=report.classification_reason,
        summary_json=report.summary.model_dump(mode="json"),
        started_at=report.started_at,
        completed_at=report.completed_at,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(run_row)

    for deal in report.deal_summaries:
        for chapter in deal.chapter_scores:
            db.add(
                EvalChapterScoreRow(
                    run_id=report.run_id,
                    fund_id=fund_id,
                    deal_id=uuid.UUID(chapter.deal_id) if chapter.deal_id else None,
                    deal_name=chapter.deal_name,
                    chapter_number=chapter.chapter_number,
                    chapter_tag=chapter.chapter_tag,
                    chapter_title=chapter.chapter_title,
                    is_applicable_layer1=chapter.is_applicable_layer1,
                    is_applicable_layer2=chapter.is_applicable_layer2,
                    layer1_json=chapter.layer1.model_dump(mode="json"),
                    layer2_json=chapter.layer2.model_dump(mode="json"),
                    layer3_json=chapter.layer3.model_dump(mode="json"),
                    layer4_json=chapter.layer4.model_dump(mode="json"),
                    aggregate_score_json=chapter.aggregate.model_dump(mode="json"),
                    classification=chapter.classification.value,
                    classification_reason=chapter.classification_reason,
                    golden_version=chapter.golden_version,
                    memo_version_tag=chapter.memo_version_tag,
                    model_version=chapter.model_version,
                    provider_info_json=chapter.provider_info,
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
            )


def _build_provider_manifest() -> dict[str, Any]:
    openai_ready = bool(settings.OPENAI_API_KEY)
    azure_ready = bool(settings.AZURE_OPENAI_ENDPOINT and settings.AZURE_OPENAI_KEY)
    if openai_ready:
        effective_provider = "openai_direct"
        fallback_provider = "azure_openai" if azure_ready else None
    elif azure_ready:
        effective_provider = "azure_openai"
        fallback_provider = None
    else:
        effective_provider = "unconfigured"
        fallback_provider = None
    return {
        "effective_provider": effective_provider,
        "fallback_provider": fallback_provider,
        "openai_direct_ready": openai_ready,
        "azure_openai_ready": azure_ready,
        "azure_api_version": settings.AZURE_OPENAI_API_VERSION,
    }


def _compute_prompt_manifest_hash() -> str:
    digest = hashlib.sha256()
    if not PROMPTS_ROOT.exists():
        return ""
    for path in sorted(PROMPTS_ROOT.rglob("*.j2")):
        digest.update(path.relative_to(PROMPTS_ROOT).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _compute_model_manifest_hash() -> str:
    payload = {
        "stages": {stage: get_model(stage) for stage in MODEL_STAGES},
        "env_overrides": {
            key: value
            for key, value in sorted(os.environ.items())
            if key.startswith("NETZ_MODEL_")
        },
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _deal_baseline_kind(chapter_scores: list[EvalChapterScore]) -> BaselineKind:
    if any(ch.baseline.kind == BaselineKind.GOLDEN_FIXED for ch in chapter_scores):
        return BaselineKind.GOLDEN_FIXED
    if any(ch.baseline.kind == BaselineKind.LAST_PASS for ch in chapter_scores):
        return BaselineKind.LAST_PASS
    return BaselineKind.NONE


def _run_baseline_kind(deal_summaries: list[EvalDealSummary]) -> BaselineKind:
    kinds = {deal.baseline_kind for deal in deal_summaries}
    if BaselineKind.GOLDEN_FIXED in kinds:
        return BaselineKind.GOLDEN_FIXED
    if BaselineKind.LAST_PASS in kinds:
        return BaselineKind.LAST_PASS
    return BaselineKind.NONE


def _run_baseline_run_id(deal_summaries: list[EvalDealSummary]) -> uuid.UUID | None:
    for deal in deal_summaries:
        for chapter in deal.chapter_scores:
            if chapter.baseline.baseline_run_id:
                return chapter.baseline.baseline_run_id
    return None


def _deal_classification(chapter_scores: list[EvalChapterScore], comparable: bool) -> RegressionState:
    if not chapter_scores:
        return RegressionState.DATA_ISSUE
    if any(ch.classification == RegressionState.REGRESSION for ch in chapter_scores):
        return RegressionState.REGRESSION
    if any(ch.classification == RegressionState.DATA_ISSUE for ch in chapter_scores) and not comparable:
        return RegressionState.DATA_ISSUE
    if any(ch.classification == RegressionState.IMPROVEMENT for ch in chapter_scores):
        return RegressionState.IMPROVEMENT
    return RegressionState.PASS


def _deal_reason(chapter_scores: list[EvalChapterScore], comparable: bool) -> str:
    if not chapter_scores:
        return "No chapter scores were produced."
    regression = next((ch for ch in chapter_scores if ch.classification == RegressionState.REGRESSION), None)
    if regression:
        return regression.classification_reason
    data_issue = next((ch for ch in chapter_scores if ch.classification == RegressionState.DATA_ISSUE and ch.classification_reason), None)
    if data_issue:
        return data_issue.classification_reason
    if any(ch.classification == RegressionState.DATA_ISSUE for ch in chapter_scores) and not comparable:
        return "Deal evaluation is not comparable because baseline or chapter artifacts are incomplete."
    improvement = next((ch for ch in chapter_scores if ch.classification == RegressionState.IMPROVEMENT), None)
    if improvement:
        return improvement.classification_reason
    return "All chapters remained within acceptable tolerance."


def _first_blocking_layer(layer1: LayerScore, layer2: LayerScore, layer3: LayerScore) -> str | None:
    for layer in (layer1, layer2, layer3):
        if layer.blocking:
            return layer.layer
    return None


def _first_blocking_from_scores(chapter_scores: list[EvalChapterScore]) -> str | None:
    for chapter in chapter_scores:
        blocking = _first_blocking_layer(chapter.layer1, chapter.layer2, chapter.layer3)
        if blocking:
            return blocking
    return None


def _first_blocking_from_deals(deal_summaries: list[EvalDealSummary]) -> str | None:
    for deal in deal_summaries:
        if deal.blocking_layer:
            return deal.blocking_layer
    return None


def _artifact_to_dict(artifact: DealUnderwritingArtifact | None) -> dict[str, Any]:
    if artifact is None:
        return {}
    return {
        "recommendation": artifact.recommendation,
        "confidence_level": artifact.confidence_level,
        "risk_band": artifact.risk_band,
        "critic_findings": artifact.critic_findings or {},
        "policy_breaches": artifact.policy_breaches or {},
        "chapters_completed": artifact.chapters_completed,
        "model_version": artifact.model_version,
        "generated_at": artifact.generated_at.isoformat() if artifact.generated_at else None,
    }


def _text_similarity(current_text: str, baseline_text: str) -> float:
    return round(SequenceMatcher(None, (current_text or "").strip(), (baseline_text or "").strip()).ratio(), 4)


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")


def main() -> None:  # pragma: no cover - manual CLI wrapper
    parser = argparse.ArgumentParser(description="Run the IC memo eval framework.")
    parser.add_argument("--fund-id", required=True)
    parser.add_argument("--deal-ids", default="")
    parser.add_argument("--sample-size", type=int, default=3)
    parser.add_argument("--actor-id", default="validation-harness")
    parser.add_argument(
        "--run-mode",
        choices=[mode.value for mode in EvalRunMode],
        default=EvalRunMode.EVALUATE_EXISTING_ARTIFACTS.value,
    )
    parser.add_argument(
        "--trigger-type",
        choices=[trigger.value for trigger in TriggerType],
        default=TriggerType.MANUAL.value,
    )
    parser.add_argument("--golden-set-name", default="ic_memo_default")
    parser.add_argument("--force-rerun", action="store_true")
    args = parser.parse_args()

    from app.core.db.engine import async_session_factory

    SessionLocal = async_session_factory
    deal_ids = [uuid.UUID(raw.strip()) for raw in args.deal_ids.split(",") if raw.strip()]
    with SessionLocal() as session:
        report = run_ic_memo_eval(
            session,
            fund_id=uuid.UUID(args.fund_id),
            deal_ids=deal_ids or None,
            sample_size=args.sample_size,
            actor_id=args.actor_id,
            trigger_type=TriggerType(args.trigger_type),
            run_mode=EvalRunMode(args.run_mode),
            golden_set_name=args.golden_set_name,
            force_rerun=args.force_rerun,
        )
        print(report.model_dump_json(indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
