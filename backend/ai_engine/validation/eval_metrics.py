from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import mean
from typing import Any

from ai_engine.intelligence.deep_review_confidence import compute_underwriting_confidence
from ai_engine.validation.deep_review_comparator import _extract_recommendation_from_chapter
from ai_engine.validation.evidence_quality import (
    cross_validate_answer,
    recency_analysis,
)
from ai_engine.validation.validation_schema import (
    LayerAggregateScore,
    LayerScore,
    MetricResult,
    MetricStatus,
)

CH13_TAG = "ch13_recommendation"
NUMERIC_DENSE_CHAPTERS = {
    "ch03_exit",
    "ch07_capital",
    "ch08_returns",
    "ch09_downside",
    "ch12_peers",
    "ch14_governance_stress",
}
CHAPTER_DOC_TYPE_AFFINITY: dict[str, set[str]] = {
    "ch01_exec": {"TERM_SHEET", "FINANCIAL", "RISK_ASSESSMENT", "FUND_POLICY"},
    "ch02_macro": {"FINANCIAL", "RISK_ASSESSMENT", "REGULATORY"},
    "ch03_exit": {"FINANCIAL", "FINANCIAL_STATEMENTS", "RISK_ASSESSMENT"},
    "ch04_sponsor": {
        "SUBSCRIPTION_AGREEMENT",
        "SIDE_LETTER",
        "LEGAL",
        "FUND_CONSTITUTION",
        "GUARANTEE",
        "FUND_POLICY",
        "COMPLIANCE",
        "REGULATORY",
        "RISK_ASSESSMENT",
        "MONITORING",
    },
    "ch05_legal": {
        "CREDIT_AGREEMENT",
        "FACILITY_AGREEMENT",
        "LOAN_AGREEMENT",
        "SECURITY_AGREEMENT",
        "INTERCREDITOR",
        "GUARANTEE",
        "PLEDGE",
        "LEGAL",
    },
    "ch06_terms": {"TERM_SHEET", "CREDIT_AGREEMENT", "FACILITY_AGREEMENT", "LOAN_AGREEMENT"},
    "ch07_capital": {"FINANCIAL", "FINANCIAL_STATEMENTS", "TERM_SHEET"},
    "ch08_returns": {"FINANCIAL", "FINANCIAL_STATEMENTS", "TERM_SHEET"},
    "ch09_downside": {"RISK_ASSESSMENT", "FINANCIAL", "COVENANT_COMPLIANCE"},
    "ch10_covenants": {"COVENANT_COMPLIANCE", "COVENANT", "CREDIT_AGREEMENT", "FACILITY_AGREEMENT"},
    "ch11_risks": {"RISK_ASSESSMENT", "RISK", "COMPLIANCE", "REGULATORY", "INSURANCE", "WATCHLIST"},
    "ch12_peers": {"FINANCIAL", "TERM_SHEET", "RISK_ASSESSMENT"},
    "ch14_governance_stress": {"COMPLIANCE", "REGULATORY", "RISK_ASSESSMENT", "FUND_POLICY"},
}
_NUMBER_RE = re.compile(r"\b(?:\d+(?:[\.,]\d+)?%?|\$\d[\d,\.]*)\b")
_RELATED_ENTITY_TERMS = (
    "related entity",
    "publicly listed",
    "managed by the same sponsor",
    "managed by the same investment manager",
    "ticker:",
)
_TARGET_ATTRIBUTION_GUARDS = (
    "target vehicle",
    "private fund under review",
    "direct target",
    "related entity data only",
)


@dataclass(slots=True)
class EvidenceChunkProxy:
    chunk_id: str
    chunk_text: str
    source_blob: str
    last_modified: str | None = None


def is_layer12_applicable(chapter_tag: str) -> bool:
    return chapter_tag != CH13_TAG


def build_layer_aggregate(
    layer1: LayerScore,
    layer2: LayerScore,
    layer3: LayerScore,
    layer4: LayerScore | None = None,
) -> LayerAggregateScore:
    weights = []
    values = []
    for weight, layer in (
        (0.25, layer1),
        (0.30, layer2),
        (0.30, layer3),
        (0.15, layer4),
    ):
        if layer is not None and layer.applicable and layer.status != MetricStatus.DATA_ISSUE:
            weights.append(weight)
            values.append(layer.score * weight)
    overall = sum(values) / sum(weights) if weights else 0.0
    return LayerAggregateScore(
        layer1=layer1.score if layer1.applicable else None,
        layer2=layer2.score if layer2.applicable else None,
        layer3=layer3.score if layer3.applicable else None,
        layer4=layer4.score if layer4 and layer4.applicable else None,
        overall=round(overall, 4),
    )


def evaluate_retrieval_layer(
    *,
    chapter_tag: str,
    chapter_text: str,
    evidence_pack: dict[str, Any],
) -> LayerScore:
    if not is_layer12_applicable(chapter_tag):
        return LayerScore(
            layer="layer1",
            applicable=False,
            status=MetricStatus.NOT_APPLICABLE,
            score=1.0,
        )

    retrieval_audit = evidence_pack.get("retrieval_audit", {}) or {}
    chapter_audit = (retrieval_audit.get("chapters", {}) or {}).get(chapter_tag, {}) or {}
    metrics: list[MetricResult] = []

    coverage_status = str(chapter_audit.get("coverage_status", "MISSING")).upper()
    coverage_score = 1.0 if coverage_status in {"SATURATED", "COMPLETE", "COVERED"} else 0.5 if coverage_status in {"PARTIAL", "MIXED"} else 0.0
    metrics.append(
        MetricResult(
            metric="chapter_coverage",
            status=_status_from_score(coverage_score, warn_floor=0.5),
            score=coverage_score,
            actual=coverage_status,
            expected="SATURATED|COMPLETE",
        ),
    )

    unique_docs = int(chapter_audit.get("unique_docs", 0) or 0)
    diversity_score = 1.0 if unique_docs >= 4 else 0.6 if unique_docs >= 2 else 0.0
    metrics.append(
        MetricResult(
            metric="doc_diversity",
            status=_status_from_score(diversity_score, warn_floor=0.6),
            score=diversity_score,
            actual=unique_docs,
            expected=">=4 unique docs",
        ),
    )

    actual_doc_types = {str(v).upper() for v in (chapter_audit.get("doc_types", []) or []) if v}
    expected_doc_types = CHAPTER_DOC_TYPE_AFFINITY.get(chapter_tag, set())
    overlap = len(actual_doc_types & expected_doc_types)
    affinity_score = 1.0 if overlap >= 2 else 0.6 if overlap >= 1 else 0.0
    metrics.append(
        MetricResult(
            metric="doc_type_affinity",
            status=_status_from_score(affinity_score, warn_floor=0.6),
            score=affinity_score,
            actual=sorted(actual_doc_types),
            expected=sorted(expected_doc_types),
            details={"overlap": overlap},
        ),
    )

    chunk_count = int(chapter_audit.get("chunk_count", 0) or 0)
    min_chunks = 4 if chapter_tag not in {"ch05_legal", "ch06_terms"} else 5
    chunk_score = 1.0 if min_chunks <= chunk_count <= 30 else 0.5 if 1 <= chunk_count < min_chunks else 0.0
    metrics.append(
        MetricResult(
            metric="chunk_count_valid",
            status=_status_from_score(chunk_score, warn_floor=0.5),
            score=chunk_score,
            actual=chunk_count,
            expected=f"{min_chunks}-30 chunks",
        ),
    )

    recency = recency_analysis(_build_recency_proxies(evidence_pack))
    recency_score = 1.0 if not recency.get("mixed_revisions") else 0.4
    metrics.append(
        MetricResult(
            metric="recency_clean",
            status=_status_from_score(recency_score, warn_floor=0.6),
            score=recency_score,
            actual=recency.get("mixed_revisions", False),
            expected=False,
            details=recency,
        ),
    )

    if chapter_tag in NUMERIC_DENSE_CHAPTERS:
        number_count = len(_NUMBER_RE.findall(chapter_text or ""))
        numeric_score = 1.0 if number_count >= 8 else 0.5 if number_count >= 3 else 0.0
        metrics.append(
            MetricResult(
                metric="numeric_density",
                status=_status_from_score(numeric_score, warn_floor=0.5),
                score=numeric_score,
                actual=number_count,
                expected=">=8 numeric tokens",
            ),
        )
    else:
        metrics.append(
            MetricResult(
                metric="numeric_density",
                status=MetricStatus.NOT_APPLICABLE,
                score=1.0,
                actual=None,
                expected=None,
                reason="Numeric density is not gating for this chapter.",
            ),
        )

    return _finalise_layer("layer1", metrics)


def evaluate_grounding_layer(
    *,
    chapter_tag: str,
    chapter_text: str,
    evidence_pack: dict[str, Any],
    chapter_citations: list[dict[str, Any]] | None = None,
) -> LayerScore:
    if not is_layer12_applicable(chapter_tag):
        return LayerScore(
            layer="layer2",
            applicable=False,
            status=MetricStatus.NOT_APPLICABLE,
            score=1.0,
        )

    metrics: list[MetricResult] = []
    chapter_citations = chapter_citations or []
    chunk_proxies = _build_grounding_proxies(chapter_citations)
    citation_governance = evidence_pack.get("citation_governance", {}) or {}

    if chunk_proxies:
        cross = cross_validate_answer(chapter_text or "", chunk_proxies)
        cross_score = 1.0 if cross.get("overall_status") == "CONFIRMED" else 0.5 if cross.get("overall_status") == "NO_CRITICAL_CLAIMS" else 0.0
        metrics.append(
            MetricResult(
                metric="claim_cross_validation",
                status=_status_from_score(cross_score, warn_floor=0.5),
                score=cross_score,
                actual=cross.get("overall_status"),
                expected="CONFIRMED|NO_CRITICAL_CLAIMS",
                details=cross,
            ),
        )
    else:
        metrics.append(
            MetricResult(
                metric="claim_cross_validation",
                status=MetricStatus.DATA_ISSUE,
                score=0.0,
                reason="No chapter-level citations/excerpts available for cross-validation.",
            ),
        )

    citation_count = len(chapter_citations)
    citation_score = 1.0 if citation_count >= 1 else 0.0
    metrics.append(
        MetricResult(
            metric="citation_validity",
            status=_status_from_score(citation_score, warn_floor=0.5),
            score=citation_score,
            actual=citation_count,
            expected=">=1 citation for grounded chapters",
        ),
    )

    attr_score, attr_reason = _entity_attribution_score(chapter_text)
    metrics.append(
        MetricResult(
            metric="entity_attribution_regression",
            status=_status_from_score(attr_score, warn_floor=0.6),
            score=attr_score,
            reason=attr_reason,
        ),
    )

    if citation_count > 0:
        claim_count = max(1, len(_NUMBER_RE.findall(chapter_text or "")))
        ungrounded_rate = max(0.0, min(1.0, 1.0 - min(citation_count, claim_count) / claim_count))
        ungrounded_score = 1.0 - ungrounded_rate
        metrics.append(
            MetricResult(
                metric="ungrounded_claim_rate",
                status=_status_from_score(ungrounded_score, warn_floor=0.6),
                score=ungrounded_score,
                actual=round(ungrounded_rate, 4),
                expected="<=0.40",
            ),
        )
    else:
        metrics.append(
            MetricResult(
                metric="ungrounded_claim_rate",
                status=MetricStatus.DATA_ISSUE,
                score=0.0,
                reason="No chapter-level citations available to estimate grounding coverage.",
            ),
        )

    fabrication_detected = bool(citation_governance.get("unsupported_claims_detected"))
    fabrication_score = 0.0 if fabrication_detected else 1.0
    metrics.append(
        MetricResult(
            metric="fabrication_flag",
            status=MetricStatus.FAIL if fabrication_detected else MetricStatus.PASS,
            score=fabrication_score,
            actual=fabrication_detected,
            expected=False,
        ),
    )

    return _finalise_layer("layer2", metrics)


def evaluate_decision_integrity_layer(
    *,
    chapter_tag: str,
    chapter_text: str,
    evidence_pack: dict[str, Any],
    underwriting_artifact: dict[str, Any] | None,
    profile_metadata: dict[str, Any] | None,
) -> LayerScore:
    metrics: list[MetricResult] = []
    artifact = underwriting_artifact or {}
    metadata = profile_metadata or {}

    retrieval_audit = evidence_pack.get("retrieval_audit", {}) or {}
    saturation_report = evidence_pack.get("saturation_report", {}) or {}
    critic_output = evidence_pack.get("critic_output", {}) or artifact.get("critic_findings", {}) or {}
    confidence_breakdown = (
        evidence_pack.get("confidence_breakdown_pre_tone", {})
        or evidence_pack.get("confidence_breakdown", {})
        or {}
    )
    hard_checks = metadata.get("hard_policy_checks", {}) or {}
    concentration_profile = metadata.get("concentration_profile", {}) or {}
    quant_profile = metadata.get("quant_profile", {}) or {}
    evidence_pack_meta = {
        "chapter_counts": {
            key: {
                "unique_docs": val.get("unique_docs", 0),
                "chunk_count": val.get("chunk_count", 0),
            }
            for key, val in (retrieval_audit.get("chapters", {}) or {}).items()
        },
        "investment_terms": evidence_pack.get("investment_terms", {}) or metadata.get("investment_terms", {}) or {},
    }

    recomputed = compute_underwriting_confidence(
        retrieval_audit=retrieval_audit,
        saturation_report=saturation_report,
        hard_check_results=hard_checks,
        concentration_profile=concentration_profile,
        critic_output=critic_output,
        quant_profile=quant_profile,
        evidence_pack_meta=evidence_pack_meta,
    )
    stored_pre_tone = evidence_pack.get("confidence_score_pre_tone")
    if stored_pre_tone is None:
        # Backward compatibility for evidence packs emitted before the explicit
        # pre-tone field was introduced.
        stored_pre_tone = evidence_pack.get("confidence_score")
    expected_pre_tone = int(stored_pre_tone) if stored_pre_tone is not None else -1
    recomputed_score = int(recomputed.get("confidence_score", 0))
    confidence_valid = expected_pre_tone == recomputed_score if expected_pre_tone >= 0 else False
    metrics.append(
        MetricResult(
            metric="confidence_score_valid",
            status=MetricStatus.PASS if confidence_valid else MetricStatus.FAIL if expected_pre_tone >= 0 else MetricStatus.DATA_ISSUE,
            score=1.0 if confidence_valid else 0.0,
            actual=recomputed_score,
            expected=expected_pre_tone if expected_pre_tone >= 0 else None,
            details={"recomputed": recomputed, "stored_breakdown": confidence_breakdown},
            reason="" if expected_pre_tone >= 0 else "Pre-tone confidence score missing from evidence pack.",
        ),
    )

    caps = set(evidence_pack.get("confidence_caps_applied", []) or [])
    hard_breaches = bool((hard_checks or {}).get("has_hard_breaches")) or bool((evidence_pack.get("decision_anchor", {}) or {}).get("hardBreaches"))
    hard_cap_ok = (not hard_breaches) or any("Hard policy breach" in cap for cap in caps)
    metrics.append(
        MetricResult(
            metric="hard_breach_cap",
            status=MetricStatus.PASS if hard_cap_ok else MetricStatus.FAIL,
            score=1.0 if hard_cap_ok else 0.0,
            actual=sorted(caps),
            expected="Hard policy breach cap present when hard breaches exist",
        ),
    )

    post_tone = int((artifact.get("critic_findings", {}) or {}).get("confidence_score_deterministic") or evidence_pack.get("confidence_score", 0) or 0)
    tone_invariant_ok = expected_pre_tone < 0 or post_tone <= expected_pre_tone
    metrics.append(
        MetricResult(
            metric="tone_invariant",
            status=MetricStatus.PASS if tone_invariant_ok else MetricStatus.FAIL,
            score=1.0 if tone_invariant_ok else 0.0,
            actual=post_tone,
            expected=f"<= {expected_pre_tone}" if expected_pre_tone >= 0 else None,
        ),
    )

    fatal_flaws = critic_output.get("fatal_flaws", []) or []
    fatal_override_ok = not fatal_flaws or post_tone <= 40
    metrics.append(
        MetricResult(
            metric="fatal_flaw_override",
            status=MetricStatus.PASS if fatal_override_ok else MetricStatus.FAIL,
            score=1.0 if fatal_override_ok else 0.0,
            actual=len(fatal_flaws),
            expected="post-tone score <= 40 when fatal flaws exist",
        ),
    )

    decision_anchor = evidence_pack.get("decision_anchor", {}) or {}
    expected_decision = str(decision_anchor.get("finalDecision", "")).upper()
    chapter_recommendation = str(_extract_recommendation_from_chapter(chapter_text)).upper()
    if chapter_tag == CH13_TAG and expected_decision:
        aligned = chapter_recommendation == expected_decision
        metrics.append(
            MetricResult(
                metric="decision_anchor_alignment",
                status=MetricStatus.PASS if aligned else MetricStatus.FAIL,
                score=1.0 if aligned else 0.0,
                actual=chapter_recommendation,
                expected=expected_decision,
            ),
        )
    else:
        metrics.append(
            MetricResult(
                metric="decision_anchor_alignment",
                status=MetricStatus.NOT_APPLICABLE if chapter_tag != CH13_TAG else MetricStatus.DATA_ISSUE,
                score=1.0 if chapter_tag != CH13_TAG else 0.0,
                reason="Decision-anchor alignment is chapter-13 specific.",
            ),
        )

    idempotent = _check_idempotency(
        retrieval_audit=retrieval_audit,
        saturation_report=saturation_report,
        hard_checks=hard_checks,
        concentration_profile=concentration_profile,
        critic_output=critic_output,
        quant_profile=quant_profile,
        evidence_pack_meta=evidence_pack_meta,
    )
    metrics.append(
        MetricResult(
            metric="idempotency_10x",
            status=MetricStatus.PASS if idempotent else MetricStatus.FAIL,
            score=1.0 if idempotent else 0.0,
            actual=idempotent,
            expected=True,
        ),
    )

    blocker_class = _classify_blocker(decision_anchor, critic_output, hard_checks)
    metrics.append(
        MetricResult(
            metric="blocker_classification",
            status=MetricStatus.PASS if blocker_class != "UNKNOWN" else MetricStatus.WARN,
            score=1.0 if blocker_class != "UNKNOWN" else 0.5,
            actual=blocker_class,
            expected="Known blocker class",
        ),
    )

    return _finalise_layer("layer3", metrics)


def chapter_citations_from_pack(
    evidence_pack: dict[str, Any],
    chapter_tag: str,
    chapter_number: int | None = None,
) -> list[dict[str, Any]]:
    chapter_citations = (evidence_pack.get("chapter_citations", {}) or {}).get(chapter_tag, [])
    if isinstance(chapter_citations, list) and chapter_citations:
        return chapter_citations

    fallback = []
    for cit in evidence_pack.get("citations", []) or []:
        if not isinstance(cit, dict):
            continue
        if str(cit.get("chapter_tag") or "").strip() == chapter_tag:
            fallback.append(cit)
            continue
        if chapter_number is not None and cit.get("chapter_number") == chapter_number:
            fallback.append(cit)
    return fallback


def _build_recency_proxies(evidence_pack: dict[str, Any]) -> list[EvidenceChunkProxy]:
    proxies: list[EvidenceChunkProxy] = []
    citations = evidence_pack.get("citations", []) or []
    if not citations:
        for chapter_citations in (evidence_pack.get("chapter_citations", {}) or {}).values():
            if isinstance(chapter_citations, list):
                citations.extend(chapter_citations)
    for cit in citations:
        proxies.append(
            EvidenceChunkProxy(
                chunk_id=str(cit.get("chunk_id", "UNKNOWN")),
                chunk_text="",
                source_blob=str(cit.get("blob_name", "")),
                last_modified=str(cit.get("last_modified")) if cit.get("last_modified") else None,
            ),
        )
    return proxies


def _build_grounding_proxies(chapter_citations: list[dict[str, Any]]) -> list[EvidenceChunkProxy]:
    proxies: list[EvidenceChunkProxy] = []
    for cit in chapter_citations:
        text = str(cit.get("excerpt") or cit.get("chunk_text") or "")
        proxies.append(
            EvidenceChunkProxy(
                chunk_id=str(cit.get("chunk_id", "UNKNOWN")),
                chunk_text=text,
                source_blob=str(cit.get("source_name") or cit.get("blob_name") or ""),
                last_modified=str(cit.get("last_modified")) if cit.get("last_modified") else None,
            ),
        )
    return proxies


def _entity_attribution_score(chapter_text: str) -> tuple[float, str]:
    lower = (chapter_text or "").lower()
    has_related_signal = any(term in lower for term in _RELATED_ENTITY_TERMS)
    has_guard = any(term in lower for term in _TARGET_ATTRIBUTION_GUARDS)
    if not has_related_signal:
        return 1.0, "No related-entity attribution risk signaled in chapter text."
    if has_guard:
        return 1.0, "Related-entity references are guarded by explicit attribution language."
    return 0.0, "Related-entity references detected without explicit attribution guard."


def _status_from_score(score: float, *, warn_floor: float) -> MetricStatus:
    if score >= 1.0:
        return MetricStatus.PASS
    if score >= warn_floor:
        return MetricStatus.WARN
    return MetricStatus.FAIL


def _finalise_layer(layer_name: str, metrics: list[MetricResult]) -> LayerScore:
    applicable_scores = [
        metric.score
        for metric in metrics
        if metric.status not in {MetricStatus.NOT_APPLICABLE, MetricStatus.DATA_ISSUE}
    ]
    score = round(mean(applicable_scores), 4) if applicable_scores else 0.0
    blocking = any(metric.status == MetricStatus.FAIL and metric.metric in {
        "chapter_coverage",
        "citation_validity",
        "fabrication_flag",
        "confidence_score_valid",
        "hard_breach_cap",
        "tone_invariant",
        "fatal_flaw_override",
        "decision_anchor_alignment",
    } for metric in metrics)
    if any(metric.status == MetricStatus.FAIL for metric in metrics):
        status = MetricStatus.FAIL
    elif all(metric.status == MetricStatus.DATA_ISSUE for metric in metrics):
        status = MetricStatus.DATA_ISSUE
    elif any(metric.status == MetricStatus.WARN for metric in metrics):
        status = MetricStatus.WARN
    else:
        status = MetricStatus.PASS
    warnings = [metric.reason for metric in metrics if metric.reason and metric.status in {MetricStatus.WARN, MetricStatus.DATA_ISSUE}]
    return LayerScore(
        layer=layer_name,
        applicable=True,
        status=status,
        score=score,
        metrics=metrics,
        warnings=warnings,
        blocking=blocking,
    )


def _check_idempotency(
    *,
    retrieval_audit: dict[str, Any],
    saturation_report: dict[str, Any],
    hard_checks: dict[str, Any],
    concentration_profile: dict[str, Any],
    critic_output: dict[str, Any],
    quant_profile: dict[str, Any],
    evidence_pack_meta: dict[str, Any],
) -> bool:
    results = []
    for _ in range(10):
        results.append(
            compute_underwriting_confidence(
                retrieval_audit=retrieval_audit,
                saturation_report=saturation_report,
                hard_check_results=hard_checks,
                concentration_profile=concentration_profile,
                critic_output=critic_output,
                quant_profile=quant_profile,
                evidence_pack_meta=evidence_pack_meta,
            ),
        )
    serialised = [str(result) for result in results]
    return all(item == serialised[0] for item in serialised)


def _classify_blocker(
    decision_anchor: dict[str, Any],
    critic_output: dict[str, Any],
    hard_checks: dict[str, Any],
) -> str:
    if hard_checks.get("has_hard_breaches"):
        return "POLICY_BLOCKER"
    if critic_output.get("fatal_flaws"):
        return "STRUCTURAL_BLOCKER"
    if decision_anchor.get("icGate") == "CONDITIONAL":
        return "BOARD_OVERRIDE_ONLY"
    if decision_anchor.get("diligenceGaps"):
        return "DILIGENCE_GAP"
    return "UNKNOWN"
