"""Tests for pipeline components — skip_filter, governance_detector, validation gates."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

# ── Helper for chunk objects ────────────────────────────────────────

@dataclass
class _FakeChunk:
    """Minimal chunk-like object with a .text attribute for validation tests."""
    text: str
    chunk_index: int = 0


# ── skip_filter tests ───────────────────────────────────────────────


class TestSkipFilter:
    """Test should_skip_document() from extraction/skip_filter.py."""

    @pytest.mark.parametrize("filename", [
        "W-8BEN-form.pdf",
        "W-9 Tax Form.pdf",
        "FATCA Self-Certification.pdf",
        "CRS Self Cert form.pdf",
        "KYC Form - Entity.pdf",
        "AML Form 2024.pdf",
        "Beneficial Owner Declaration.pdf",
        "Anti Money Laundering Policy.pdf",
    ])
    def test_skippable_files(self, filename):
        from ai_engine.extraction.skip_filter import should_skip_document
        assert should_skip_document(filename) is True

    @pytest.mark.parametrize("filename", [
        "Credit Agreement - Fund VI.pdf",
        "LPA - Netz PCF.pdf",
        "Q1 2024 Investor Presentation.pdf",
        "Financial Statements 2023.pdf",
        "Side Letter - LP001.pdf",
    ])
    def test_non_skippable_files(self, filename):
        from ai_engine.extraction.skip_filter import should_skip_document
        assert should_skip_document(filename) is False

    def test_empty_filename(self):
        from ai_engine.extraction.skip_filter import should_skip_document
        assert should_skip_document("") is False


# ── governance_detector tests ───────────────────────────────────────


class TestGovernanceDetector:
    """Test detect_governance() from extraction/governance_detector.py."""

    def test_detects_side_letter(self):
        from ai_engine.extraction.governance_detector import detect_governance
        result = detect_governance("This side letter grants MFN rights to the investor.")
        assert result.governance_critical is True
        assert "side_letter" in result.governance_flags
        assert "most_favored_nation" in result.governance_flags

    def test_detects_carried_interest(self):
        from ai_engine.extraction.governance_detector import detect_governance
        result = detect_governance("The carried interest allocation shall be 20%.")
        assert "carried_interest" in result.governance_flags

    def test_detects_clawback(self):
        from ai_engine.extraction.governance_detector import detect_governance
        result = detect_governance("Subject to the clawback provisions in Section 8.")
        assert "clawback" in result.governance_flags

    def test_no_governance_flags(self):
        from ai_engine.extraction.governance_detector import detect_governance
        result = detect_governance("This is a quarterly investor presentation with NAV data.")
        assert result.governance_critical is False
        assert result.governance_flags == []

    def test_critical_vs_non_critical(self):
        from ai_engine.extraction.governance_detector import detect_governance
        # clawback is not in _GOVERNANCE_CRITICAL_RE, so governance_critical should be False
        result = detect_governance("The clawback mechanism applies to the GP.")
        assert result.governance_critical is False
        assert "clawback" in result.governance_flags

    def test_empty_text(self):
        from ai_engine.extraction.governance_detector import detect_governance
        result = detect_governance("")
        assert result.governance_critical is False
        assert result.governance_flags == []


# ── validation gate tests ───────────────────────────────────────────


class TestValidationGates:
    """Test validation functions from pipeline/validation.py."""

    def test_ocr_validation_passes(self):
        from ai_engine.pipeline.validation import validate_ocr_output
        result = validate_ocr_output("A" * 200, "test.pdf")
        assert result.success is True

    def test_ocr_validation_fails_short_text(self):
        from ai_engine.pipeline.validation import validate_ocr_output
        result = validate_ocr_output("short", "test.pdf")
        assert result.success is False
        assert len(result.errors) > 0

    def test_ocr_validation_fails_empty(self):
        from ai_engine.pipeline.validation import validate_ocr_output
        result = validate_ocr_output("", "test.pdf")
        assert result.success is False

    def test_chunk_validation_passes(self):
        from ai_engine.pipeline.validation import validate_chunks
        # Use _FakeChunk with .text attr so validate_chunks reads it correctly
        chunks = [_FakeChunk(text="A" * 100, chunk_index=0)]
        result = validate_chunks(chunks, 120)  # 120 input chars, 100 output = 83% retention
        assert result.success is True

    def test_chunk_validation_fails_empty(self):
        from ai_engine.pipeline.validation import validate_chunks
        result = validate_chunks([], 1000)
        assert result.success is False

    def test_chunk_validation_fails_content_loss(self):
        from ai_engine.pipeline.validation import validate_chunks
        # 100 input chars, only 10 retained = 90% loss > 25% threshold
        chunks = [_FakeChunk(text="A" * 10, chunk_index=0)]
        result = validate_chunks(chunks, 100)
        assert result.success is False
