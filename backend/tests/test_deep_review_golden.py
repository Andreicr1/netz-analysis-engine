"""Golden tests — verify zero behavioral change after deep_review modularization.

These tests capture outputs from deterministic functions BEFORE the Wave 2
package extraction and assert they remain identical AFTER the move.
"""
from __future__ import annotations

# ── Fixtures: known inputs for deterministic functions ─────────────────────


GOLDEN_CONFIDENCE_INPUT = {
    "retrieval_audit": {
        "total_chunks": 42,
        "unique_doc_types": 5,
        "source_diversity": 0.7,
        "corpus_method": "sectional_budget",
    },
    "saturation_report": {
        "saturation_ratio": 0.82,
        "total_chars_retrieved": 120_000,
        "budget_utilization": 0.75,
    },
    "hard_check_results": {
        "hard_limit_breaches": [],
        "has_hard_breaches": False,
        "requires_board_override": False,
    },
    "concentration_profile": {
        "requires_board_override": False,
        "concentration_risk_level": "moderate",
    },
    "critic_output": {
        "fatal_flaws": [],
        "confidence_score": 0.85,
        "rewrite_required": False,
    },
    "quant_profile": {
        "metrics_status": "COMPLETE",
        "has_pending_non_usd": False,
    },
    "evidence_pack_meta": {
        "chapter_count": 13,
        "chapter_scores": {
            "ch05_legal": 0.8,
            "ch06_terms": 0.9,
            "ch07_capital": 0.75,
            "ch08_returns": 0.85,
            "ch10_covenants": 0.7,
            "ch04_sponsor": 0.9,
        },
        "total_citations": 28,
    },
}

GOLDEN_DECISION_INPUT = {
    "hard_check_results": {
        "hard_limit_breaches": [],
        "has_hard_breaches": False,
        "requires_board_override": False,
    },
    "policy_dict": {
        "compliance_status": "COMPLIANT",
        "violations": [],
        "waivers_required": [],
    },
    "critic_dict": {
        "fatal_flaws": [],
        "confidence_score": 0.88,
        "rewrite_required": False,
    },
    "concentration_dict": {
        "requires_board_override": False,
    },
    "quant_dict": {
        "metrics_status": "COMPLETE",
    },
}

GOLDEN_HARD_POLICY_INPUT = {
    "concentration_dict": {
        "top_manager_pct": 0.20,
        "max_single_investment_pct": 0.08,
    },
    "analysis": {
        "currency": "USD",
        "hedged": True,
    },
    "deal_fields": {
        "lockup_period": "3 years",
    },
}


# ── Test class ─────────────────────────────────────────────────────────────


class TestGoldenConfidence:
    """Verify compute_underwriting_confidence deterministic output."""

    def test_confidence_returns_dict(self):
        from vertical_engines.credit.deep_review.confidence import (
            compute_underwriting_confidence,
        )

        result = compute_underwriting_confidence(**GOLDEN_CONFIDENCE_INPUT)
        assert isinstance(result, dict)
        assert "confidence_score" in result
        assert "confidence_level" in result
        assert "breakdown" in result
        assert "caps_applied" in result
        assert "rationale_bullets" in result

    def test_confidence_score_is_deterministic(self):
        from vertical_engines.credit.deep_review.confidence import (
            compute_underwriting_confidence,
        )

        r1 = compute_underwriting_confidence(**GOLDEN_CONFIDENCE_INPUT)
        r2 = compute_underwriting_confidence(**GOLDEN_CONFIDENCE_INPUT)
        assert r1["confidence_score"] == r2["confidence_score"]
        assert r1["confidence_level"] == r2["confidence_level"]
        assert r1["breakdown"] == r2["breakdown"]

    def test_confidence_golden_snapshot(self):
        """Exact score captured before Wave 2 — assert unchanged after move."""
        from vertical_engines.credit.deep_review.confidence import (
            compute_underwriting_confidence,
        )

        result = compute_underwriting_confidence(**GOLDEN_CONFIDENCE_INPUT)
        # Exact values captured pre-refactor (2026-03-15)
        assert result["confidence_score"] == 90
        assert result["confidence_level"] == "HIGH"
        assert result["caps_applied"] == []
        assert result["breakdown"] == {
            "evidence_coverage": 25,
            "evidence_quality": 5,
            "decision_integrity": 20,
            "diligence_gaps": 15,
            "critic_outcome": 15,
            "data_integrity": 10,
        }

    def test_confidence_hard_breach_caps_at_30(self):
        """Hard policy breach forces cap at 30 and LOW level."""
        from vertical_engines.credit.deep_review.confidence import (
            compute_underwriting_confidence,
        )

        inputs = {**GOLDEN_CONFIDENCE_INPUT}
        inputs["hard_check_results"] = {
            "hard_limit_breaches": [{"type": "manager_concentration"}],
            "has_hard_breaches": True,
            "requires_board_override": True,
        }
        result = compute_underwriting_confidence(**inputs)
        assert result["confidence_score"] <= 30
        assert result["confidence_level"] == "LOW"

    def test_tone_adjustment_never_increases(self):
        """Post-tone adjustment can only reduce score, never increase."""
        from vertical_engines.credit.deep_review.confidence import (
            apply_tone_normalizer_adjustment,
            compute_underwriting_confidence,
        )

        base = compute_underwriting_confidence(**GOLDEN_CONFIDENCE_INPUT)
        adjusted = apply_tone_normalizer_adjustment(
            base,
            tone_signal_escalated=True,
            tone_pass2_changes=[
                {"type": "material_contradiction"},
                {"type": "material_contradiction"},
            ],
        )
        assert adjusted["confidence_score"] <= base["confidence_score"]


class TestGoldenDecisionAnchor:
    """Verify _compute_decision_anchor deterministic output."""

    def test_clean_deal_invests(self):
        from vertical_engines.credit.deep_review.decision import (
            _compute_decision_anchor,
        )

        result = _compute_decision_anchor(**GOLDEN_DECISION_INPUT)
        assert result["finalDecision"] == "INVEST"
        assert result["icGate"] == "CLEAR"

    def test_hard_breach_passes(self):
        from vertical_engines.credit.deep_review.decision import (
            _compute_decision_anchor,
        )

        inputs = {**GOLDEN_DECISION_INPUT}
        inputs["hard_check_results"] = {
            "hard_limit_breaches": [{"type": "manager_concentration"}],
            "has_hard_breaches": True,
        }
        result = _compute_decision_anchor(**inputs)
        assert result["finalDecision"] == "PASS"
        assert result["icGate"] == "BLOCKED"

    def test_two_fatal_flaws_passes(self):
        from vertical_engines.credit.deep_review.decision import (
            _compute_decision_anchor,
        )

        inputs = {**GOLDEN_DECISION_INPUT}
        inputs["critic_dict"] = {
            "fatal_flaws": [
                {"confirmed": True, "description": "Flaw 1"},
                {"confirmed": True, "description": "Flaw 2"},
            ],
            "confidence_score": 0.3,
            "rewrite_required": True,
        }
        result = _compute_decision_anchor(**inputs)
        assert result["finalDecision"] == "PASS"

    def test_one_fatal_flaw_conditional(self):
        from vertical_engines.credit.deep_review.decision import (
            _compute_decision_anchor,
        )

        inputs = {**GOLDEN_DECISION_INPUT}
        inputs["critic_dict"] = {
            "fatal_flaws": [{"confirmed": True, "description": "Flaw 1"}],
            "confidence_score": 0.5,
            "rewrite_required": False,
        }
        result = _compute_decision_anchor(**inputs)
        assert result["finalDecision"] == "CONDITIONAL"

    def test_decision_is_deterministic(self):
        from vertical_engines.credit.deep_review.decision import (
            _compute_decision_anchor,
        )

        r1 = _compute_decision_anchor(**GOLDEN_DECISION_INPUT)
        r2 = _compute_decision_anchor(**GOLDEN_DECISION_INPUT)
        assert r1 == r2


class TestGoldenHardPolicyChecks:
    """Verify _run_hard_policy_checks deterministic output."""

    def test_clean_deal_no_breaches(self):
        from vertical_engines.credit.deep_review.policy import (
            _run_hard_policy_checks,
        )

        result = _run_hard_policy_checks(**GOLDEN_HARD_POLICY_INPUT)
        assert isinstance(result, dict)
        assert "hard_limit_breaches" in result
        assert "has_hard_breaches" in result
        # Clean deal should have no breaches
        assert result["has_hard_breaches"] is False

    def test_hard_checks_deterministic(self):
        from vertical_engines.credit.deep_review.policy import (
            _run_hard_policy_checks,
        )

        r1 = _run_hard_policy_checks(**GOLDEN_HARD_POLICY_INPUT)
        r2 = _run_hard_policy_checks(**GOLDEN_HARD_POLICY_INPUT)
        assert r1 == r2


class TestPackagePublicAPI:
    """Verify all __all__ symbols are importable from the package root."""

    def test_all_symbols_importable(self):
        import vertical_engines.credit.deep_review as pkg

        for name in pkg.__all__:
            attr = getattr(pkg, name)
            assert callable(attr), f"{name} should be callable"
