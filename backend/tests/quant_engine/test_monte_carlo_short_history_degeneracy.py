"""Regression tests for S05-F04 (Tier 1) — MC short-history + long-horizon
block bootstrap degeneracy.

T close to block_size + horizon >> T causes block bootstrap to cycle the same
few monthly windows of input data, producing meaningless percentile bands.
"""

from __future__ import annotations

import numpy as np

from quant_engine.monte_carlo_service import (
    MonteCarloResult,
    run_monte_carlo,
)

# ── Regression tests for S05-F04 (Tier 1) ──────────────────────────────────


def test_short_history_long_horizon_returns_degraded():
    """T=42, horizon=2520 (10Y) → block bootstrap would cycle ~22 windows
    of 42-day history. Must return degraded=True with explicit reason."""
    rng = np.random.default_rng(42)
    daily = rng.normal(0.0003, 0.01, 42)
    result = run_monte_carlo(daily, horizons=[2520], seed=42)
    assert result.degraded is True
    assert result.n_simulations == 0
    assert result.degraded_reason is not None
    assert "horizon" in result.degraded_reason.lower()


def test_short_history_short_horizon_runs_normally():
    """T=42 + 1Y horizon (252 days) should NOT degrade — 42/252 = 16.7%
    sample richness, above 10% floor."""
    rng = np.random.default_rng(42)
    daily = rng.normal(0.0003, 0.01, 42)
    result = run_monte_carlo(daily, horizons=[252], seed=42, n_simulations=100)
    assert result.degraded is False
    assert result.degraded_reason is None
    assert result.n_simulations > 0


def test_long_history_long_horizon_runs_normally():
    """T=300, horizon=2520. T/horizon = 11.9% > 10% floor. Should run."""
    rng = np.random.default_rng(42)
    daily = rng.normal(0.0003, 0.01, 300)
    result = run_monte_carlo(daily, horizons=[2520], seed=42, n_simulations=100)
    assert result.degraded is False
    assert result.n_simulations > 0


def test_just_above_floor_runs_normally():
    """Boundary: T = min(max_horizon * 0.1, 252) exactly. Must not degrade."""
    # max_horizon=2520 → min_t_required = min(252, 252) = 252
    rng = np.random.default_rng(42)
    daily = rng.normal(0.0003, 0.01, 252)
    result = run_monte_carlo(daily, horizons=[2520], seed=42, n_simulations=100)
    assert result.degraded is False


def test_just_below_floor_degrades():
    """Boundary: T = min_t_required - 1. Must degrade."""
    rng = np.random.default_rng(42)
    daily = rng.normal(0.0003, 0.01, 251)
    result = run_monte_carlo(daily, horizons=[2520], seed=42)
    assert result.degraded is True


def test_t_below_42_still_degrades():
    """Existing T<42 guard preserved (S05-F03 angle covered by Q47 too)."""
    rng = np.random.default_rng(42)
    daily = rng.normal(0.0003, 0.01, 30)
    result = run_monte_carlo(daily, horizons=[252], seed=42)
    assert result.degraded is True
    assert result.n_simulations == 0


def test_degraded_reason_includes_diagnostic_numbers():
    """degraded_reason must include T and horizon for operator forensics."""
    rng = np.random.default_rng(42)
    daily = rng.normal(0.0003, 0.01, 42)
    result = run_monte_carlo(daily, horizons=[2520], seed=42)
    assert result.degraded is True
    assert "42" in result.degraded_reason or "T=42" in result.degraded_reason
    assert "2520" in result.degraded_reason


# ── Existing-behavior preservation (control tests) ─────────────────────


def test_dataclass_default_degraded_false():
    """Existing callers using positional/default-only init: degraded=False."""
    r = MonteCarloResult(n_simulations=10000, statistic="max_drawdown")
    assert r.degraded is False
    assert r.degraded_reason is None


def test_seed_propagation_unchanged():
    """Existing behavior: same seed produces same output (control)."""
    rng = np.random.default_rng(42)
    daily = rng.normal(0.0003, 0.01, 300)
    r1 = run_monte_carlo(daily, horizons=[252], seed=42, n_simulations=100)
    r2 = run_monte_carlo(daily, horizons=[252], seed=42, n_simulations=100)
    if r1.n_simulations > 0 and r2.n_simulations > 0:
        assert r1.mean == r2.mean
        assert r1.std == r2.std
