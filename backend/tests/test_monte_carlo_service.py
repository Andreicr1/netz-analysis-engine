"""Tests for quant_engine/monte_carlo_service.py — block bootstrap Monte Carlo."""

from __future__ import annotations

import numpy as np
import pytest

from quant_engine.monte_carlo_service import (
    MonteCarloResult,
    _block_bootstrap_paths,
    _compute_max_drawdown,
    run_monte_carlo,
)

# ── Fixtures ──────────────────────────────────────────────────────────


def _make_daily_returns(n_days: int = 504, seed: int = 42) -> np.ndarray:
    """Generate synthetic daily returns (~2 years)."""
    rng = np.random.RandomState(seed)
    return rng.normal(0.0003, 0.01, n_days)


# ── Block Bootstrap ──────────────────────────────────────────────────


class TestBlockBootstrap:
    def test_output_shape(self):
        daily = _make_daily_returns()
        paths = _block_bootstrap_paths(daily, n_simulations=100, horizon=252, block_size=21)
        assert paths.shape == (100, 252)

    def test_values_come_from_original(self):
        """All bootstrapped values must exist in the original series."""
        daily = _make_daily_returns()
        paths = _block_bootstrap_paths(
            daily, n_simulations=10, horizon=63, block_size=21,
            rng=np.random.RandomState(0),
        )
        original_set = set(daily.tolist())
        for i in range(paths.shape[0]):
            for v in paths[i]:
                assert v in original_set

    def test_block_continuity(self):
        """Within a 21-day block, values should be contiguous from the original."""
        daily = _make_daily_returns()
        paths = _block_bootstrap_paths(
            daily, n_simulations=1, horizon=42, block_size=21,
            rng=np.random.RandomState(7),
        )
        path = paths[0]
        # First block of 21 should appear contiguously in daily
        block = path[:21]
        found = False
        for start in range(len(daily) - 20):
            if np.allclose(daily[start:start + 21], block):
                found = True
                break
        assert found


# ── Max Drawdown ─────────────────────────────────────────────────────


class TestComputeMaxDrawdown:
    def test_no_drawdown(self):
        """Monotonically increasing NAV → 0 drawdown."""
        nav = np.array([1.0, 1.01, 1.02, 1.03, 1.04])
        dd = _compute_max_drawdown(nav)
        assert dd == pytest.approx(0.0, abs=1e-10)

    def test_known_drawdown(self):
        """NAV drops 20% from peak."""
        nav = np.array([1.0, 1.1, 1.2, 0.96, 1.0])
        dd = _compute_max_drawdown(nav)
        # Peak=1.2, trough=0.96 → DD = (0.96-1.2)/1.2 = -0.2
        assert dd == pytest.approx(-0.2, abs=0.001)

    def test_always_negative_or_zero(self):
        daily = _make_daily_returns()
        nav = np.cumprod(1 + daily)
        dd = _compute_max_drawdown(nav)
        assert dd <= 0.0


# ── Full Service ─────────────────────────────────────────────────────


class TestRunMonteCarlo:
    def test_returns_result_type(self):
        daily = _make_daily_returns()
        result = run_monte_carlo(daily, n_simulations=100, seed=42)
        assert isinstance(result, MonteCarloResult)

    def test_insufficient_data(self):
        result = run_monte_carlo(np.array([0.01] * 20), n_simulations=100)
        assert result.n_simulations == 0

    def test_n_simulations_matches(self):
        daily = _make_daily_returns()
        result = run_monte_carlo(daily, n_simulations=500, seed=42)
        assert result.n_simulations == 500

    def test_statistic_persisted(self):
        daily = _make_daily_returns()
        result = run_monte_carlo(daily, n_simulations=100, statistic="return", seed=42)
        assert result.statistic == "return"

    def test_percentile_ordering(self):
        """Percentile values should be monotonically non-decreasing."""
        daily = _make_daily_returns()
        result = run_monte_carlo(daily, n_simulations=1000, seed=42)
        pctl_vals = list(result.percentiles.values())
        for i in range(len(pctl_vals) - 1):
            assert pctl_vals[i] <= pctl_vals[i + 1] + 1e-8

    def test_max_drawdown_negative(self):
        """Max drawdown percentiles should be non-positive."""
        daily = _make_daily_returns()
        result = run_monte_carlo(
            daily, n_simulations=500, statistic="max_drawdown", seed=42,
        )
        for v in result.percentiles.values():
            assert v <= 0.0 + 1e-8

    def test_confidence_bars_populated(self):
        """Confidence bars should be generated for each horizon."""
        daily = _make_daily_returns()
        horizons = [252, 504]
        result = run_monte_carlo(
            daily, n_simulations=100, horizons=horizons, seed=42,
        )
        assert len(result.confidence_bars) == len(horizons)
        for bar in result.confidence_bars:
            assert "horizon" in bar
            assert "pct_5" in bar
            assert "pct_95" in bar

    def test_historical_value_computed(self):
        daily = _make_daily_returns()
        result = run_monte_carlo(daily, n_simulations=100, seed=42)
        assert result.historical_value != 0.0

    def test_sharpe_statistic(self):
        daily = _make_daily_returns()
        result = run_monte_carlo(
            daily, n_simulations=100, statistic="sharpe", seed=42,
        )
        assert result.statistic == "sharpe"
        assert result.mean != 0.0

    def test_frozen_dataclass(self):
        daily = _make_daily_returns()
        result = run_monte_carlo(daily, n_simulations=100, seed=42)
        with pytest.raises(AttributeError):
            result.n_simulations = 0  # type: ignore[misc]

    def test_reproducible_with_seed(self):
        """Same seed should produce identical results."""
        daily = _make_daily_returns()
        r1 = run_monte_carlo(daily, n_simulations=100, seed=42)
        r2 = run_monte_carlo(daily, n_simulations=100, seed=42)
        assert r1.mean == r2.mean
        assert r1.percentiles == r2.percentiles
