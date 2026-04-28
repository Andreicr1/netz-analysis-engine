"""Regression tests for S08-F05 — compute_bond_metrics insufficient-data guard (PR-Q67)."""

from __future__ import annotations

import pytest

from vertical_engines.wealth.screener.quant_metrics import (
    BondQuantMetrics,
    compute_bond_metrics,
)

# ── F05 regression: empty attributes returns None ──────────────────────


def test_empty_attributes_returns_none() -> None:
    """compute_bond_metrics({}) returns None — insufficient data signal."""
    result = compute_bond_metrics({})
    assert result is None


def test_only_data_source_returns_none() -> None:
    """Attributes with only metadata field → None (no enrichment)."""
    result = compute_bond_metrics({"data_source": "csv"})
    assert result is None


def test_only_irrelevant_fields_returns_none() -> None:
    """Attributes with no required field → None."""
    result = compute_bond_metrics({"isin": "US123", "issuer": "Acme"})
    assert result is None


# ── F05 regression: any required field present → returns metrics ───────


def test_one_required_field_returns_metrics_with_zero_for_missing() -> None:
    """If at least one required field present, return metrics (don't None-block).

    Caller may still deprecate via composite_score's MIN_COVERAGE_RATIO gate.
    """
    result = compute_bond_metrics({"coupon_rate_pct": 5.0})
    assert result is not None
    assert isinstance(result, BondQuantMetrics)


def test_full_attributes_returns_real_metrics() -> None:
    """All fields present → real metrics computed."""
    attrs = {
        "coupon_rate_pct": 5.0,
        "outstanding_usd": 100_000_000.0,
        "face_value_usd": 100_000_000.0,
        "duration_years": 8.0,
        "benchmark_yield_pct": 4.5,
        "data_source": "csv",
    }
    result = compute_bond_metrics(attrs)
    assert result is not None
    assert result.spread_vs_benchmark_bps == pytest.approx(50.0)  # (5.0 - 4.5) * 100
    assert result.liquidity_score == pytest.approx(1.0)  # outstanding == face_value
    assert result.duration_efficiency == pytest.approx(0.625)  # 5.0 / 8.0


# ── F05 regression: malformed input still returns None ─────────────────


def test_non_numeric_required_field_returns_none() -> None:
    """Non-numeric value in required field → None (existing try/except path)."""
    result = compute_bond_metrics({"coupon_rate_pct": "not a number"})
    # The required-field guard PASSES (coupon_rate_pct is not None),
    # then float() raises ValueError → existing try/except returns None.
    assert result is None


def test_zero_coupon_bond_returns_metrics() -> None:
    """Legitimate zero-coupon bond (coupon=0 with other fields present) → metrics."""
    attrs = {
        "coupon_rate_pct": 0.0,
        "duration_years": 10.0,
        "benchmark_yield_pct": 4.0,
        "outstanding_usd": 50_000_000.0,
        "face_value_usd": 50_000_000.0,
    }
    result = compute_bond_metrics(attrs)
    assert result is not None
    assert result.spread_vs_benchmark_bps == pytest.approx(-400.0)  # negative spread
