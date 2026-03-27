"""Tests for vertical_engines.credit.pipeline.screening — context retrieval and completeness scoring."""
from __future__ import annotations

from vertical_engines.credit.pipeline.models import (
    REQUIRED_DD_DOCUMENTS,
)
from vertical_engines.credit.pipeline.screening import (
    _compute_missing_documents,
    compute_completeness_score,
)

# ── _compute_missing_documents ────────────────────────────────────


class TestComputeMissingDocuments:
    def test_all_missing_when_no_chunks(self):
        result = _compute_missing_documents([], [])
        # Should have at least some standard DD docs flagged as missing
        assert len(result) > 0

    def test_audited_financials_detected(self):
        chunks = [
            {"doc_type": "financial_statements", "title": "audited financial statement", "content": ""},
        ]
        result = _compute_missing_documents(chunks, [])
        missing_types = {d["document_type"] for d in result}
        assert "Audited Financial Statements" not in missing_types

    def test_credit_agreement_detected(self):
        chunks = [
            {"doc_type": "", "title": "credit agreement", "content": "This credit agreement between..."},
        ]
        result = _compute_missing_documents(chunks, [])
        missing_types = {d["document_type"] for d in result}
        assert "Credit Agreement / Loan Documentation" not in missing_types

    def test_insurance_detected(self):
        chunks = [
            {"doc_type": "", "title": "certificate of insurance", "content": ""},
        ]
        result = _compute_missing_documents(chunks, [])
        missing_types = {d["document_type"] for d in result}
        assert "Insurance Certificates" not in missing_types

    def test_structured_missing_merged(self):
        structured = [
            {"document_type": "Custom Missing Doc", "priority": "high", "weight": 5},
        ]
        result = _compute_missing_documents([], structured)
        types = {d["document_type"] for d in result}
        assert "Custom Missing Doc" in types

    def test_no_duplicate_entries(self):
        structured = [
            {"document_type": "Audited Financial Statements", "priority": "critical", "weight": 15},
        ]
        result = _compute_missing_documents([], structured)
        type_counts = {}
        for d in result:
            dt = d["document_type"]
            type_counts[dt] = type_counts.get(dt, 0) + 1
        # No document type should appear more than once
        for dt, count in type_counts.items():
            assert count == 1, f"Duplicate: {dt}"

    def test_tax_returns_detected(self):
        chunks = [
            {"doc_type": "", "title": "tax return filing", "content": ""},
        ]
        result = _compute_missing_documents(chunks, [])
        missing_types = {d["document_type"] for d in result}
        assert "Tax Returns (2-3 years)" not in missing_types

    def test_collateral_valuation_detected(self):
        chunks = [
            {"doc_type": "", "title": "", "content": "appraisal report for the collateral property"},
        ]
        result = _compute_missing_documents(chunks, [])
        missing_types = {d["document_type"] for d in result}
        assert "Collateral Valuation / Appraisal" not in missing_types

    def test_ucc_lien_detected(self):
        chunks = [
            {"doc_type": "", "title": "UCC filing search", "content": ""},
        ]
        result = _compute_missing_documents(chunks, [])
        missing_types = {d["document_type"] for d in result}
        assert "UCC / Lien Search Results" not in missing_types


# ── compute_completeness_score ────────────────────────────────────


class TestCompletenessScore:
    def test_perfect_score_no_missing(self):
        result = compute_completeness_score([])
        assert result["completeness_score"] == 100.0
        assert result["completeness_grade"] == "STRONG"
        assert result["documents_missing"] == 0
        assert result["documents_present"] == len(REQUIRED_DD_DOCUMENTS)

    def test_all_missing_lowest_score(self):
        all_missing = [{"document_type": d["document_type"]} for d in REQUIRED_DD_DOCUMENTS]
        result = compute_completeness_score(all_missing)
        assert result["completeness_score"] == 0.0
        assert result["completeness_grade"] == "INSUFFICIENT"
        assert result["documents_present"] == 0
        assert result["documents_missing"] == len(REQUIRED_DD_DOCUMENTS)

    def test_grade_strong(self):
        # Missing one low-weight doc
        missing = [{"document_type": "Environmental / Regulatory Compliance Reports"}]
        result = compute_completeness_score(missing)
        assert result["completeness_score"] >= 85
        assert result["completeness_grade"] == "STRONG"

    def test_grade_adequate(self):
        # Missing a few docs with combined weight bringing score between 65-85
        missing = [
            {"document_type": "Audited Financial Statements"},
            {"document_type": "Collateral Valuation / Appraisal"},
        ]
        result = compute_completeness_score(missing)
        assert 65 <= result["completeness_score"] < 85
        assert result["completeness_grade"] == "ADEQUATE"

    def test_grade_weak(self):
        # Missing critical docs bringing score below 40
        missing = [
            {"document_type": "Audited Financial Statements"},
            {"document_type": "Tax Returns (2-3 years)"},
            {"document_type": "Credit Agreement / Loan Documentation"},
            {"document_type": "Collateral Valuation / Appraisal"},
            {"document_type": "Management Accounts (Trailing 12 Months)"},
        ]
        result = compute_completeness_score(missing)
        # Combined weight = 15+12+15+12+10 = 64 out of 100 → score ~36%
        assert result["completeness_grade"] in ("WEAK", "INSUFFICIENT")

    def test_breakdown_present(self):
        result = compute_completeness_score([])
        assert "breakdown" in result
        assert len(result["breakdown"]) == len(REQUIRED_DD_DOCUMENTS)
        for dt, info in result["breakdown"].items():
            assert "priority" in info
            assert "weight" in info
            assert "present" in info
            assert info["present"] is True

    def test_total_tracked_correct(self):
        result = compute_completeness_score([])
        assert result["total_tracked"] == len(REQUIRED_DD_DOCUMENTS)

    def test_unknown_missing_doc_does_not_crash(self):
        missing = [{"document_type": "Some Unknown Document"}]
        result = compute_completeness_score(missing)
        # Should still compute correctly — unknown docs don't match any tracked doc
        assert result["completeness_score"] == 100.0
