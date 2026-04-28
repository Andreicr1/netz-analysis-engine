"""Regression tests for S08-F01 — composite_score minimum coverage gate."""

from __future__ import annotations

from vertical_engines.wealth.screener.quant_metrics import MIN_COVERAGE_RATIO, composite_score


def test_thin_data_below_50pct_coverage_returns_none() -> None:
    """Single metric out of 4 (25% coverage) -> None, not optimistic PASS."""
    metrics = {"sharpe_ratio": 2.0}  # only 1 of 4 metrics
    peers = {"sharpe_ratio": [0.5, 1.0, 1.5, 2.0, 2.5]}  # has peers
    weights = {
        "sharpe_ratio": 0.30, "max_drawdown": 0.25,
        "pct_positive_months": 0.25, "annual_volatility_pct": 0.20,
    }
    result = composite_score(metrics, peers, weights)
    assert result is None  # 30% coverage < 50% threshold


def test_two_metrics_above_50pct_coverage_returns_score() -> None:
    """2 of 4 metrics (55% coverage at boundary) -> score returned."""
    metrics = {"sharpe_ratio": 2.0, "max_drawdown": -0.05}
    peers = {
        "sharpe_ratio": [0.5, 1.0, 1.5, 2.0, 2.5],
        "max_drawdown": [-0.30, -0.20, -0.15, -0.10, -0.05],
    }
    weights = {
        "sharpe_ratio": 0.30, "max_drawdown": 0.25,
        "pct_positive_months": 0.25, "annual_volatility_pct": 0.20,
    }
    result = composite_score(metrics, peers, weights)
    assert result is not None  # 55% coverage >= 50% threshold


def test_all_metrics_returns_full_score() -> None:
    """All 4 metrics observed -> full score (100% coverage)."""
    metrics = {
        "sharpe_ratio": 2.0, "max_drawdown": -0.05,
        "pct_positive_months": 0.75, "annual_volatility_pct": 12.0,
    }
    peers = {
        "sharpe_ratio": [0.5, 1.0, 1.5, 2.0, 2.5],
        "max_drawdown": [-0.30, -0.20, -0.15, -0.10, -0.05],
        "pct_positive_months": [0.40, 0.50, 0.60, 0.70, 0.75],
        "annual_volatility_pct": [25.0, 18.0, 15.0, 12.0, 10.0],
    }
    weights = {
        "sharpe_ratio": 0.30, "max_drawdown": 0.25,
        "pct_positive_months": 0.25, "annual_volatility_pct": 0.20,
    }
    result = composite_score(metrics, peers, weights)
    assert result is not None
    assert 0.0 <= result <= 1.0


def test_zero_total_weight_returns_none() -> None:
    """No metric has both value AND peers -> None (existing behavior preserved)."""
    metrics = {"sharpe_ratio": 2.0}
    peers = {}  # no peer data
    weights = {"sharpe_ratio": 1.0}
    result = composite_score(metrics, peers, weights)
    assert result is None


def test_min_coverage_constant_is_documented() -> None:
    """MIN_COVERAGE_RATIO is exported as module constant for audit."""
    assert MIN_COVERAGE_RATIO == 0.50


def test_exactly_50pct_coverage_returns_score() -> None:
    """Exactly 50% weight coverage -> at boundary, returns score (not strict less-than)."""
    metrics = {"sharpe_ratio": 1.5}
    peers = {"sharpe_ratio": [0.5, 1.0, 1.5, 2.0, 2.5]}
    weights = {"sharpe_ratio": 0.50, "max_drawdown": 0.50}
    result = composite_score(metrics, peers, weights)
    # 50% coverage is NOT < 50%, so score should be returned
    assert result is not None
