"""Retrieval confidence signal — delta/rank-based decision layer.

Provides a domain-agnostic RetrievalSignal that captures confidence
metadata for a query's result set.  Based on relative measures (deltas,
percentiles) rather than fragile absolute score thresholds.

Usage:
    from ai_engine.extraction.retrieval_signal import RetrievalSignal

    signal = RetrievalSignal.from_results(results, score_key="reranker_score")
    print(signal.confidence)  # "HIGH" | "MODERATE" | "LOW" | "AMBIGUOUS"
"""
from __future__ import annotations

import dataclasses
import statistics
from typing import Any

# ── Tunable heuristics (reranker logit scale) ───────────────────────
RERANKER_DELTA_HIGH: float = 2.0
RERANKER_DELTA_MODERATE: float = 0.5

# ── Tunable heuristics (cosine similarity scale) ────────────────────
COSINE_DELTA_HIGH: float = 0.08
COSINE_DELTA_MODERATE: float = 0.03

# ── Minimum result count for meaningful signal ──────────────────────
MIN_RESULTS_FOR_AMBIGUOUS: int = 5
MIN_RESULTS_FOR_HIGH: int = 3


@dataclasses.dataclass(frozen=True)
class RetrievalSignal:
    """Confidence metadata for a retrieval query's result set."""

    top1_score: float
    top2_score: float | None
    delta_top1_top2: float
    percentile_top1: float
    result_count: int
    confidence: str  # "HIGH" | "MODERATE" | "LOW" | "AMBIGUOUS"

    @classmethod
    def from_results(
        cls,
        results: list[dict[str, Any]],
        score_key: str = "reranker_score",
    ) -> RetrievalSignal:
        """Compute signal from a sorted (descending) result list.

        Parameters
        ----------
        results : list[dict]
            Results sorted by descending score.
        score_key : str
            Primary score key.  Falls back to ``"score"`` if the key is
            absent on the first result.

        """
        if not results:
            return cls(
                top1_score=0.0,
                top2_score=None,
                delta_top1_top2=0.0,
                percentile_top1=0.0,
                result_count=0,
                confidence="LOW",
            )

        # Resolve score key — prefer score_key, fallback to "score"
        first = results[0]
        if score_key not in first and "score" in first:
            score_key = "score"

        scores = [float(r.get(score_key, 0.0)) for r in results]
        top1 = scores[0]
        top2 = scores[1] if len(scores) > 1 else None
        delta = (top1 - top2) if top2 is not None else 0.0
        result_count = len(scores)

        # Percentile: fraction of results that top1 exceeds
        if result_count > 1:
            below = sum(1 for s in scores[1:] if s < top1)
            percentile = below / (result_count - 1)
        else:
            percentile = 1.0

        # Detect score scale — reranker logits can be negative / > 1;
        # cosine is bounded [0, 1].
        is_cosine = score_key == "score"
        delta_high = COSINE_DELTA_HIGH if is_cosine else RERANKER_DELTA_HIGH
        delta_moderate = COSINE_DELTA_MODERATE if is_cosine else RERANKER_DELTA_MODERATE

        # Classify confidence
        if result_count < MIN_RESULTS_FOR_HIGH:
            confidence = "LOW"
        elif delta > delta_high and result_count >= MIN_RESULTS_FOR_HIGH:
            confidence = "HIGH"
        elif delta > delta_moderate:
            confidence = "MODERATE"
        elif result_count >= MIN_RESULTS_FOR_AMBIGUOUS:
            confidence = "AMBIGUOUS"
        else:
            confidence = "LOW"

        # Edge case: if top1 is below the median, downgrade to LOW
        if result_count >= MIN_RESULTS_FOR_HIGH:
            median = statistics.median(scores)
            if top1 <= median:
                confidence = "LOW"

        return cls(
            top1_score=round(top1, 6),
            top2_score=round(top2, 6) if top2 is not None else None,
            delta_top1_top2=round(delta, 6),
            percentile_top1=round(percentile, 6),
            result_count=result_count,
            confidence=confidence,
        )
