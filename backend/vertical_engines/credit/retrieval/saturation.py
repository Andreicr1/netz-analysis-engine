"""Evidence saturation enforcement and retrieval audit artifacts.

Implements enforce_evidence_saturation() (per-chapter minimum thresholds)
and build_retrieval_audit() (structured audit artifact for compliance).

Error contract: never-raises. Returns result dict with warnings on failure.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from vertical_engines.credit.retrieval.models import (
    CHAPTER_EVIDENCE_THRESHOLDS,
    COVERAGE_MISSING,
    COVERAGE_PARTIAL,
    RETRIEVAL_POLICY_NAME,
)

logger = structlog.get_logger()


def enforce_evidence_saturation(
    chapter_stats: dict[str, dict],
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """Enforce evidence saturation thresholds per chapter."""
    gaps:                    list[dict] = []
    missing_document_classes: list[str] = []

    for ch_key, ch_data in chapter_stats.items():
        status = ch_data.get("coverage_status", COVERAGE_MISSING)
        stats  = ch_data.get("stats", {})

        if status == COVERAGE_MISSING:
            reason = (
                f"Chapter {ch_key}: NO evidence retrieved. "
                f"chunks={stats.get('chunk_count', 0)} "
                f"docs={stats.get('unique_docs', 0)} "
                f"mode={ch_data.get('retrieval_mode', '?')} "
                f"filter={ch_data.get('doc_type_filter', 'NONE')}"
            )
            gaps.append({"chapter": ch_key, "status": status, "reason": reason})
            logger.warning("evidence_gap", reason=reason)

            if ch_key in ("ch08_returns", "ch07_capital"):
                missing_document_classes.append("MISSING_FINANCIAL_DISCLOSURE")
            elif ch_key in ("ch05_legal", "ch06_terms"):
                missing_document_classes.append("NO_LPA_FOUND")

            if strict:
                logger.warning(
                    "evidence_saturation_strict_fail",
                    reason=reason,
                    gaps=len(gaps),
                )
                return {
                    "gaps": gaps,
                    "missing_document_classes": list(set(missing_document_classes)),
                    "all_saturated": False,
                    "strict_fail": True,
                    "strict_fail_reason": reason,
                }

        elif status == COVERAGE_PARTIAL:
            threshold = CHAPTER_EVIDENCE_THRESHOLDS.get(ch_key)
            reason = (
                f"Chapter {ch_key}: PARTIAL evidence. "
                f"chunks={stats.get('chunk_count', 0)} "
                f"(min={threshold.min_chunks if threshold else '?'}) "
                f"docs={stats.get('unique_docs', 0)} "
                f"(min={threshold.min_docs if threshold else '?'}) "
                f"mode={ch_data.get('retrieval_mode', '?')}"
            )
            gaps.append({"chapter": ch_key, "status": status, "reason": reason})
            logger.info("evidence_partial", reason=reason)

    all_saturated = len(gaps) == 0

    if missing_document_classes:
        logger.warning(
            "missing_document_classes",
            classes=missing_document_classes,
        )

    return {
        "gaps":                    gaps,
        "missing_document_classes": list(set(missing_document_classes)),
        "all_saturated":           all_saturated,
    }


def build_retrieval_audit(
    *,
    fund_id: str,
    deal_id: str,
    chapter_evidence: dict[str, dict],
    corpus_result: dict[str, Any],
    saturation_report: dict[str, Any],
) -> dict[str, Any]:
    """Build a structured, serializable audit artifact.

    v2 additions: retrieval_mode and doc_type_filter recorded per chapter.
    """
    global_stats  = corpus_result.get("global_stats", {})
    chapter_stats = corpus_result.get("chapter_stats", {})

    unique_docs   = global_stats.get("unique_docs", 0)
    total_chunks  = global_stats.get("total_chunks", 0)
    all_saturated = saturation_report.get("all_saturated", False)
    missing_classes = saturation_report.get("missing_document_classes", [])

    if all_saturated and unique_docs >= 15 and total_chunks >= 80:
        evidence_confidence = "VERY_HIGH"
    elif unique_docs >= 10 and total_chunks >= 40:
        evidence_confidence = "HIGH"
    elif unique_docs >= 5 and total_chunks >= 20:
        evidence_confidence = "MEDIUM"
    else:
        evidence_confidence = "LOW"

    chapters_audit: dict[str, dict] = {}
    for ch_key, ch_info in chapter_stats.items():
        stats = ch_info.get("stats", {})
        chapters_audit[ch_key] = {
            "queries":         ch_info.get("queries", []),
            "retrieval_mode":  ch_info.get("retrieval_mode", "IC_GRADE"),
            "doc_type_filter": ch_info.get("doc_type_filter"),
            "chunk_count":     stats.get("chunk_count", 0),
            "unique_docs":     stats.get("unique_docs", 0),
            "coverage_status": ch_info.get("coverage_status", COVERAGE_MISSING),
            "doc_types":       stats.get("doc_types", []),
        }

    audit = {
        "retrieval_policy": RETRIEVAL_POLICY_NAME,
        "fund_id":   fund_id,
        "deal_id":   deal_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "chapters":  chapters_audit,
        "global_stats": {
            **global_stats,
            "evidence_confidence": evidence_confidence,
        },
        "saturation_report":      saturation_report,
        "missing_document_classes": missing_classes,
    }

    logger.info(
        "retrieval_audit_built",
        policy=RETRIEVAL_POLICY_NAME,
        docs=unique_docs,
        chunks=total_chunks,
        confidence=evidence_confidence,
        gaps=len(saturation_report.get("gaps", [])),
    )

    return audit
