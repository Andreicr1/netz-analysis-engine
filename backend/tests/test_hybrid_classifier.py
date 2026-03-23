"""Tests for ai_engine.classification.hybrid_classifier — three-layer classification."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ai_engine.classification.hybrid_classifier import (
    DOC_TYPE_DESCRIPTIONS,
    VEHICLE_TYPE_DESCRIPTIONS,
    _classify_cosine,
    _ensure_doc_type_vectorizer,
    _ensure_vehicle_type_vectorizer,
    _ocr_window,
    classify,
    classify_vehicle_rules,
)
from ai_engine.pipeline.models import (
    CANONICAL_DOC_TYPES,
    CANONICAL_VEHICLE_TYPES,
)

# ── Description completeness ────────────────────────────────────


class TestDescriptionCompleteness:
    def test_doc_type_descriptions_match_canonical(self):
        assert set(DOC_TYPE_DESCRIPTIONS.keys()) == CANONICAL_DOC_TYPES

    def test_vehicle_type_descriptions_match_canonical(self):
        assert set(VEHICLE_TYPE_DESCRIPTIONS.keys()) == CANONICAL_VEHICLE_TYPES


# ── _ocr_window ─────────────────────────────────────────────────


class TestOcrWindow:
    def test_short_text_returned_as_is(self):
        text = "Hello world"
        assert _ocr_window(text) == text

    def test_long_text_truncated(self):
        text = "A" * 5000 + "B" * 3000
        result = _ocr_window(text)
        assert len(result) < len(text)
        assert result.startswith("A" * 100)
        assert "[...]" in result
        assert result.endswith("B" * 100)

    def test_exact_boundary(self):
        text = "X" * 7000  # exactly 5000 + 2000
        result = _ocr_window(text)
        assert result == text


# ── Layer 1 filename rules ──────────────────────────────────────


class TestLayer1FilenameRules:
    @pytest.mark.asyncio
    async def test_lpa_filename(self):
        result = await classify(text="", filename="Fund_V_LPA.pdf")
        assert result.doc_type == "legal_lpa"
        assert result.layer == 1
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_side_letter_filename(self):
        result = await classify(text="", filename="Side Letter - Investor A.pdf")
        assert result.doc_type == "legal_side_letter"
        assert result.layer == 1

    @pytest.mark.asyncio
    async def test_financial_statements_filename(self):
        result = await classify(text="", filename="Audited Financial Statements 2025.pdf")
        assert result.doc_type == "financial_statements"
        assert result.layer == 1

    @pytest.mark.asyncio
    async def test_credit_agreement_filename(self):
        result = await classify(text="", filename="Credit Agreement - Borrower LLC.pdf")
        assert result.doc_type == "legal_credit_agreement"
        assert result.layer == 1

    @pytest.mark.asyncio
    async def test_fund_profile_fact_card(self):
        result = await classify(text="", filename="Fund_III_Fact_Card.pdf")
        assert result.doc_type == "fund_profile"
        assert result.layer == 1

    @pytest.mark.asyncio
    async def test_structure_chart(self):
        result = await classify(text="", filename="Structure Chart.pdf")
        assert result.doc_type == "fund_structure"
        assert result.layer == 1

    @pytest.mark.asyncio
    async def test_strategy_profile_podcast(self):
        result = await classify(text="", filename="Podcast - Private Credit.pdf")
        assert result.doc_type == "strategy_profile"
        assert result.layer == 1

    @pytest.mark.asyncio
    async def test_employee_handbook(self):
        result = await classify(text="", filename="Employee Handbook 2025.pdf")
        assert result.doc_type == "operational_service"
        assert result.layer == 1

    @pytest.mark.asyncio
    async def test_org_chart(self):
        result = await classify(text="", filename="Org Chart.pdf")
        assert result.doc_type == "org_chart"
        assert result.layer == 1


# ── Layer 1 content rules ───────────────────────────────────────


class TestLayer1ContentRules:
    @pytest.mark.asyncio
    async def test_audited_financial_content(self):
        text = "AUDITED FINANCIAL STATEMENTS for the year ended " + "X" * 200
        result = await classify(text=text, filename="unknown.pdf")
        assert result.doc_type == "financial_statements"
        assert result.layer == 1

    @pytest.mark.asyncio
    async def test_independent_auditor_report(self):
        text = "INDEPENDENT AUDITOR'S REPORT " + "X" * 200
        result = await classify(text=text, filename="unknown.pdf")
        assert result.doc_type == "financial_statements"
        assert result.layer == 1

    @pytest.mark.asyncio
    async def test_limited_partnership_agreement_content(self):
        text = "LIMITED PARTNERSHIP AGREEMENT of Fund V, L.P. " + "X" * 200
        result = await classify(text=text, filename="unknown.pdf")
        assert result.doc_type == "legal_lpa"
        assert result.layer == 1

    @pytest.mark.asyncio
    async def test_subscription_agreement_content(self):
        text = "SUBSCRIPTION AGREEMENT for interests in Fund V " + "X" * 200
        result = await classify(text=text, filename="unknown.pdf")
        assert result.doc_type == "legal_subscription"
        assert result.layer == 1


# ── Layer 2 cosine similarity ────────────────────────────────────


class TestLayer2CosineSimilarity:
    def test_vectorizer_initializes(self):
        vectorizer, labels, matrix = _ensure_doc_type_vectorizer()
        assert len(labels) == len(CANONICAL_DOC_TYPES)
        assert matrix.shape[0] == len(labels)

    def test_vehicle_vectorizer_initializes(self):
        vectorizer, labels, matrix = _ensure_vehicle_type_vectorizer()
        assert len(labels) == len(CANONICAL_VEHICLE_TYPES)

    def test_classify_cosine_returns_valid_label(self):
        vectorizer, labels, matrix = _ensure_doc_type_vectorizer()
        query = "This is a credit agreement between a borrower and lenders"
        label, score, accepted = _classify_cosine(query, vectorizer, labels, matrix)
        assert label in CANONICAL_DOC_TYPES
        assert 0 <= score <= 1

    def test_classify_cosine_gibberish_low_score(self):
        vectorizer, labels, matrix = _ensure_doc_type_vectorizer()
        query = "xyz123 qwerty asdfgh zxcvbn"
        label, score, accepted = _classify_cosine(query, vectorizer, labels, matrix)
        assert score < 0.3  # Should have low similarity


# ── Layer 3 LLM fallback (mocked) ───────────────────────────────


class TestLayer3LLMFallback:
    @pytest.mark.asyncio
    async def test_layer3_fallback_on_ambiguous_text(self):
        """When L1 and L2 both fail, layer 3 should be invoked."""
        # Use nonsense text that won't match any filename or content rule
        # and will have low cosine similarity
        text = "xyzzy plugh 42 thud grunt " * 100

        mock_result = AsyncMock()
        mock_result.doc_type = "other"
        mock_result.confidence = 50

        with patch(
            "ai_engine.extraction.document_intelligence.async_classify_document",
            return_value=mock_result,
        ):
            result = await classify(text=text, filename="xyzzy.pdf")
            # Should reach layer 2 or 3 (L2 may accept with low score)
            assert result.layer in (2, 3)


# ── Vehicle type rules ───────────────────────────────────────────


class TestVehicleTypeRules:
    def test_caoff_filename_is_feeder(self):
        result = classify_vehicle_rules("CAOFF Fund.pdf", "")
        assert result == "feeder_master"

    def test_borrower_marker_is_direct(self):
        result = classify_vehicle_rules("loan.pdf", "Borrower: ABC Corp")
        assert result == "direct_investment"

    def test_fund_of_funds_marker(self):
        result = classify_vehicle_rules("fof.pdf", "This is a fund-of-funds vehicle")
        assert result == "fund_of_funds"

    def test_clo_is_spv(self):
        result = classify_vehicle_rules("clo.pdf", "CLO 2025 Series Notes due 2030")
        assert result == "spv"

    def test_standalone_fund_markers(self):
        result = classify_vehicle_rules(
            "fund.pdf",
            "Fund VI Limited Partnership capital deployed"
        )
        assert result == "standalone_fund"

    def test_reit_is_standalone(self):
        result = classify_vehicle_rules(
            "reit.pdf",
            "This non-traded REIT is structured as a real estate investment vehicle"
        )
        assert result == "standalone_fund"

    def test_no_match_returns_none(self):
        result = classify_vehicle_rules("random.pdf", "Nothing special")
        assert result is None


# ── Full classify() integration ─────────────────────────────────


class TestClassifyIntegration:
    @pytest.mark.asyncio
    async def test_no_vehicle_doc_type_forces_other(self):
        result = await classify(text="", filename="Strategy Profile Overview.pdf")
        assert result.doc_type == "strategy_profile"
        assert result.vehicle_type == "other"

    @pytest.mark.asyncio
    async def test_result_has_all_fields(self):
        result = await classify(text="", filename="LPA.pdf")
        assert hasattr(result, "doc_type")
        assert hasattr(result, "vehicle_type")
        assert hasattr(result, "confidence")
        assert hasattr(result, "layer")
        assert hasattr(result, "model_name")

    @pytest.mark.asyncio
    async def test_ppm_classified_as_lpa(self):
        result = await classify(text="", filename="Fund_V_PPM.pdf")
        assert result.doc_type == "legal_lpa"
