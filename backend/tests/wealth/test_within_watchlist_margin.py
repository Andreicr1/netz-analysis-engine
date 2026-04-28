"""Regression tests for S08-F03 — _within_watchlist_margin AND-logic (PR-Q65)."""

from __future__ import annotations

from vertical_engines.wealth.screener.models import CriterionResult
from vertical_engines.wealth.screener.service import ScreenerService


def _r(criterion: str, expected: str, actual: str, passed: bool) -> CriterionResult:
    return CriterionResult(
        criterion=criterion, expected=expected, actual=actual,
        passed=passed, layer=2,
    )


# ── F03 regression: AND logic for multiple numeric failures ────────────


def test_single_marginal_failure_grants_watchlist() -> None:
    """One failure within 10% → WATCHLIST."""
    results = [_r("min_aum_usd", "100000000", "95000000", False)]  # 5% margin
    assert ScreenerService._within_watchlist_margin(results, {}) is True


def test_marginal_plus_catastrophic_blocks_watchlist() -> None:
    """One marginal + one catastrophic failure → FAIL (not WATCHLIST)."""
    results = [
        _r("min_aum_usd", "100000000", "95000000", False),  # 5% margin
        _r("min_track_record_years", "5", "1", False),  # 80% miss
    ]
    assert ScreenerService._within_watchlist_margin(results, {}) is False


def test_all_marginal_grants_watchlist() -> None:
    """All failures within 10% → WATCHLIST."""
    results = [
        _r("min_aum_usd", "100000000", "95000000", False),
        _r("max_expense_ratio_pct", "0.005", "0.0054", False),
    ]
    assert ScreenerService._within_watchlist_margin(results, {}) is True


# ── F03 regression: non-numeric failures block watchlist ───────────────


def test_geography_failure_blocks_watchlist() -> None:
    """Geography mismatch is non-numeric → FAIL even if numeric criterion is marginal."""
    results = [
        _r("geography", "IE", "US", False),  # non-numeric
        _r("min_aum_usd", "100000000", "95000000", False),  # 5% margin
    ]
    assert ScreenerService._within_watchlist_margin(results, {}) is False


def test_boolean_failure_blocks_watchlist() -> None:
    """Boolean criterion failure is non-numeric → FAIL."""
    results = [
        _r("sanctions_check", "True", "False", False),
        _r("min_aum_usd", "100000000", "95000000", False),
    ]
    assert ScreenerService._within_watchlist_margin(results, {}) is False


def test_allowed_list_failure_blocks_watchlist() -> None:
    """Allowed list mismatch is non-numeric → FAIL."""
    results = [
        _r("allowed_domiciles", "['IE', 'LU']", "KY", False),
        _r("min_aum_usd", "100000000", "95000000", False),
    ]
    assert ScreenerService._within_watchlist_margin(results, {}) is False


# ── F03 regression: edge cases ─────────────────────────────────────────


def test_zero_expected_blocks_watchlist() -> None:
    """expected=0 is ambiguous → conservative FAIL."""
    results = [_r("min_alpha", "0", "-0.01", False)]
    assert ScreenerService._within_watchlist_margin(results, {}) is False


def test_empty_results_returns_false() -> None:
    """No L2 results → no failure → False (defensive)."""
    assert ScreenerService._within_watchlist_margin([], {}) is False


def test_only_passed_results_returns_false() -> None:
    """All passed → no failures → False."""
    results = [_r("min_aum_usd", "100000000", "150000000", True)]
    assert ScreenerService._within_watchlist_margin(results, {}) is False


def test_just_outside_margin_blocks_watchlist() -> None:
    """11% miss (just outside 10% margin) → FAIL."""
    results = [_r("min_aum_usd", "100000000", "89000000", False)]  # 11% miss
    assert ScreenerService._within_watchlist_margin(results, {}) is False


def test_just_inside_margin_grants_watchlist() -> None:
    """9% miss (just inside margin) → WATCHLIST."""
    results = [_r("min_aum_usd", "100000000", "91000000", False)]  # 9% miss
    assert ScreenerService._within_watchlist_margin(results, {}) is True
