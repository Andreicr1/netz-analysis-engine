"""Tests for pure-logic functions in ai_engine/extraction/.

Covers: skip_filter, governance_detector, retrieval_signal,
embed_chunks.build_embed_text, and obligation_extractor helpers.
All tests run offline — no DB, no API calls.
"""
from __future__ import annotations

import pytest

from ai_engine.extraction.embed_chunks import EMBED_MAX_CHARS, build_embed_text
from ai_engine.extraction.governance_detector import GovernanceResult, detect_governance
from ai_engine.extraction.obligation_extractor import (
    _evidence_expected,
    _infer_due_rule,
    _infer_frequency,
    _infer_responsible_party,
    _infer_source,
)
from ai_engine.extraction.retrieval_signal import (
    RetrievalSignal,
)
from ai_engine.extraction.skip_filter import should_skip_document

# =====================================================================
# 1. skip_filter — should_skip_document
# =====================================================================


class TestSkipFilter:
    """should_skip_document returns True for compliance/tax forms."""

    @pytest.mark.parametrize(
        "filename",
        [
            "W-8BEN_Form_2024.pdf",
            "W-9_Signed.pdf",
            "FATCA_Declaration.pdf",
            "CRS Self-Certification Form.pdf",
            "CRS_Tax_Self_Cert.pdf",
            "Self-Certification Form.pdf",
            "KYC Form - Fund III.pdf",
            "AML Form Completed.pdf",
            "Beneficial Owner Declaration.pdf",
            "Anti Money Laundering Policy.pdf",
        ],
    )
    def test_should_skip_compliance_forms(self, filename: str) -> None:
        assert should_skip_document(filename) is True

    @pytest.mark.parametrize(
        "filename",
        [
            "LPA_Fund_III_Final.pdf",
            "Financial Statements Q4 2024.pdf",
            "Subscription Agreement.pdf",
            "Private Placement Memorandum.pdf",
            "IC Memo - Acme Corp.pdf",
            "Quarterly Report.pdf",
            "Due Diligence Report.pdf",
            "Side Letter Agreement.pdf",
            "Term Sheet.pdf",
        ],
    )
    def test_should_not_skip_analytical_docs(self, filename: str) -> None:
        assert should_skip_document(filename) is False

    @pytest.mark.parametrize(
        "filename",
        [
            "w-8ben_form.pdf",
            "w-9_signed.pdf",
            "fatca_declaration.pdf",
            "kyc form.pdf",
            "aml form.pdf",
            "beneficial owner.pdf",
            "anti money laundering.pdf",
            "W-8BEN",
            "FATCA",
        ],
    )
    def test_case_insensitivity(self, filename: str) -> None:
        assert should_skip_document(filename) is True

    def test_empty_filename(self) -> None:
        assert should_skip_document("") is False


# =====================================================================
# 2. governance_detector — detect_governance
# =====================================================================


class TestGovernanceDetector:
    """detect_governance finds governance patterns and flags critical ones."""

    @pytest.mark.parametrize(
        "text,expected_flag",
        [
            ("This side letter grants preferential terms.", "side_letter"),
            ("Subject to most favored nation provisions.", "most_favored_nation"),
            ("Subject to most-favored-nation clause.", "most_favored_nation"),
            ("MFN rights apply to all investors.", "most_favored_nation"),
            ("The key person clause is triggered.", "key_person_clause"),
            ("The keyman event has occurred.", "key_person_clause"),
            ("key-person provisions apply.", "key_person_clause"),
            ("Subject to clawback provisions.", "clawback"),
            ("The claw-back mechanism is described here.", "clawback"),
            ("Carried interest is 20% above hurdle.", "carried_interest"),
            ("Performance fee of 2% applies.", "carried_interest"),
            ("Performance allocation shall be computed.", "carried_interest"),
            ("Promote interest accrues to the GP.", "carried_interest"),
            ("A fee rebate of 50 bps is offered.", "fee_rebate"),
            ("Fee waiver for early investors.", "fee_rebate"),
            ("Management fee offset mechanism.", "fee_rebate"),
            ("A gating provision limits redemptions.", "gating_provision"),
            ("The redemption gate is set at 25%.", "gating_provision"),
            ("Suspension of redemption may occur.", "suspension_of_redemptions"),
            ("The board may suspend redemption rights.", "suspension_of_redemptions"),
            ("Concentration limit of 20% per issuer.", "concentration_limit"),
            ("Concentration cap shall not exceed 15%.", "concentration_limit"),
            ("Board override required for exceptions.", "board_override"),
            ("Board resolution to approve the investment.", "board_override"),
            ("Board approval is needed.", "board_override"),
            ("An investment limit exception was granted.", "investment_limit_exception"),
            ("A policy exception was documented.", "investment_limit_exception"),
            ("The policy override was approved.", "policy_override"),
            ("Conflicts of interest must be disclosed.", "conflicts_of_interest"),
            ("Conflict of interest arises when...", "conflicts_of_interest"),
            ("Related party transactions require approval.", "related_party"),
            ("Related-party transaction with affiliate.", "related_party"),
            ("The fund-of-funds structure includes...", "fund_of_funds_structure"),
            ("This is a FoF vehicle.", "fund_of_funds_structure"),
            ("Invests in underlying fund interests.", "fund_of_funds_structure"),
        ],
    )
    def test_individual_pattern_detection(self, text: str, expected_flag: str) -> None:
        result = detect_governance(text)
        assert expected_flag in result.governance_flags

    @pytest.mark.parametrize(
        "text",
        [
            "This side letter grants preferential terms.",
            "Subject to most favored nation provisions.",
            "MFN rights apply to all investors.",
            "A fee rebate of 50 bps is offered.",
            "Fee waiver for early investors.",
            "Board override required for exceptions.",
            "An investment limit exception was granted.",
            "The fund-of-funds structure includes...",
        ],
    )
    def test_governance_critical_true(self, text: str) -> None:
        result = detect_governance(text)
        assert result.governance_critical is True

    @pytest.mark.parametrize(
        "text",
        [
            "Subject to clawback provisions.",
            "Carried interest is 20% above hurdle.",
            "Gating provision limits redemptions to 25%.",
            "Concentration limit of 20% per issuer.",
            "Policy override was approved.",
            "Conflicts of interest must be disclosed.",
            "Related party transactions require approval.",
            "Key person clause is triggered.",
        ],
    )
    def test_governance_critical_false(self, text: str) -> None:
        result = detect_governance(text)
        assert result.governance_critical is False

    def test_empty_text(self) -> None:
        result = detect_governance("")
        assert result.governance_critical is False
        assert result.governance_flags == []

    def test_no_matches(self) -> None:
        result = detect_governance("The fund invests in diversified credit portfolios.")
        assert result.governance_critical is False
        assert result.governance_flags == []

    def test_multiple_flags(self) -> None:
        text = (
            "The side letter includes a fee rebate and clawback provisions. "
            "Board override is required for any policy exception."
        )
        result = detect_governance(text)
        assert "side_letter" in result.governance_flags
        assert "fee_rebate" in result.governance_flags
        assert "clawback" in result.governance_flags
        assert "board_override" in result.governance_flags
        assert "investment_limit_exception" in result.governance_flags
        assert result.governance_critical is True

    def test_result_is_frozen_dataclass(self) -> None:
        result = detect_governance("side letter")
        assert isinstance(result, GovernanceResult)
        with pytest.raises(AttributeError):
            result.governance_critical = False  # type: ignore[misc]


# =====================================================================
# 3. retrieval_signal — RetrievalSignal.from_results
# =====================================================================


class TestRetrievalSignal:
    """RetrievalSignal.from_results computes delta-based confidence."""

    def test_empty_results(self) -> None:
        signal = RetrievalSignal.from_results([])
        assert signal.confidence == "LOW"
        assert signal.result_count == 0
        assert signal.top1_score == 0.0
        assert signal.top2_score is None
        assert signal.delta_top1_top2 == 0.0
        assert signal.percentile_top1 == 0.0

    def test_single_result_is_low(self) -> None:
        results = [{"reranker_score": 5.0}]
        signal = RetrievalSignal.from_results(results)
        assert signal.confidence == "LOW"
        assert signal.result_count == 1
        assert signal.top2_score is None
        assert signal.percentile_top1 == 1.0

    def test_two_results_below_min_for_high(self) -> None:
        results = [{"reranker_score": 8.0}, {"reranker_score": 1.0}]
        signal = RetrievalSignal.from_results(results)
        assert signal.confidence == "LOW"
        assert signal.result_count == 2

    def test_high_confidence_reranker_scale(self) -> None:
        # 3+ results, large delta (> RERANKER_DELTA_HIGH=2.0)
        results = [
            {"reranker_score": 10.0},
            {"reranker_score": 5.0},
            {"reranker_score": 3.0},
        ]
        signal = RetrievalSignal.from_results(results)
        assert signal.confidence == "HIGH"
        assert signal.delta_top1_top2 == 5.0

    def test_moderate_confidence_reranker_scale(self) -> None:
        # 3+ results, delta between MODERATE and HIGH thresholds
        results = [
            {"reranker_score": 5.0},
            {"reranker_score": 4.0},
            {"reranker_score": 2.0},
        ]
        signal = RetrievalSignal.from_results(results)
        assert signal.confidence == "MODERATE"
        assert signal.delta_top1_top2 == 1.0

    def test_ambiguous_many_results_small_delta(self) -> None:
        # 5+ results, tiny delta
        results = [
            {"reranker_score": 5.0},
            {"reranker_score": 4.9},
            {"reranker_score": 4.8},
            {"reranker_score": 4.7},
            {"reranker_score": 4.6},
        ]
        signal = RetrievalSignal.from_results(results)
        assert signal.confidence == "AMBIGUOUS"

    def test_score_key_fallback_to_score(self) -> None:
        results = [
            {"score": 0.95},
            {"score": 0.80},
            {"score": 0.70},
        ]
        signal = RetrievalSignal.from_results(results, score_key="reranker_score")
        # reranker_score absent, falls back to "score" (cosine scale)
        assert signal.top1_score == 0.95
        assert signal.top2_score == 0.80

    def test_cosine_scale_detection(self) -> None:
        # score_key="score" uses cosine thresholds
        results = [
            {"score": 0.95},
            {"score": 0.80},
            {"score": 0.70},
        ]
        signal = RetrievalSignal.from_results(results, score_key="score")
        # delta = 0.15 > COSINE_DELTA_HIGH (0.08)
        assert signal.confidence == "HIGH"

    def test_cosine_moderate(self) -> None:
        results = [
            {"score": 0.90},
            {"score": 0.85},
            {"score": 0.80},
        ]
        signal = RetrievalSignal.from_results(results, score_key="score")
        # delta = 0.05, between COSINE_DELTA_MODERATE (0.03) and COSINE_DELTA_HIGH (0.08)
        assert signal.confidence == "MODERATE"

    def test_top1_below_median_downgrade_to_low(self) -> None:
        # Craft a scenario where top1 <= median despite being first
        # scores are NOT sorted descending (caller error), so top1 is low
        results = [
            {"reranker_score": 1.0},
            {"reranker_score": 5.0},
            {"reranker_score": 6.0},
        ]
        signal = RetrievalSignal.from_results(results)
        # top1=1.0, median=5.0 → top1 <= median → downgrade
        assert signal.confidence == "LOW"

    def test_percentile_calculation(self) -> None:
        results = [
            {"reranker_score": 10.0},
            {"reranker_score": 5.0},
            {"reranker_score": 3.0},
            {"reranker_score": 1.0},
        ]
        signal = RetrievalSignal.from_results(results)
        # top1=10.0, 3 results below → percentile = 3/3 = 1.0
        assert signal.percentile_top1 == 1.0

    def test_percentile_partial(self) -> None:
        results = [
            {"reranker_score": 5.0},
            {"reranker_score": 5.0},
            {"reranker_score": 3.0},
            {"reranker_score": 1.0},
        ]
        signal = RetrievalSignal.from_results(results)
        # top1=5.0, scores[1:] = [5.0, 3.0, 1.0]
        # below = 2 (3.0 and 1.0 are < 5.0, but 5.0 is not < 5.0)
        # percentile = 2/3
        assert round(signal.percentile_top1, 6) == round(2 / 3, 6)

    def test_frozen_dataclass(self) -> None:
        signal = RetrievalSignal.from_results([])
        with pytest.raises(AttributeError):
            signal.confidence = "HIGH"  # type: ignore[misc]

    def test_default_score_key(self) -> None:
        results = [
            {"reranker_score": 10.0},
            {"reranker_score": 5.0},
            {"reranker_score": 3.0},
        ]
        signal = RetrievalSignal.from_results(results)
        assert signal.top1_score == 10.0

    def test_missing_score_key_defaults_zero(self) -> None:
        # Neither reranker_score nor score present
        results = [{"other": 1.0}, {"other": 2.0}, {"other": 3.0}]
        signal = RetrievalSignal.from_results(results, score_key="reranker_score")
        assert signal.top1_score == 0.0


# =====================================================================
# 4. embed_chunks — build_embed_text
# =====================================================================


class TestBuildEmbedText:
    """build_embed_text prepends breadcrumb and truncates."""

    def test_breadcrumb_prepended(self) -> None:
        chunk = {"breadcrumb": "Fee Structure > Management Fee", "content": "The fee is 2%."}
        result = build_embed_text(chunk)
        assert result == "Fee Structure > Management Fee\n\nThe fee is 2%."

    def test_no_double_prepend(self) -> None:
        chunk = {
            "breadcrumb": "Fee Structure",
            "content": "[Fee Structure] The fee is 2%.",
        }
        result = build_embed_text(chunk)
        assert result == "[Fee Structure] The fee is 2%."

    def test_truncation_at_max_chars(self) -> None:
        long_content = "A" * (EMBED_MAX_CHARS + 1000)
        chunk = {"breadcrumb": "", "content": long_content}
        result = build_embed_text(chunk)
        assert len(result) == EMBED_MAX_CHARS

    def test_truncation_with_breadcrumb(self) -> None:
        breadcrumb = "Section"
        long_content = "B" * (EMBED_MAX_CHARS + 500)
        chunk = {"breadcrumb": breadcrumb, "content": long_content}
        result = build_embed_text(chunk)
        assert len(result) == EMBED_MAX_CHARS
        assert result.startswith("Section\n\n")

    def test_empty_breadcrumb(self) -> None:
        chunk = {"breadcrumb": "", "content": "Some content here."}
        result = build_embed_text(chunk)
        assert result == "Some content here."

    def test_empty_content(self) -> None:
        chunk = {"breadcrumb": "Header", "content": ""}
        result = build_embed_text(chunk)
        # breadcrumb is truthy but content is empty → prepend happens
        assert result == "Header\n\n"

    def test_both_empty(self) -> None:
        chunk = {"breadcrumb": "", "content": ""}
        result = build_embed_text(chunk)
        assert result == ""

    def test_missing_keys(self) -> None:
        chunk: dict[str, str] = {}
        result = build_embed_text(chunk)
        assert result == ""

    def test_content_exactly_at_limit(self) -> None:
        chunk = {"breadcrumb": "", "content": "C" * EMBED_MAX_CHARS}
        result = build_embed_text(chunk)
        assert len(result) == EMBED_MAX_CHARS


# =====================================================================
# 5. obligation_extractor — pure helper functions
# =====================================================================


class TestInferSource:
    """_infer_source maps path keywords to source categories."""

    @pytest.mark.parametrize(
        "path_text,expected",
        [
            ("Legal/CIMA/Annual Filing.pdf", "CIMA"),
            ("Regulatory/AML Compliance.pdf", "CIMA"),
            ("cima_reports/q4.pdf", "CIMA"),
            ("Admin/NAV Reports/nav_q4.pdf", "Admin"),
            ("Fund Administrator/Statements.pdf", "Admin"),
            ("Custodian/Account Statement.pdf", "Custodian"),
            ("Bank/Confirmation Letter.pdf", "Custodian"),
            ("Offering/PPM.pdf", "Offering"),
            ("Legal/LPA_v2.pdf", "Offering"),
            ("", "Offering"),
        ],
    )
    def test_infer_source(self, path_text: str, expected: str) -> None:
        assert _infer_source(path_text) == expected


class TestInferFrequency:
    """_infer_frequency extracts reporting frequency from obligation text."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Deliver quarterly financial statements.", "Quarterly"),
            ("Submit annual audited report.", "Annual"),
            ("File annually with CIMA.", "Annual"),
            ("Must comply with all applicable laws.", "Ongoing"),
            ("Notify immediately upon breach.", "Ongoing"),
            ("", "Ongoing"),
        ],
    )
    def test_infer_frequency(self, text: str, expected: str) -> None:
        assert _infer_frequency(text) == expected


class TestInferDueRule:
    """_infer_due_rule extracts deadlines from obligation text."""

    def test_within_days_pattern(self) -> None:
        text = "Must be submitted within 30 days after the fiscal year end."
        result = _infer_due_rule(text)
        assert "within 30 days after" in result

    def test_months_after_fy_end(self) -> None:
        text = "Deliver audited statements 6 months after fy end."
        result = _infer_due_rule(text)
        assert "6 months after fy end" in result

    def test_iso_date_fallback(self) -> None:
        text = "The report is due by 2025-03-31 to the administrator."
        result = _infer_due_rule(text)
        assert result == "Due on 2025-03-31"

    def test_default_when_no_match(self) -> None:
        text = "Shall maintain proper books and records at all times."
        result = _infer_due_rule(text)
        assert result == "Ongoing - immediate compliance"

    def test_empty_text(self) -> None:
        assert _infer_due_rule("") == "Ongoing - immediate compliance"


class TestInferResponsibleParty:
    """_infer_responsible_party maps source + text to responsible party."""

    @pytest.mark.parametrize(
        "source,text,expected",
        [
            ("Offering", "The investment manager shall deliver...", "Investment Manager"),
            ("Offering", "The manager shall submit...", "Investment Manager"),
            ("Admin", "File the report.", "Fund Administrator"),
            ("Offering", "The administrator shall compute NAV.", "Fund Administrator"),
            ("Custodian", "Hold assets in safekeeping.", "Custodian"),
            ("Offering", "The custodian shall provide statements.", "Custodian"),
            ("Offering", "The bank shall issue confirmations.", "Custodian"),
            ("Offering", "Counsel shall review the agreement.", "Legal Counsel"),
            ("Offering", "Legal review required for amendments.", "Legal Counsel"),
            ("CIMA", "File the annual return.", "Compliance Officer"),
            ("Offering", "The fund shall distribute proceeds.", "Fund Management"),
        ],
    )
    def test_infer_responsible_party(
        self, source: str, text: str, expected: str
    ) -> None:
        assert _infer_responsible_party(source, text) == expected


class TestEvidenceExpected:
    """_evidence_expected maps source to evidence type."""

    @pytest.mark.parametrize(
        "source,expected",
        [
            ("CIMA", "Regulatory filing receipt"),
            ("Admin", "Administrator report / confirmation"),
            ("Custodian", "Custodian statement"),
            ("Offering", "Board-approved offering compliance evidence"),
        ],
    )
    def test_known_sources(self, source: str, expected: str) -> None:
        assert _evidence_expected(source) == expected

    def test_unknown_source(self) -> None:
        assert _evidence_expected("Unknown") == "Formal evidence document"
