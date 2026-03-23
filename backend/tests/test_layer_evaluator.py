"""Tests for vertical_engines.wealth.screener.layer_evaluator — screening layer evaluation."""
from __future__ import annotations

import pytest

from vertical_engines.wealth.screener.layer_evaluator import (
    _RATING_ORDER,
    DEFAULT_HYSTERESIS_BUFFER,
    DEFAULT_PASS_THRESHOLD,
    DEFAULT_WATCHLIST_THRESHOLD,
    LayerEvaluator,
    determine_status,
)


@pytest.fixture
def evaluator():
    return LayerEvaluator(config={})


# ── Layer 1 — eliminatory criteria ───────────────────────────────


class TestLayer1:
    def test_min_threshold_passes(self, evaluator):
        criteria = {"fund": {"min_aum": 100_000_000}}
        results = evaluator.evaluate_layer1(
            "fund", {"aum": 200_000_000}, criteria
        )
        assert len(results) == 1
        assert results[0].passed is True
        assert results[0].layer == 1

    def test_min_threshold_fails(self, evaluator):
        criteria = {"fund": {"min_aum": 100_000_000}}
        results = evaluator.evaluate_layer1(
            "fund", {"aum": 50_000_000}, criteria
        )
        assert results[0].passed is False

    def test_max_threshold_passes(self, evaluator):
        criteria = {"fund": {"max_volatility": 20.0}}
        results = evaluator.evaluate_layer1(
            "fund", {"volatility": 15.0}, criteria
        )
        assert results[0].passed is True

    def test_max_threshold_fails(self, evaluator):
        criteria = {"fund": {"max_volatility": 20.0}}
        results = evaluator.evaluate_layer1(
            "fund", {"volatility": 25.0}, criteria
        )
        assert results[0].passed is False

    def test_missing_numeric_attribute_fails(self, evaluator):
        criteria = {"fund": {"min_aum": 100_000_000}}
        results = evaluator.evaluate_layer1("fund", {}, criteria)
        assert results[0].passed is False
        assert results[0].actual == "N/A"

    def test_allowed_list_passes(self, evaluator):
        criteria = {"fund": {"allowed_strategy": ["equity", "credit", "macro"]}}
        results = evaluator.evaluate_layer1(
            "fund", {"strategy": "credit"}, criteria
        )
        assert results[0].passed is True

    def test_allowed_list_fails(self, evaluator):
        criteria = {"fund": {"allowed_strategy": ["equity", "credit"]}}
        results = evaluator.evaluate_layer1(
            "fund", {"strategy": "crypto"}, criteria
        )
        assert results[0].passed is False

    def test_excluded_list_passes(self, evaluator):
        criteria = {"fund": {"excluded_geography": ["sanctioned_country"]}}
        results = evaluator.evaluate_layer1(
            "fund", {"geography": "USA"}, criteria
        )
        assert results[0].passed is True

    def test_excluded_list_fails(self, evaluator):
        criteria = {"fund": {"excluded_geography": ["sanctioned_country"]}}
        results = evaluator.evaluate_layer1(
            "fund", {"geography": "sanctioned_country"}, criteria
        )
        assert results[0].passed is False

    def test_empty_exclusion_list_passes(self, evaluator):
        criteria = {"fund": {"excluded_geography": []}}
        results = evaluator.evaluate_layer1(
            "fund", {"geography": "anything"}, criteria
        )
        assert results[0].passed is True

    def test_boolean_criterion(self, evaluator):
        criteria = {"fund": {"sanctions_check": True}}
        results = evaluator.evaluate_layer1(
            "fund", {"sanctions_check": True}, criteria
        )
        assert results[0].passed is True

    def test_boolean_criterion_fails(self, evaluator):
        criteria = {"fund": {"sanctions_check": True}}
        results = evaluator.evaluate_layer1(
            "fund", {"sanctions_check": False}, criteria
        )
        assert results[0].passed is False

    def test_credit_rating_floor_passes(self, evaluator):
        criteria = {"bond": {"min_credit_rating": "BBB-"}}
        results = evaluator.evaluate_layer1(
            "bond", {"credit_rating_sp": "A+"}, criteria
        )
        assert results[0].passed is True

    def test_credit_rating_floor_fails(self, evaluator):
        criteria = {"bond": {"min_credit_rating": "BBB-"}}
        results = evaluator.evaluate_layer1(
            "bond", {"credit_rating_sp": "BB+"}, criteria
        )
        assert results[0].passed is False

    def test_unknown_instrument_type_empty(self, evaluator):
        criteria = {"fund": {"min_aum": 100}}
        results = evaluator.evaluate_layer1("unknown", {}, criteria)
        assert len(results) == 0

    def test_asset_class_exact_match(self, evaluator):
        criteria = {"fund": {"asset_class": "equity"}}
        results = evaluator.evaluate_layer1(
            "fund", {"asset_class": "Equity"}, criteria
        )
        assert results[0].passed is True  # case-insensitive

    def test_geography_exact_match(self, evaluator):
        criteria = {"fund": {"geography": "us"}}
        results = evaluator.evaluate_layer1(
            "fund", {"geography": "US"}, criteria
        )
        assert results[0].passed is True

    def test_unknown_criterion_returns_none(self, evaluator):
        criteria = {"fund": {"some_unknown_criterion": "value"}}
        results = evaluator.evaluate_layer1("fund", {}, criteria)
        assert len(results) == 0

    def test_numeric_field_with_usd_suffix(self, evaluator):
        criteria = {"fund": {"min_aum": 100}}
        results = evaluator.evaluate_layer1(
            "fund", {"aum_usd": 200}, criteria
        )
        assert results[0].passed is True


# ── Layer 2 — mandate fit ────────────────────────────────────────


class TestLayer2:
    def test_block_criteria_applied(self, evaluator):
        criteria = {
            "blocks": {
                "block_a": {
                    "criteria": {"min_aum": 50_000_000}
                }
            }
        }
        results = evaluator.evaluate_layer2(
            "fund", {"aum": 100_000_000}, "block_a", criteria
        )
        assert len(results) == 1
        assert results[0].passed is True
        assert results[0].layer == 2

    def test_none_block_id_returns_empty(self, evaluator):
        results = evaluator.evaluate_layer2("fund", {}, None, {})
        assert results == []

    def test_unknown_block_returns_empty(self, evaluator):
        criteria = {"blocks": {}}
        results = evaluator.evaluate_layer2("fund", {}, "nonexistent", criteria)
        assert results == []


# ── determine_status ──────────────────────────────────────────────


class TestDetermineStatus:
    def test_none_score_returns_watchlist(self):
        assert determine_status(None, None) == "WATCHLIST"

    def test_first_screening_pass(self):
        assert determine_status(0.7, None) == "PASS"

    def test_first_screening_watchlist(self):
        assert determine_status(0.5, None) == "WATCHLIST"

    def test_first_screening_fail(self):
        assert determine_status(0.2, None) == "FAIL"

    def test_watchlist_to_pass_requires_buffer(self):
        # Exactly at threshold — not promoted
        assert determine_status(DEFAULT_PASS_THRESHOLD, "WATCHLIST") == "WATCHLIST"
        # Above threshold + buffer → promoted
        assert determine_status(
            DEFAULT_PASS_THRESHOLD + DEFAULT_HYSTERESIS_BUFFER + 0.01,
            "WATCHLIST"
        ) == "PASS"

    def test_watchlist_to_fail_requires_buffer(self):
        # Just below watchlist threshold but within buffer → stays WATCHLIST
        val = DEFAULT_WATCHLIST_THRESHOLD - DEFAULT_HYSTERESIS_BUFFER + 0.01
        assert determine_status(val, "WATCHLIST") == "WATCHLIST"
        # Well below → FAIL
        assert determine_status(
            DEFAULT_WATCHLIST_THRESHOLD - DEFAULT_HYSTERESIS_BUFFER - 0.01,
            "WATCHLIST"
        ) == "FAIL"

    def test_pass_to_watchlist_requires_buffer(self):
        # Just below threshold but within buffer → stays PASS
        assert determine_status(
            DEFAULT_PASS_THRESHOLD - DEFAULT_HYSTERESIS_BUFFER + 0.01,
            "PASS"
        ) == "PASS"
        # Well below threshold → demoted
        assert determine_status(
            DEFAULT_PASS_THRESHOLD - DEFAULT_HYSTERESIS_BUFFER - 0.01,
            "PASS"
        ) == "WATCHLIST"

    def test_pass_to_fail(self):
        assert determine_status(0.1, "PASS") == "FAIL"

    def test_custom_thresholds(self):
        thresholds = {
            "pass_threshold": 0.8,
            "watchlist_threshold": 0.5,
            "hysteresis_buffer": 0.1,
        }
        assert determine_status(0.91, "WATCHLIST", thresholds) == "PASS"
        assert determine_status(0.85, "WATCHLIST", thresholds) == "WATCHLIST"

    def test_fail_status_no_hysteresis(self):
        assert determine_status(0.7, "FAIL") == "PASS"
        assert determine_status(0.5, "FAIL") == "WATCHLIST"
        assert determine_status(0.2, "FAIL") == "FAIL"


# ── Rating order ──────────────────────────────────────────────────


class TestRatingOrder:
    def test_aaa_highest(self):
        assert _RATING_ORDER["AAA"] == max(_RATING_ORDER.values())

    def test_d_lowest(self):
        assert _RATING_ORDER["D"] == min(_RATING_ORDER.values())

    def test_investment_grade_boundary(self):
        assert _RATING_ORDER["BBB-"] > _RATING_ORDER["BB+"]

    def test_all_standard_ratings_present(self):
        expected = [
            "AAA", "AA+", "AA", "AA-",
            "A+", "A", "A-",
            "BBB+", "BBB", "BBB-",
            "BB+", "BB", "BB-",
            "B+", "B", "B-",
            "CCC+", "CCC", "CCC-",
            "CC", "C", "D",
        ]
        for rating in expected:
            assert rating in _RATING_ORDER
