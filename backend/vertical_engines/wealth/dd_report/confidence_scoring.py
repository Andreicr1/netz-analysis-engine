"""Deterministic confidence scoring for DD Reports.

Computes a 0-100 confidence score based on evidence completeness,
chapter generation success rate, critic outcomes, and quant data
availability. No LLM calls — purely deterministic.
"""

from __future__ import annotations

from typing import Any

import structlog

from vertical_engines.wealth.dd_report.models import ChapterResult

logger = structlog.get_logger()

# ── Weight allocation (must sum to 1.0) ──────────────────────────
_WEIGHTS = {
    "chapter_completeness": 0.30,
    "evidence_coverage": 0.25,
    "quant_data_quality": 0.25,
    "critic_outcome": 0.20,
}


def compute_confidence_score(
    chapters: list[ChapterResult],
    evidence_refs: dict[str, Any] | None = None,
    quant_profile: dict[str, Any] | None = None,
) -> float:
    """Compute a deterministic 0-100 confidence score.

    Parameters
    ----------
    chapters : list[ChapterResult]
        Generated chapter results.
    evidence_refs : dict
        Evidence references gathered during generation.
    quant_profile : dict
        Quant metrics available for the fund.

    Returns
    -------
    float
        Confidence score between 0.0 and 100.0.
    """
    scores: dict[str, float] = {}

    # 1. Chapter completeness (0-100)
    total = len(chapters)
    completed = sum(1 for ch in chapters if ch.content_md and ch.status == "completed")
    scores["chapter_completeness"] = (completed / total * 100) if total > 0 else 0.0

    # 2. Evidence coverage (0-100)
    evidence = evidence_refs or {}
    expected_keys = [
        "documents", "quant_profile", "risk_metrics",
        "scoring_data", "macro_snapshot",
    ]
    present = sum(1 for k in expected_keys if evidence.get(k))
    scores["evidence_coverage"] = (present / len(expected_keys)) * 100

    # 3. Quant data quality (0-100)
    quant = quant_profile or {}
    key_metrics = [
        "cvar_95_3m", "sharpe_1y", "return_1y",
        "volatility_1y", "manager_score",
    ]
    quant_present = sum(1 for k in key_metrics if quant.get(k) is not None)
    scores["quant_data_quality"] = (quant_present / len(key_metrics)) * 100

    # 4. Critic outcome (0-100)
    accepted = sum(1 for ch in chapters if ch.critic_status == "accepted")
    escalated = sum(1 for ch in chapters if ch.critic_status == "escalated")
    if total > 0:
        critic_score = (accepted / total) * 100
        # Penalize escalations
        critic_score -= (escalated / total) * 30
        scores["critic_outcome"] = max(0.0, critic_score)
    else:
        scores["critic_outcome"] = 0.0

    # Weighted sum
    final = sum(
        scores[k] * _WEIGHTS[k] for k in _WEIGHTS
    )

    logger.info(
        "confidence_score_computed",
        final=round(final, 2),
        components=scores,
    )

    return round(min(100.0, max(0.0, final)), 2)


def derive_decision_anchor(
    confidence_score: float,
    chapters: list[ChapterResult],
) -> str | None:
    """Derive the decision anchor from the recommendation chapter.

    If the recommendation chapter exists and has content, extract
    the decision anchor. Otherwise, derive from confidence score.

    Returns
    -------
    str or None
        'APPROVE', 'CONDITIONAL', or 'REJECT'. None if insufficient data.
    """
    # Try to get from recommendation chapter content
    rec_chapter = next(
        (ch for ch in chapters if ch.tag == "recommendation" and ch.content_md),
        None,
    )

    if rec_chapter and rec_chapter.content_md:
        content_upper = rec_chapter.content_md.upper()
        if "APPROVE" in content_upper and "CONDITIONAL" not in content_upper:
            return "APPROVE"
        if "CONDITIONAL" in content_upper:
            return "CONDITIONAL"
        if "REJECT" in content_upper:
            return "REJECT"

    # Fallback: derive from confidence score
    if confidence_score >= 70:
        return "APPROVE"
    if confidence_score >= 40:
        return "CONDITIONAL"
    if confidence_score > 0:
        return "REJECT"

    return None
