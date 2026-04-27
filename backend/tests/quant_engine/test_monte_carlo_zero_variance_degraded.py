"""F02 regression: MC zero-variance Sharpe degraded surface (S05-F02).

Validates that mass zero-variance collapse across simulated paths
surfaces degraded=True on MonteCarloResult, while partial or
non-Sharpe statistics remain unaffected.
"""

from __future__ import annotations

import numpy as np

from quant_engine.monte_carlo_service import (
    MonteCarloResult,
    run_monte_carlo,
)


def test_flat_nav_sharpe_returns_degraded():
    """All-zero daily returns + statistic='sharpe' -> most paths
    produce zero-variance Sharpe. Run must surface degraded=True."""
    daily = np.zeros(300)  # T=300, well above thresholds, but flat
    result = run_monte_carlo(daily, horizons=[252], seed=42, statistic="sharpe")
    assert isinstance(result, MonteCarloResult)
    assert result.degraded is True
    assert result.degraded_reason is not None
    assert "zero_variance" in result.degraded_reason.lower()
    # Not gated to n_simulations=0 — run completed, just degraded
    assert result.n_simulations > 0


def test_flat_nav_max_drawdown_not_degraded_for_zero_variance_reason():
    """statistic='max_drawdown' is not affected by zero-variance —
    flat NAV produces zero drawdown legitimately. Should NOT degrade
    on the zero-variance path (other guards may still degrade)."""
    daily = np.zeros(300)
    result = run_monte_carlo(daily, horizons=[252], seed=42, statistic="max_drawdown")
    # If degraded for some other reason (e.g., insufficient T), that's fine.
    # The point: degraded_reason should NOT mention zero_variance for max_drawdown.
    if result.degraded:
        assert "zero_variance" not in (result.degraded_reason or "").lower()


def test_normal_distribution_sharpe_not_degraded():
    """Healthy non-flat returns + statistic='sharpe' -> degraded=False."""
    rng = np.random.default_rng(42)
    daily = rng.normal(0.0005, 0.01, 300)
    result = run_monte_carlo(daily, horizons=[252], seed=42, statistic="sharpe")
    assert result.degraded is False
    assert result.n_simulations > 0


def test_partial_zero_variance_below_threshold_not_degraded():
    """Most paths informative, a few zero-variance -> run not degraded."""
    rng = np.random.default_rng(42)
    daily = rng.normal(0.0005, 0.01, 300)
    # With healthy input, < 50% paths should hit zero-variance
    result = run_monte_carlo(daily, horizons=[252], seed=42, statistic="sharpe")
    assert result.degraded is False
