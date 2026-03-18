"""Evidence quality utilities for AI validation layers.

Cross-cutting AI-engine utilities used by eval_metrics and the
global agent.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def cross_validate_answer(
    answer_text: str,
    chunks: list[Any],
) -> dict[str, Any]:
    """Cross-validate an LLM answer against source evidence chunks.

    Checks whether critical claims in the answer are supported by
    at least one evidence chunk.

    Returns a dict with ``overall_status``, ``claims``, and
    ``has_critical_claims`` keys.
    """
    if not answer_text or not chunks:
        return {
            "has_critical_claims": False,
            "claims": [],
            "overall_status": "NO_CRITICAL_CLAIMS",
        }

    # Extract numeric/monetary claims from the answer
    import re

    claim_pattern = re.compile(
        r"(?:\$[\d,]+(?:\.\d+)?(?:\s*(?:million|billion|mn|bn))?|"
        r"\d+(?:\.\d+)?%|"
        r"\d+(?:\.\d+)?x)",
        re.IGNORECASE,
    )
    claims = claim_pattern.findall(answer_text)
    if not claims:
        return {
            "has_critical_claims": False,
            "claims": [],
            "overall_status": "NO_CRITICAL_CLAIMS",
        }

    # Check each claim against chunks
    chunk_texts = " ".join(
        getattr(c, "chunk_text", "") or "" for c in chunks
    ).lower()

    confirmed = 0
    claim_results = []
    for claim in claims:
        # Normalize for comparison
        claim_clean = claim.replace(",", "").lower()
        found = claim_clean in chunk_texts
        claim_results.append({"claim": claim, "supported": found})
        if found:
            confirmed += 1

    total = len(claims)
    if confirmed == total:
        status = "CONFIRMED"
    elif confirmed > 0:
        status = "PARTIAL"
    else:
        status = "UNCONFIRMED"

    return {
        "has_critical_claims": True,
        "claims": claim_results,
        "overall_status": status,
        "confirmed_count": confirmed,
        "total_claims": total,
    }


def recency_analysis(chunks: list[Any]) -> dict[str, Any]:
    """Analyze recency of evidence chunks.

    Returns a dict indicating whether there are mixed revisions,
    the most recent date, and any outdated chunks.
    """
    dates: list[str] = []
    for c in chunks:
        lm = getattr(c, "last_modified", None)
        if lm:
            dates.append(str(lm))

    if not dates:
        return {
            "revisions_detected": [],
            "most_recent": None,
            "mixed_revisions": False,
            "outdated_chunks": [],
            "recency_warning": None,
            "last_modified_range": {"earliest": None, "latest": None},
        }

    sorted_dates = sorted(dates)
    unique_dates = sorted(set(dates))

    return {
        "revisions_detected": unique_dates,
        "most_recent": sorted_dates[-1],
        "mixed_revisions": len(unique_dates) > 1,
        "outdated_chunks": [],
        "recency_warning": None,
        "last_modified_range": {
            "earliest": sorted_dates[0],
            "latest": sorted_dates[-1],
        },
    }


def compute_confidence(
    chunks: list[Any],
    domain_filter: str | None = None,
) -> dict[str, Any]:
    """Compute retrieval confidence score from evidence chunks.

    Returns a dict with ``retrieval_confidence`` (0.0-1.0) and
    ``components`` breakdown.
    """
    if not chunks:
        return {
            "retrieval_confidence": 0.0,
            "components": {
                "chunk_count": 0,
                "avg_score": 0.0,
                "source_diversity": 0,
            },
        }

    scores = [
        getattr(c, "search_score", None) or getattr(c, "extraction_confidence", 0.5)
        for c in chunks
    ]
    avg_score = sum(scores) / len(scores) if scores else 0.0

    sources = {
        getattr(c, "source_blob", "") for c in chunks
        if getattr(c, "source_blob", "")
    }

    # Confidence heuristic
    chunk_factor = min(1.0, len(chunks) / 10.0)
    score_factor = min(1.0, avg_score)
    diversity_factor = min(1.0, len(sources) / 3.0)
    confidence = (chunk_factor * 0.3 + score_factor * 0.4 + diversity_factor * 0.3)

    return {
        "retrieval_confidence": round(confidence, 4),
        "components": {
            "chunk_count": len(chunks),
            "avg_score": round(avg_score, 4),
            "source_diversity": len(sources),
        },
    }
