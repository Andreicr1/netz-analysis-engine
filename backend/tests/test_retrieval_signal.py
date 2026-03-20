"""Tests for RetrievalSignal confidence classification."""
from __future__ import annotations

import pytest

from ai_engine.extraction.retrieval_signal import RetrievalSignal


def _make_results(
    scores: list[float],
    score_key: str = "reranker_score",
) -> list[dict]:
    """Build a fake result list sorted descending by score_key."""
    results = [{score_key: s, "content": f"chunk {i}"} for i, s in enumerate(scores)]
    results.sort(key=lambda r: r[score_key], reverse=True)
    return results


class TestHighConfidence:
    """One dominant result with a large gap → HIGH."""

    def test_reranker_high(self):
        # top1=8.0, top2=5.0, delta=3.0 > RERANKER_DELTA_HIGH (2.0)
        results = _make_results([8.0, 5.0, 4.5, 4.0, 3.0])
        signal = RetrievalSignal.from_results(results, score_key="reranker_score")
        assert signal.confidence == "HIGH"
        assert signal.delta_top1_top2 == pytest.approx(3.0)
        assert signal.result_count == 5

    def test_cosine_high(self):
        # top1=0.95, top2=0.85, delta=0.10 > COSINE_DELTA_HIGH (0.08)
        results = _make_results([0.95, 0.85, 0.80, 0.75, 0.70], score_key="score")
        signal = RetrievalSignal.from_results(results, score_key="score")
        assert signal.confidence == "HIGH"
        assert signal.delta_top1_top2 == pytest.approx(0.10, abs=1e-4)


class TestAmbiguous:
    """Top 5 results within a tight score band → AMBIGUOUS."""

    def test_reranker_ambiguous(self):
        # All scores within 0.3 — delta < RERANKER_DELTA_MODERATE (0.5)
        results = _make_results([5.3, 5.2, 5.15, 5.1, 5.05])
        signal = RetrievalSignal.from_results(results, score_key="reranker_score")
        assert signal.confidence == "AMBIGUOUS"
        assert signal.result_count == 5

    def test_cosine_ambiguous(self):
        # All scores within 0.02 — delta < COSINE_DELTA_MODERATE (0.03)
        results = _make_results([0.90, 0.89, 0.885, 0.88, 0.879], score_key="score")
        signal = RetrievalSignal.from_results(results, score_key="score")
        assert signal.confidence == "AMBIGUOUS"


class TestLowResultCount:
    """Only 1-2 results → LOW."""

    def test_single_result(self):
        results = _make_results([7.5])
        signal = RetrievalSignal.from_results(results, score_key="reranker_score")
        assert signal.confidence == "LOW"
        assert signal.top2_score is None
        assert signal.delta_top1_top2 == 0.0

    def test_two_results(self):
        results = _make_results([7.5, 3.0])
        signal = RetrievalSignal.from_results(results, score_key="reranker_score")
        assert signal.confidence == "LOW"
        assert signal.result_count == 2


class TestModerate:
    """Clear but not dominant gap → MODERATE."""

    def test_reranker_moderate(self):
        # delta=1.0 — between RERANKER_DELTA_MODERATE (0.5) and RERANKER_DELTA_HIGH (2.0)
        results = _make_results([6.0, 5.0, 4.8, 4.5, 4.0])
        signal = RetrievalSignal.from_results(results, score_key="reranker_score")
        assert signal.confidence == "MODERATE"
        assert signal.delta_top1_top2 == pytest.approx(1.0)

    def test_cosine_moderate(self):
        # delta=0.05 — between COSINE_DELTA_MODERATE (0.03) and COSINE_DELTA_HIGH (0.08)
        results = _make_results([0.90, 0.85, 0.82, 0.80, 0.78], score_key="score")
        signal = RetrievalSignal.from_results(results, score_key="score")
        assert signal.confidence == "MODERATE"


class TestScoreKeyFallback:
    """Verifies score_key fallback logic."""

    def test_uses_reranker_score_first(self):
        results = [
            {"reranker_score": 8.0, "score": 0.5, "content": "a"},
            {"reranker_score": 3.0, "score": 0.9, "content": "b"},
            {"reranker_score": 2.0, "score": 0.8, "content": "c"},
        ]
        signal = RetrievalSignal.from_results(results, score_key="reranker_score")
        assert signal.top1_score == pytest.approx(8.0)

    def test_falls_back_to_score(self):
        results = [
            {"score": 0.95, "content": "a"},
            {"score": 0.90, "content": "b"},
            {"score": 0.85, "content": "c"},
        ]
        # Request reranker_score but it's missing — should fallback to "score"
        signal = RetrievalSignal.from_results(results, score_key="reranker_score")
        assert signal.top1_score == pytest.approx(0.95)


class TestEmptyResults:
    """Empty list → LOW with zeros."""

    def test_empty(self):
        signal = RetrievalSignal.from_results([])
        assert signal.confidence == "LOW"
        assert signal.top1_score == 0.0
        assert signal.top2_score is None
        assert signal.delta_top1_top2 == 0.0
        assert signal.percentile_top1 == 0.0
        assert signal.result_count == 0


class TestCosineVsRerankerThresholds:
    """Verify different threshold scales applied based on score_key."""

    def test_same_delta_different_scale(self):
        # delta=0.05 — HIGH for cosine (> 0.03), but far below HIGH for reranker (< 2.0)
        cosine_results = _make_results([0.90, 0.85, 0.80, 0.75, 0.70], score_key="score")
        reranker_results = _make_results([5.05, 5.0, 4.95, 4.90, 4.85], score_key="reranker_score")

        cosine_signal = RetrievalSignal.from_results(cosine_results, score_key="score")
        reranker_signal = RetrievalSignal.from_results(reranker_results, score_key="reranker_score")

        # Both have delta=0.05 but different classification
        assert cosine_signal.delta_top1_top2 == pytest.approx(0.05, abs=1e-4)
        assert reranker_signal.delta_top1_top2 == pytest.approx(0.05, abs=1e-4)

        # Cosine: 0.05 > COSINE_DELTA_MODERATE (0.03) → MODERATE
        assert cosine_signal.confidence == "MODERATE"
        # Reranker: 0.05 < RERANKER_DELTA_MODERATE (0.5) → AMBIGUOUS
        assert reranker_signal.confidence == "AMBIGUOUS"
