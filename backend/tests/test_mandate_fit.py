"""Tests for the Wealth Mandate Fit Engine — Sprint 5.

Covers:
- ClientProfile/ConstraintResult/MandateFitResult model integrity
- constraint_evaluator: risk bucket, ESG, domicile, liquidity, currency
- MandateFitService: single instrument + universe evaluation
- Suitability scoring
- Edge cases: empty profiles, missing attributes, exception handling
"""

from __future__ import annotations

import uuid

import pytest

from vertical_engines.wealth.mandate_fit.constraint_evaluator import (
    compute_suitability_score,
    evaluate_currency,
    evaluate_domicile,
    evaluate_esg,
    evaluate_liquidity,
    evaluate_risk_bucket,
)
from vertical_engines.wealth.mandate_fit.models import (
    ClientProfile,
    ConstraintResult,
    MandateFitResult,
    MandateFitRunResult,
)
from vertical_engines.wealth.mandate_fit.service import MandateFitService

# ═══════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════

def _conservative_profile() -> ClientProfile:
    return ClientProfile(
        risk_bucket="conservative",
        esg_required=True,
        domicile_restrictions=("RU", "CN"),
        max_redemption_days=30,
        currency_restrictions=("USD", "EUR"),
    )


def _aggressive_profile() -> ClientProfile:
    return ClientProfile(
        risk_bucket="aggressive",
        esg_required=False,
        domicile_restrictions=(),
        max_redemption_days=None,
        currency_restrictions=(),
    )


# ═══════════════════════════════════════════════════════════════════
#  Model integrity tests
# ═══════════════════════════════════════════════════════════════════


class TestModels:
    def test_client_profile_frozen(self):
        p = _conservative_profile()
        with pytest.raises(AttributeError):
            p.risk_bucket = "aggressive"  # type: ignore[misc]

    def test_constraint_result_frozen(self):
        r = ConstraintResult(constraint="esg", passed=True, reason="ok")
        with pytest.raises(AttributeError):
            r.passed = False  # type: ignore[misc]

    def test_mandate_fit_result_frozen(self):
        r = MandateFitResult(
            instrument_id=uuid.uuid4(),
            instrument_name="Test",
            eligible=True,
            suitability_score=1.0,
            constraint_results=(),
            disqualifying_reasons=(),
        )
        with pytest.raises(AttributeError):
            r.eligible = False  # type: ignore[misc]

    def test_run_result_frozen(self):
        r = MandateFitRunResult(
            total_evaluated=0, eligible_count=0, ineligible_count=0, results=(),
        )
        assert r.total_evaluated == 0


# ═══════════════════════════════════════════════════════════════════
#  Constraint evaluator tests
# ═══════════════════════════════════════════════════════════════════


class TestRiskBucket:
    def test_conservative_instrument_passes_conservative_profile(self):
        profile = _conservative_profile()
        r = evaluate_risk_bucket("fixed_income", {}, profile)
        assert r.passed is True

    def test_aggressive_instrument_fails_conservative_profile(self):
        profile = _conservative_profile()
        r = evaluate_risk_bucket("equity_small_cap", {}, profile)
        assert r.passed is False

    def test_moderate_instrument_passes_aggressive_profile(self):
        profile = _aggressive_profile()
        r = evaluate_risk_bucket("equity_large_cap", {}, profile)
        assert r.passed is True

    def test_explicit_risk_level_in_attributes(self):
        profile = _conservative_profile()
        r = evaluate_risk_bucket("alternatives", {"risk_level": "conservative"}, profile)
        assert r.passed is True

    def test_unknown_asset_class_defaults_aggressive(self):
        profile = _conservative_profile()
        r = evaluate_risk_bucket("exotic_derivatives", {}, profile)
        assert r.passed is False


class TestEsg:
    def test_esg_required_and_compliant(self):
        profile = _conservative_profile()
        r = evaluate_esg({"esg_compliant": True}, profile)
        assert r.passed is True

    def test_esg_required_and_not_compliant(self):
        profile = _conservative_profile()
        r = evaluate_esg({"esg_compliant": False}, profile)
        assert r.passed is False

    def test_esg_not_required(self):
        profile = _aggressive_profile()
        r = evaluate_esg({}, profile)
        assert r.passed is True

    def test_esg_missing_attribute_defaults_false(self):
        profile = _conservative_profile()
        r = evaluate_esg({}, profile)
        assert r.passed is False


class TestDomicile:
    def test_restricted_geography_fails(self):
        profile = _conservative_profile()
        r = evaluate_domicile("RU", profile)
        assert r.passed is False

    def test_allowed_geography_passes(self):
        profile = _conservative_profile()
        r = evaluate_domicile("US", profile)
        assert r.passed is True

    def test_no_restrictions(self):
        profile = _aggressive_profile()
        r = evaluate_domicile("RU", profile)
        assert r.passed is True

    def test_case_insensitive(self):
        profile = _conservative_profile()
        r = evaluate_domicile("ru", profile)
        assert r.passed is False


class TestLiquidity:
    def test_within_limit(self):
        profile = _conservative_profile()
        r = evaluate_liquidity({"redemption_days": 15}, profile)
        assert r.passed is True

    def test_exceeds_limit(self):
        profile = _conservative_profile()
        r = evaluate_liquidity({"redemption_days": 60}, profile)
        assert r.passed is False

    def test_no_requirement(self):
        profile = _aggressive_profile()
        r = evaluate_liquidity({"redemption_days": 365}, profile)
        assert r.passed is True

    def test_no_redemption_data(self):
        profile = _conservative_profile()
        r = evaluate_liquidity({}, profile)
        assert r.passed is True

    def test_non_numeric_redemption_days(self):
        profile = _conservative_profile()
        r = evaluate_liquidity({"redemption_days": "N/A"}, profile)
        assert r.passed is True
        assert "Invalid" in r.reason

    def test_string_numeric_redemption_days(self):
        profile = _conservative_profile()
        r = evaluate_liquidity({"redemption_days": "15"}, profile)
        assert r.passed is True


class TestCurrency:
    def test_allowed_currency(self):
        profile = _conservative_profile()
        r = evaluate_currency("USD", profile)
        assert r.passed is True

    def test_disallowed_currency(self):
        profile = _conservative_profile()
        r = evaluate_currency("BRL", profile)
        assert r.passed is False

    def test_no_restrictions(self):
        profile = _aggressive_profile()
        r = evaluate_currency("BRL", profile)
        assert r.passed is True


class TestSuitabilityScore:
    def test_all_pass_same_severity(self):
        results = [
            ConstraintResult("a", True, "ok", severity="hard"),
            ConstraintResult("b", True, "ok", severity="hard"),
        ]
        assert compute_suitability_score(results) == 1.0

    def test_none_pass(self):
        results = [
            ConstraintResult("a", False, "nope", severity="hard"),
            ConstraintResult("b", False, "nope", severity="soft"),
        ]
        assert compute_suitability_score(results) == 0.0

    def test_partial_hard_soft(self):
        # 1 hard pass (weight 2), 1 soft fail (weight 1) = 2/3
        results = [
            ConstraintResult("a", True, "ok", severity="hard"),
            ConstraintResult("b", False, "nope", severity="soft"),
        ]
        assert abs(compute_suitability_score(results) - 2.0 / 3.0) < 1e-9

    def test_hard_pass_scores_higher_than_soft_pass(self):
        # Institutional convention: hard PASS always contributes more than soft PASS.
        hard_only = [ConstraintResult("a", True, "ok", severity="hard")]
        soft_only = [ConstraintResult("a", True, "ok", severity="soft")]
        # Both score 1.0 individually (all-pass), but in mixed lists the weighting
        # ensures hard passes dominate. Test mixed scenario:
        mixed_hard_pass = [
            ConstraintResult("risk", True, "ok", severity="hard"),
            ConstraintResult("esg", False, "nope", severity="soft"),
        ]
        mixed_soft_pass = [
            ConstraintResult("risk", False, "nope", severity="hard"),
            ConstraintResult("esg", True, "ok", severity="soft"),
        ]
        assert compute_suitability_score(mixed_hard_pass) > compute_suitability_score(mixed_soft_pass)
        # Verify both are still 1.0 when all pass
        assert compute_suitability_score(hard_only) == 1.0
        assert compute_suitability_score(soft_only) == 1.0

    def test_empty(self):
        assert compute_suitability_score([]) == 0.0

    def test_default_severity_is_hard(self):
        r = ConstraintResult("test", True, "ok")
        assert r.severity == "hard"


# ═══════════════════════════════════════════════════════════════════
#  MandateFitService tests
# ═══════════════════════════════════════════════════════════════════


class TestMandateFitService:
    def test_eligible_instrument(self):
        svc = MandateFitService()
        result = svc.evaluate_instrument(
            instrument_id=uuid.uuid4(),
            instrument_name="ESG Bond Fund",
            instrument_type="fund",
            asset_class="fixed_income",
            geography="US",
            currency="USD",
            attributes={"esg_compliant": True, "redemption_days": 7},
            profile=_conservative_profile(),
        )
        assert result.eligible is True
        assert result.suitability_score == 1.0
        assert len(result.disqualifying_reasons) == 0

    def test_ineligible_instrument(self):
        svc = MandateFitService()
        result = svc.evaluate_instrument(
            instrument_id=uuid.uuid4(),
            instrument_name="Russian Crypto Fund",
            instrument_type="fund",
            asset_class="crypto",
            geography="RU",
            currency="RUB",
            attributes={"esg_compliant": False, "redemption_days": 90},
            profile=_conservative_profile(),
        )
        assert result.eligible is False
        assert result.suitability_score < 1.0
        # Hard failures: risk_bucket (crypto > conservative) + liquidity (90d > 30d)
        assert len(result.disqualifying_reasons) == 2
        # Soft failures: ESG + domicile + currency -> warnings
        assert len(result.warnings) == 3

    def test_universe_evaluation(self):
        svc = MandateFitService()
        instruments = [
            {
                "instrument_id": uuid.uuid4(),
                "name": "Good Fund",
                "instrument_type": "fund",
                "asset_class": "fixed_income",
                "geography": "US",
                "currency": "USD",
                "attributes": {"esg_compliant": True},
            },
            {
                "instrument_id": uuid.uuid4(),
                "name": "Bad Fund",
                "instrument_type": "fund",
                "asset_class": "crypto",
                "geography": "RU",
                "currency": "RUB",
                "attributes": {},
            },
        ]
        result = svc.evaluate_universe(instruments, _conservative_profile())
        assert result.total_evaluated == 2
        assert result.eligible_count == 1
        assert result.ineligible_count == 1

    def test_empty_universe(self):
        svc = MandateFitService()
        result = svc.evaluate_universe([], _conservative_profile())
        assert result.total_evaluated == 0


# ═══════════════════════════════════════════════════════════════════
#  Hard/soft severity discipline tests (PR-Q120)
# ═══════════════════════════════════════════════════════════════════


class TestHardSoftSeverity:
    """Tests for institutional hard/soft constraint discipline.

    Hard constraints (risk_bucket, liquidity): failure disqualifies.
    Soft constraints (ESG, domicile, currency): failure warns but does not disqualify.
    """

    def test_soft_preference_does_not_disqualify(self):
        """An ESG miss is a soft preference — instrument remains eligible."""
        svc = MandateFitService()
        result = svc.evaluate_instrument(
            instrument_id=uuid.uuid4(),
            instrument_name="Non-ESG Bond Fund",
            instrument_type="fund",
            asset_class="fixed_income",
            geography="US",
            currency="USD",
            attributes={"esg_compliant": False, "redemption_days": 7},
            profile=_conservative_profile(),
        )
        # ESG is soft — failure should NOT disqualify
        assert result.eligible is True
        assert len(result.disqualifying_reasons) == 0
        # But warning must surface for IC
        assert len(result.warnings) == 1
        assert "esg" in result.warnings[0].lower()
        # Score should be less than 1.0 (one soft miss)
        assert result.suitability_score < 1.0

    def test_hard_constraint_disqualifies(self):
        """A liquidity violation is a hard constraint — instrument is ineligible."""
        svc = MandateFitService()
        result = svc.evaluate_instrument(
            instrument_id=uuid.uuid4(),
            instrument_name="Illiquid PE Fund",
            instrument_type="fund",
            asset_class="fixed_income",  # risk_bucket passes as conservative
            geography="US",
            currency="USD",
            attributes={"esg_compliant": True, "redemption_days": 365},
            profile=_conservative_profile(),
        )
        assert result.eligible is False
        assert len(result.disqualifying_reasons) == 1
        assert "365" in result.disqualifying_reasons[0]
        assert len(result.warnings) == 0

    def test_domicile_is_soft_not_eliminatory(self):
        """Domicile mismatch must NOT disqualify (PR-Q79 decision)."""
        svc = MandateFitService()
        result = svc.evaluate_instrument(
            instrument_id=uuid.uuid4(),
            instrument_name="Russia-domiciled Bond",
            instrument_type="fund",
            asset_class="fixed_income",
            geography="RU",  # restricted by conservative profile
            currency="USD",
            attributes={"esg_compliant": True, "redemption_days": 7},
            profile=_conservative_profile(),
        )
        # Domicile is soft — eligible despite restriction match
        assert result.eligible is True
        assert len(result.disqualifying_reasons) == 0
        assert any("RU" in w for w in result.warnings)

    def test_currency_is_soft_not_eliminatory(self):
        """Currency mismatch must NOT disqualify — it is a preference."""
        svc = MandateFitService()
        result = svc.evaluate_instrument(
            instrument_id=uuid.uuid4(),
            instrument_name="BRL Bond Fund",
            instrument_type="fund",
            asset_class="fixed_income",
            geography="US",
            currency="BRL",  # not in (USD, EUR) allowed list
            attributes={"esg_compliant": True, "redemption_days": 7},
            profile=_conservative_profile(),
        )
        assert result.eligible is True
        assert len(result.disqualifying_reasons) == 0
        assert any("BRL" in w for w in result.warnings)

    def test_multiple_soft_failures_still_eligible(self):
        """Multiple soft failures (ESG + domicile + currency) do not disqualify."""
        svc = MandateFitService()
        result = svc.evaluate_instrument(
            instrument_id=uuid.uuid4(),
            instrument_name="Triple Soft Miss Fund",
            instrument_type="fund",
            asset_class="fixed_income",
            geography="RU",
            currency="BRL",
            attributes={"esg_compliant": False, "redemption_days": 7},
            profile=_conservative_profile(),
        )
        assert result.eligible is True
        assert len(result.disqualifying_reasons) == 0
        assert len(result.warnings) == 3  # ESG + domicile + currency

    def test_hard_fail_plus_soft_fail(self):
        """Hard failure disqualifies even when soft failures also present."""
        svc = MandateFitService()
        result = svc.evaluate_instrument(
            instrument_id=uuid.uuid4(),
            instrument_name="Aggressive Non-ESG Fund",
            instrument_type="fund",
            asset_class="crypto",  # hard fail: aggressive > conservative
            geography="US",
            currency="USD",
            attributes={"esg_compliant": False},  # soft fail: ESG
            profile=_conservative_profile(),
        )
        assert result.eligible is False
        assert len(result.disqualifying_reasons) == 1  # risk_bucket only
        assert len(result.warnings) == 1  # ESG only

    def test_severity_field_on_constraint_result(self):
        """ConstraintResult.severity defaults to 'hard' for backwards compat."""
        r = ConstraintResult(constraint="test", passed=True, reason="ok")
        assert r.severity == "hard"

        r_soft = ConstraintResult(constraint="test", passed=True, reason="ok", severity="soft")
        assert r_soft.severity == "soft"

    def test_warnings_field_on_mandate_fit_result(self):
        """MandateFitResult.warnings field exists and defaults to empty tuple."""
        r = MandateFitResult(
            instrument_id=uuid.uuid4(),
            instrument_name="Test",
            eligible=True,
            suitability_score=1.0,
            constraint_results=(),
            disqualifying_reasons=(),
        )
        assert r.warnings == ()
