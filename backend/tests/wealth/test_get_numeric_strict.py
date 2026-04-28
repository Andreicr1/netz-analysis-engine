"""Regression tests for S08-F10 — _get_numeric strict field matching (no fallback)."""

from __future__ import annotations

from vertical_engines.wealth.screener.layer_evaluator import LayerEvaluator


def test_exact_field_returns_value() -> None:
    """Exact field name match returns the value."""
    val = LayerEvaluator._get_numeric({"aum_usd": "100000000"}, "aum_usd")
    assert val == 100_000_000.0


def test_no_fallback_to_pct_suffix() -> None:
    """Pre-fix: requesting 'aum' would fall back to 'aum_usd' or 'aum_pct'.
    Post-fix: only exact match, returns None for missing field."""
    val = LayerEvaluator._get_numeric({"aum_pct": "0.5"}, "aum")
    assert val is None  # No fuzzy fallback to aum_pct


def test_no_fallback_to_usd_suffix() -> None:
    val = LayerEvaluator._get_numeric({"leverage_usd": "5000000"}, "leverage")
    assert val is None  # No fuzzy fallback to leverage_usd


def test_non_numeric_returns_none() -> None:
    """Non-numeric value at exact field returns None (existing behavior)."""
    val = LayerEvaluator._get_numeric({"aum_usd": "N/A"}, "aum_usd")
    assert val is None


def test_missing_field_returns_none() -> None:
    val = LayerEvaluator._get_numeric({}, "aum_usd")
    assert val is None


def test_min_aum_usd_criterion_still_works_post_fix() -> None:
    """End-to-end: criterion min_aum_usd with attribute aum_usd still evaluates."""
    evaluator = LayerEvaluator({})
    result = evaluator._evaluate_criterion(
        criterion="min_aum_usd",
        expected=100_000_000,
        attributes={"aum_usd": 150_000_000},
        instrument_type="fund",
        layer=1,
    )
    assert result is not None
    assert result.passed is True
