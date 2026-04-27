"""Regression tests for S05-F08 — composite NAV weight_sum ≈ 1.0 invariant.

§3.4 contract: weights must sum to 1.0 within tolerance (1e-4).
Previously only validated weight_sum > 0; weights summing to 0.5 silently
produced composite at 50% intended scale.
"""

from __future__ import annotations

from datetime import date

import pytest

from quant_engine.benchmark_composite_service import compute_composite_nav


def _nav(nav_date: date, return_1d: float) -> dict:
    """Helper: build a single benchmark NAV dict row."""
    return {"nav_date": nav_date, "return_1d": return_1d}


# ── Regression tests for S05-F08 (Tier 3) ──────────────────────────────────


def test_weights_summing_below_tolerance_raises():
    """Weights summing to 0.5 must raise ValueError, not silently produce
    composite at 50% intended scale."""
    block_weights = {"a": 0.3, "b": 0.2}  # sum = 0.5
    navs = {
        "a": [_nav(date(2020, 1, 1), 0.01)],
        "b": [_nav(date(2020, 1, 1), 0.01)],
    }
    with pytest.raises(ValueError, match="must sum to 1.0"):
        compute_composite_nav(block_weights, navs)


def test_weights_summing_above_tolerance_raises():
    """Weights summing to 1.2 must raise."""
    block_weights = {"a": 0.7, "b": 0.5}  # sum = 1.2
    navs = {
        "a": [_nav(date(2020, 1, 1), 0.01)],
        "b": [_nav(date(2020, 1, 1), 0.01)],
    }
    with pytest.raises(ValueError, match="must sum to 1.0"):
        compute_composite_nav(block_weights, navs)


def test_weights_at_unit_pass():
    """Control: weights summing to exactly 1.0 should work."""
    block_weights = {"a": 0.6, "b": 0.4}
    navs = {
        "a": [_nav(date(2020, 1, 1), 0.01)],
        "b": [_nav(date(2020, 1, 1), 0.01)],
    }
    result = compute_composite_nav(block_weights, navs)
    assert len(result) == 1
    assert result[0].daily_return == pytest.approx(0.01, abs=1e-9)


def test_weights_within_1e_minus_4_tolerance_pass():
    """Tolerance: 1.00009 should pass (within 1e-4)."""
    block_weights = {"a": 0.60005, "b": 0.40004}  # sum = 1.00009
    navs = {
        "a": [_nav(date(2020, 1, 1), 0.01)],
        "b": [_nav(date(2020, 1, 1), 0.01)],
    }
    # Should not raise
    result = compute_composite_nav(block_weights, navs)
    assert len(result) == 1


def test_weights_just_outside_1e_minus_4_tolerance_raises():
    """Boundary: 1.0002 (+2e-4 above) should raise."""
    block_weights = {"a": 0.6001, "b": 0.4001}  # sum = 1.0002
    navs = {
        "a": [_nav(date(2020, 1, 1), 0.01)],
        "b": [_nav(date(2020, 1, 1), 0.01)],
    }
    with pytest.raises(ValueError, match="must sum to 1.0"):
        compute_composite_nav(block_weights, navs)


def test_error_message_includes_actual_weight_sum():
    """Error message must include the offending sum for debuggability."""
    block_weights = {"a": 0.3, "b": 0.2}
    navs = {
        "a": [_nav(date(2020, 1, 1), 0.01)],
        "b": [_nav(date(2020, 1, 1), 0.01)],
    }
    with pytest.raises(ValueError) as exc_info:
        compute_composite_nav(block_weights, navs)
    assert "0.5" in str(exc_info.value) or "0.500" in str(exc_info.value)


# ── Existing-behavior preservation ─────────────────────────────────────


def test_zero_weight_sum_returns_empty():
    """Existing guard preserved: weight_sum <= 0 → empty result."""
    block_weights = {"a": 0.0, "b": 0.0}
    navs = {
        "a": [_nav(date(2020, 1, 1), 0.01)],
        "b": [_nav(date(2020, 1, 1), 0.01)],
    }
    result = compute_composite_nav(block_weights, navs)
    assert result == []


def test_negative_weight_sum_returns_empty():
    block_weights = {"a": -0.1}
    navs = {"a": [_nav(date(2020, 1, 1), 0.01)]}
    result = compute_composite_nav(block_weights, navs)
    assert result == []
