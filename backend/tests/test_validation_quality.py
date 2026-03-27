"""Tests for ai_engine/validation pure-logic modules.

Covers evidence_quality, citation_formatter, vector_integrity_guard,
and delta_metrics — all offline, no I/O.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_engine.validation.citation_formatter import format_citations
from ai_engine.validation.delta_metrics import (
    _clamp,
    compute_aggregate_score,
    compute_engine_quality_score,
    compute_institutional_decision,
)
from ai_engine.validation.evidence_quality import (
    compute_confidence,
    cross_validate_answer,
    recency_analysis,
)
from ai_engine.validation.validation_schema import (
    DealValidationResult,
    DeepReviewDeltaReport,
    EngineScore,
    EvidenceDensity,
    InternalConsistency,
    RecommendationDivergence,
    RiskFlagCoverageDelta,
    SponsorImpact,
)
from ai_engine.validation.vector_integrity_guard import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL_NAME,
)

# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════


def _chunk(
    *,
    chunk_text: str = "",
    chunk_id: str = "c1",
    source_blob: str = "doc.pdf",
    doc_type: str = "report",
    domain: str = "credit",
    search_score: float | None = None,
    last_modified: str | None = None,
    extraction_confidence: float = 0.5,
) -> SimpleNamespace:
    return SimpleNamespace(
        chunk_text=chunk_text,
        chunk_id=chunk_id,
        source_blob=source_blob,
        doc_type=doc_type,
        domain=domain,
        search_score=search_score,
        last_modified=last_modified,
        extraction_confidence=extraction_confidence,
    )


# ═══════════════════════════════════════════════════════════════════
#  evidence_quality — cross_validate_answer
# ═══════════════════════════════════════════════════════════════════


class TestCrossValidateAnswer:
    def test_empty_answer(self) -> None:
        result = cross_validate_answer("", [_chunk(chunk_text="some text")])
        assert result["overall_status"] == "NO_CRITICAL_CLAIMS"
        assert result["has_critical_claims"] is False

    def test_empty_chunks(self) -> None:
        result = cross_validate_answer("Revenue was $1,000", [])
        assert result["overall_status"] == "NO_CRITICAL_CLAIMS"
        assert result["has_critical_claims"] is False

    def test_no_numeric_claims(self) -> None:
        result = cross_validate_answer(
            "The company has strong governance.",
            [_chunk(chunk_text="governance framework")],
        )
        assert result["overall_status"] == "NO_CRITICAL_CLAIMS"

    def test_monetary_claim_confirmed(self) -> None:
        answer = "The deal size is $1,250,000."
        chunks = [_chunk(chunk_text="total deal size is $1250000 as reported")]
        result = cross_validate_answer(answer, chunks)
        assert result["overall_status"] == "CONFIRMED"
        assert result["has_critical_claims"] is True
        assert result["confirmed_count"] == 1

    def test_percentage_claim_unconfirmed(self) -> None:
        answer = "The yield is 18.5%."
        chunks = [_chunk(chunk_text="yield was 12.3% last quarter")]
        result = cross_validate_answer(answer, chunks)
        assert result["overall_status"] == "UNCONFIRMED"
        assert result["confirmed_count"] == 0

    def test_mixed_claims_partial(self) -> None:
        answer = "Revenue was $500,000 with 18.5% growth."
        chunks = [_chunk(chunk_text="revenue reached $500000 in the period")]
        result = cross_validate_answer(answer, chunks)
        assert result["overall_status"] == "PARTIAL"
        assert result["confirmed_count"] == 1
        assert result["total_claims"] == 2

    def test_multiple_claim_types(self) -> None:
        answer = "MOIC of 2.5x, yield 7.2%, and commitment of $10 million."
        chunks = [
            _chunk(chunk_text="moic 2.5x confirmed, yield 7.2%, commitment $10 million"),
        ]
        result = cross_validate_answer(answer, chunks)
        assert result["overall_status"] == "CONFIRMED"
        assert result["total_claims"] == 3
        assert result["confirmed_count"] == 3


# ═══════════════════════════════════════════════════════════════════
#  evidence_quality — recency_analysis
# ═══════════════════════════════════════════════════════════════════


class TestRecencyAnalysis:
    def test_empty_chunks(self) -> None:
        result = recency_analysis([])
        assert result["revisions_detected"] == []
        assert result["most_recent"] is None
        assert result["mixed_revisions"] is False

    def test_single_date(self) -> None:
        chunks = [_chunk(last_modified="2025-01-15")]
        result = recency_analysis(chunks)
        assert result["most_recent"] == "2025-01-15"
        assert result["mixed_revisions"] is False
        assert result["revisions_detected"] == ["2025-01-15"]

    def test_multiple_same_date(self) -> None:
        chunks = [
            _chunk(last_modified="2025-03-01", chunk_id="c1"),
            _chunk(last_modified="2025-03-01", chunk_id="c2"),
        ]
        result = recency_analysis(chunks)
        assert result["mixed_revisions"] is False
        assert result["revisions_detected"] == ["2025-03-01"]

    def test_different_dates_mixed(self) -> None:
        chunks = [
            _chunk(last_modified="2024-06-01", chunk_id="c1"),
            _chunk(last_modified="2025-01-15", chunk_id="c2"),
            _chunk(last_modified="2024-11-20", chunk_id="c3"),
        ]
        result = recency_analysis(chunks)
        assert result["mixed_revisions"] is True
        assert result["most_recent"] == "2025-01-15"
        assert result["revisions_detected"] == sorted(
            ["2024-06-01", "2024-11-20", "2025-01-15"],
        )
        assert result["last_modified_range"]["earliest"] == "2024-06-01"
        assert result["last_modified_range"]["latest"] == "2025-01-15"

    def test_chunks_without_dates_ignored(self) -> None:
        chunks = [
            _chunk(last_modified=None, chunk_id="c1"),
            _chunk(last_modified="2025-02-01", chunk_id="c2"),
        ]
        result = recency_analysis(chunks)
        assert result["most_recent"] == "2025-02-01"
        assert result["mixed_revisions"] is False


# ═══════════════════════════════════════════════════════════════════
#  evidence_quality — compute_confidence
# ═══════════════════════════════════════════════════════════════════


class TestComputeConfidence:
    def test_empty_chunks(self) -> None:
        result = compute_confidence([])
        assert result["retrieval_confidence"] == 0.0
        assert result["components"]["chunk_count"] == 0

    def test_with_search_scores(self) -> None:
        chunks = [
            _chunk(search_score=0.9, chunk_id="c1", source_blob="a.pdf"),
            _chunk(search_score=0.8, chunk_id="c2", source_blob="b.pdf"),
        ]
        result = compute_confidence(chunks)
        assert result["retrieval_confidence"] > 0.0
        assert result["components"]["avg_score"] == pytest.approx(0.85, abs=0.01)

    def test_source_diversity_factor(self) -> None:
        # 3 distinct sources → diversity_factor = 1.0
        chunks = [
            _chunk(search_score=0.8, chunk_id="c1", source_blob="a.pdf"),
            _chunk(search_score=0.8, chunk_id="c2", source_blob="b.pdf"),
            _chunk(search_score=0.8, chunk_id="c3", source_blob="c.pdf"),
        ]
        result_diverse = compute_confidence(chunks)

        # 1 source → diversity_factor = 1/3
        chunks_single = [
            _chunk(search_score=0.8, chunk_id="c1", source_blob="a.pdf"),
            _chunk(search_score=0.8, chunk_id="c2", source_blob="a.pdf"),
            _chunk(search_score=0.8, chunk_id="c3", source_blob="a.pdf"),
        ]
        result_single = compute_confidence(chunks_single)

        assert result_diverse["retrieval_confidence"] > result_single["retrieval_confidence"]
        assert result_diverse["components"]["source_diversity"] == 3
        assert result_single["components"]["source_diversity"] == 1

    def test_chunk_factor_capped(self) -> None:
        # 10+ chunks → chunk_factor = 1.0 (capped)
        chunks = [
            _chunk(search_score=0.8, chunk_id=f"c{i}", source_blob="doc.pdf")
            for i in range(15)
        ]
        result = compute_confidence(chunks)
        # chunk_factor = min(1.0, 15/10) = 1.0
        assert result["components"]["chunk_count"] == 15
        assert result["retrieval_confidence"] <= 1.0

    def test_domain_filter_accepted(self) -> None:
        # domain_filter param is accepted but currently not used in logic
        chunks = [_chunk(search_score=0.7, chunk_id="c1")]
        result = compute_confidence(chunks, domain_filter="credit")
        assert result["retrieval_confidence"] > 0.0


# ═══════════════════════════════════════════════════════════════════
#  citation_formatter — format_citations
# ═══════════════════════════════════════════════════════════════════


class TestFormatCitations:
    def test_deduplication(self) -> None:
        chunks = [
            _chunk(chunk_id="x1", chunk_text="hello"),
            _chunk(chunk_id="x1", chunk_text="hello"),
        ]
        citations = format_citations(chunks)
        assert len(citations) == 1
        assert citations[0]["chunk_id"] == "x1"

    def test_excerpt_truncated(self) -> None:
        long_text = "A" * 500
        chunks = [_chunk(chunk_id="c1", chunk_text=long_text)]
        citations = format_citations(chunks)
        assert len(citations[0]["excerpt"]) == 303  # 300 + "..."
        assert citations[0]["excerpt"].endswith("...")

    def test_short_text_no_ellipsis(self) -> None:
        chunks = [_chunk(chunk_id="c1", chunk_text="short")]
        citations = format_citations(chunks)
        assert citations[0]["excerpt"] == "short"
        assert not citations[0]["excerpt"].endswith("...")

    def test_all_fields_populated(self) -> None:
        chunks = [
            _chunk(
                chunk_id="abc",
                chunk_text="evidence text",
                source_blob="report.pdf",
                doc_type="ppm",
                domain="credit",
                search_score=0.92,
            ),
        ]
        citations = format_citations(chunks)
        c = citations[0]
        assert c["chunk_id"] == "abc"
        assert c["source_blob"] == "report.pdf"
        assert c["doc_type"] == "ppm"
        assert c["domain"] == "credit"
        assert c["search_score"] == 0.92
        assert c["excerpt"] == "evidence text"

    def test_unknown_fallback_for_missing_chunk_id(self) -> None:
        ns = SimpleNamespace(
            chunk_text="text",
            source_blob="x.pdf",
            doc_type="",
            domain="",
            search_score=None,
        )
        # No chunk_id attribute
        citations = format_citations([ns])
        assert citations[0]["chunk_id"] == "UNKNOWN"


# ═══════════════════════════════════════════════════════════════════
#  vector_integrity_guard — constants
# ═══════════════════════════════════════════════════════════════════


class TestVectorIntegrityGuard:
    def test_embedding_model_name(self) -> None:
        assert EMBEDDING_MODEL_NAME == "text-embedding-3-large"

    def test_embedding_dimensions(self) -> None:
        assert EMBEDDING_DIMENSIONS == 3072


# ═══════════════════════════════════════════════════════════════════
#  delta_metrics — _clamp
# ═══════════════════════════════════════════════════════════════════


class TestClamp:
    def test_within_range(self) -> None:
        assert _clamp(0.5) == 0.5

    def test_below_range(self) -> None:
        assert _clamp(-0.3) == 0.0

    def test_above_range(self) -> None:
        assert _clamp(1.5) == 1.0

    def test_custom_bounds(self) -> None:
        assert _clamp(5.0, -1.0, 1.0) == 1.0
        assert _clamp(-5.0, -1.0, 1.0) == -1.0
        assert _clamp(0.0, -1.0, 1.0) == 0.0


# ═══════════════════════════════════════════════════════════════════
#  delta_metrics — compute_engine_quality_score
# ═══════════════════════════════════════════════════════════════════


class TestComputeEngineQualityScore:
    def test_all_defaults_v4_marginal(self) -> None:
        # Default consistency_score=1.0 gives +0.8 * W_CONSISTENCY(0.10) = 0.08,
        # which exceeds the 0.05 TIE threshold, so V4 wins marginally.
        delta = DeepReviewDeltaReport(deal_id="d1")
        score = compute_engine_quality_score(delta)
        assert score.engine_winner == "V4"
        assert score.confidence >= 0.5

    def test_zero_consistency_tie(self) -> None:
        # Force consistency to a neutral zone so all dimensions are zero/tie.
        delta = DeepReviewDeltaReport(
            deal_id="d1",
            consistency=InternalConsistency(consistency_score=0.75),
        )
        score = compute_engine_quality_score(delta)
        # 0.3 * 0.10 = 0.03 < 0.05 → TIE
        assert score.engine_winner == "TIE"
        assert score.confidence == 0.5

    def test_v4_better_risk_coverage(self) -> None:
        delta = DeepReviewDeltaReport(
            deal_id="d1",
            risk_flags=RiskFlagCoverageDelta(
                risk_flags_v3=2,
                risk_flags_v4=5,
                new_flags_detected=["interest_rate", "liquidity", "concentration"],
            ),
        )
        score = compute_engine_quality_score(delta)
        assert score.engine_winner == "V4"
        assert score.confidence > 0.5

    def test_v3_better_risk_coverage(self) -> None:
        delta = DeepReviewDeltaReport(
            deal_id="d1",
            risk_flags=RiskFlagCoverageDelta(
                risk_flags_v3=6,
                risk_flags_v4=2,
                lost_flags=["market", "credit", "operational", "liquidity"],
            ),
        )
        score = compute_engine_quality_score(delta)
        assert score.engine_winner == "V3"
        assert score.confidence > 0.5

    def test_sponsor_present_with_red_flags(self) -> None:
        delta = DeepReviewDeltaReport(
            deal_id="d1",
            sponsor=SponsorImpact(
                sponsor_present=True,
                sponsor_red_flags=3,
                impact_on_final="material",
            ),
        )
        score = compute_engine_quality_score(delta)
        assert score.engine_winner == "V4"
        assert "sponsor red flags" in score.reason.lower()

    def test_recommendation_divergence_downgrade(self) -> None:
        delta = DeepReviewDeltaReport(
            deal_id="d1",
            recommendation=RecommendationDivergence(
                v3_recommendation="APPROVE",
                v4_recommendation="CONDITIONAL",
                material_divergence=True,
                divergence_direction="APPROVE→CONDITIONAL",
            ),
        )
        score = compute_engine_quality_score(delta)
        assert score.engine_winner == "V4"
        assert "conservative" in score.reason.lower()

    def test_recommendation_divergence_upgrade(self) -> None:
        delta = DeepReviewDeltaReport(
            deal_id="d1",
            recommendation=RecommendationDivergence(
                v3_recommendation="CONDITIONAL",
                v4_recommendation="APPROVE",
                material_divergence=True,
                divergence_direction="CONDITIONAL→APPROVE",
            ),
        )
        score = compute_engine_quality_score(delta)
        assert "permissive" in score.reason.lower()

    def test_evidence_with_citations(self) -> None:
        delta = DeepReviewDeltaReport(
            deal_id="d1",
            evidence=EvidenceDensity(
                evidence_surface_tokens=5000,
                citations_used=25,
                unsupported_claims_detected=False,
            ),
        )
        score = compute_engine_quality_score(delta)
        assert score.engine_winner == "V4"
        assert "citations" in score.reason.lower()

    def test_unsupported_claims_penalty(self) -> None:
        delta_clean = DeepReviewDeltaReport(
            deal_id="d1",
            evidence=EvidenceDensity(
                evidence_surface_tokens=5000,
                citations_used=15,
                unsupported_claims_detected=False,
            ),
        )
        delta_unsupported = DeepReviewDeltaReport(
            deal_id="d2",
            evidence=EvidenceDensity(
                evidence_surface_tokens=5000,
                citations_used=15,
                unsupported_claims_detected=True,
            ),
        )
        score_clean = compute_engine_quality_score(delta_clean)
        score_unsupported = compute_engine_quality_score(delta_unsupported)
        assert score_clean.confidence >= score_unsupported.confidence
        assert "unsupported" in score_unsupported.reason.lower()

    def test_consistency_high(self) -> None:
        delta = DeepReviewDeltaReport(
            deal_id="d1",
            consistency=InternalConsistency(consistency_score=0.95),
        )
        score = compute_engine_quality_score(delta)
        # High consistency alone yields a small positive composite
        assert score.engine_winner in ("V4", "TIE")

    def test_consistency_medium(self) -> None:
        delta = DeepReviewDeltaReport(
            deal_id="d1",
            consistency=InternalConsistency(consistency_score=0.75),
        )
        score = compute_engine_quality_score(delta)
        assert score.engine_winner in ("V4", "TIE")

    def test_consistency_low(self) -> None:
        delta = DeepReviewDeltaReport(
            deal_id="d1",
            consistency=InternalConsistency(
                consistency_score=0.4,
                contradictions=["risk vs recommendation", "tenor mismatch"],
            ),
        )
        score = compute_engine_quality_score(delta)
        assert "consistency" in score.reason.lower()


# ═══════════════════════════════════════════════════════════════════
#  delta_metrics — compute_aggregate_score
# ═══════════════════════════════════════════════════════════════════


class TestComputeAggregateScore:
    def test_no_deals(self) -> None:
        score = compute_aggregate_score([])
        assert score.engine_winner == "TIE"
        assert score.confidence == 0.0

    def test_majority_v4(self) -> None:
        deals = [
            DealValidationResult(
                deal_id="d1",
                deal_name="Deal A",
                engine_score=EngineScore(engine_winner="V4", confidence=0.8, reason="better"),
            ),
            DealValidationResult(
                deal_id="d2",
                deal_name="Deal B",
                engine_score=EngineScore(engine_winner="V4", confidence=0.7, reason="better"),
            ),
            DealValidationResult(
                deal_id="d3",
                deal_name="Deal C",
                engine_score=EngineScore(engine_winner="V3", confidence=0.6, reason="worse"),
            ),
        ]
        score = compute_aggregate_score(deals)
        assert score.engine_winner == "V4"

    def test_majority_v3(self) -> None:
        deals = [
            DealValidationResult(
                deal_id="d1",
                engine_score=EngineScore(engine_winner="V3", confidence=0.7, reason="v3 wins"),
            ),
            DealValidationResult(
                deal_id="d2",
                engine_score=EngineScore(engine_winner="V3", confidence=0.8, reason="v3 wins"),
            ),
            DealValidationResult(
                deal_id="d3",
                engine_score=EngineScore(engine_winner="V4", confidence=0.6, reason="v4"),
            ),
        ]
        score = compute_aggregate_score(deals)
        assert score.engine_winner == "V3"

    def test_tie_breaks_to_v4(self) -> None:
        deals = [
            DealValidationResult(
                deal_id="d1",
                engine_score=EngineScore(engine_winner="V4", confidence=0.7, reason="v4"),
            ),
            DealValidationResult(
                deal_id="d2",
                engine_score=EngineScore(engine_winner="V3", confidence=0.7, reason="v3"),
            ),
        ]
        score = compute_aggregate_score(deals)
        assert score.engine_winner == "V4"

    def test_deals_without_engine_score_skipped(self) -> None:
        deals = [
            DealValidationResult(deal_id="d1", engine_score=None),
            DealValidationResult(
                deal_id="d2",
                engine_score=EngineScore(engine_winner="V4", confidence=0.9, reason="good"),
            ),
        ]
        score = compute_aggregate_score(deals)
        assert score.engine_winner == "V4"
        assert score.confidence == pytest.approx(0.9, abs=0.01)


# ═══════════════════════════════════════════════════════════════════
#  delta_metrics — compute_institutional_decision
# ═══════════════════════════════════════════════════════════════════


class TestComputeInstitutionalDecision:
    def test_high_confidence_v4(self) -> None:
        score = EngineScore(engine_winner="V4", confidence=0.85, reason="strong")
        decision = compute_institutional_decision(score)
        assert "recommended" in decision.lower()

    def test_marginal_v4(self) -> None:
        score = EngineScore(engine_winner="V4", confidence=0.55, reason="marginal")
        decision = compute_institutional_decision(score)
        assert "marginal" in decision.lower()

    def test_v3_winner(self) -> None:
        score = EngineScore(engine_winner="V3", confidence=0.75, reason="v3 better")
        decision = compute_institutional_decision(score)
        assert "V3 retains" in decision

    def test_inconclusive(self) -> None:
        score = EngineScore(engine_winner="TIE", confidence=0.5, reason="tie")
        decision = compute_institutional_decision(score)
        assert "inconclusive" in decision.lower()
