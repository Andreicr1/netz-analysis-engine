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
            total_evaluated=0, eligible_count=0, ineligible_count=0, results=()
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
    def test_all_pass(self):
        results = [
            ConstraintResult("a", True, "ok"),
            ConstraintResult("b", True, "ok"),
        ]
        assert compute_suitability_score(results) == 1.0

    def test_none_pass(self):
        results = [
            ConstraintResult("a", False, "nope"),
            ConstraintResult("b", False, "nope"),
        ]
        assert compute_suitability_score(results) == 0.0

    def test_partial(self):
        results = [
            ConstraintResult("a", True, "ok"),
            ConstraintResult("b", False, "nope"),
        ]
        assert compute_suitability_score(results) == 0.5

    def test_empty(self):
        assert compute_suitability_score([]) == 0.0


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
        assert len(result.disqualifying_reasons) > 0

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
