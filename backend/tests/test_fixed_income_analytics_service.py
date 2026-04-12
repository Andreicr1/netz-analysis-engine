"""Tests for quant_engine.fixed_income_analytics_service.

6 test cases using synthetic data as specified in the FI Quant Engine plan:
1. Pure FI fund (duration ~7)
2. Pure equity fund (no rate sensitivity)
3. High yield fund (credit_beta ~2.5)
4. Insufficient data (<120 obs)
5. Yield proxy with 4% carry
6. Duration-adjusted drawdown arithmetic
"""

from __future__ import annotations

import numpy as np
import pytest

from quant_engine.fixed_income_analytics_service import (
    FIRegressionConfig,
    compute_credit_beta,
    compute_duration_adjusted_drawdown,
    compute_empirical_duration,
    compute_yield_proxy,
)


@pytest.fixture()
def config() -> FIRegressionConfig:
    return FIRegressionConfig()


class TestEmpiricalDuration:
    def test_pure_fi_fund_recovers_duration(self, config: FIRegressionConfig) -> None:
        """Fund with R = -7 * delta_Y + noise should recover duration ~7."""
        rng = np.random.default_rng(42)
        n = 504
        yield_changes = rng.normal(0, 0.001, n)  # ~10bps daily std
        noise = rng.normal(0, 0.0005, n)
        fund_returns = -7.0 * yield_changes + noise

        duration, r_sq = compute_empirical_duration(fund_returns, yield_changes, config)

        assert duration is not None
        assert r_sq is not None
        assert abs(duration - 7.0) < 0.5, f"Expected ~7.0, got {duration}"
        assert r_sq > 0.5, f"Expected R² > 0.5, got {r_sq}"

    def test_equity_fund_returns_none(self, config: FIRegressionConfig) -> None:
        """Equity fund with no rate sensitivity should have R² < 0.05 -> None."""
        rng = np.random.default_rng(123)
        n = 504
        yield_changes = rng.normal(0, 0.001, n)
        fund_returns = rng.normal(0.0003, 0.01, n)  # independent of yields

        duration, r_sq = compute_empirical_duration(fund_returns, yield_changes, config)

        assert duration is None
        assert r_sq is None


class TestCreditBeta:
    def test_hy_fund_recovers_credit_beta(self, config: FIRegressionConfig) -> None:
        """HY fund with R = -2.5 * delta_spread + noise recovers beta ~2.5."""
        rng = np.random.default_rng(99)
        n = 504
        spread_changes = rng.normal(0, 0.002, n)
        noise = rng.normal(0, 0.001, n)
        fund_returns = -2.5 * spread_changes + noise

        beta, r_sq = compute_credit_beta(fund_returns, spread_changes, config)

        assert beta is not None
        assert r_sq is not None
        assert abs(beta - 2.5) < 0.5, f"Expected ~2.5, got {beta}"
        assert r_sq > 0.5, f"Expected R² > 0.5, got {r_sq}"


class TestInsufficientData:
    def test_below_min_observations_returns_none(self) -> None:
        """< 120 observations should return None for all fields."""
        rng = np.random.default_rng(7)
        n = 100  # below min_observations=120
        fund_returns = rng.normal(0, 0.01, n)
        yield_changes = rng.normal(0, 0.001, n)
        spread_changes = rng.normal(0, 0.002, n)

        d, d_r2 = compute_empirical_duration(fund_returns, yield_changes)
        cb, cb_r2 = compute_credit_beta(fund_returns, spread_changes)

        assert d is None and d_r2 is None
        assert cb is None and cb_r2 is None


class TestYieldProxy:
    def test_carry_4pct(self) -> None:
        """Monthly returns averaging ~0.33% positive should yield ~4% annual."""
        rng = np.random.default_rng(55)
        # 12 months, most positive around 0.33% (4%/12)
        monthly = np.array([0.003, 0.004, 0.0035, -0.002, 0.003, 0.0038,
                            0.0032, 0.004, -0.001, 0.003, 0.0035, 0.0033])

        yp = compute_yield_proxy(monthly)

        assert yp is not None
        assert abs(yp - 0.04) < 0.01, f"Expected ~0.04, got {yp}"

    def test_insufficient_months_returns_none(self) -> None:
        monthly = np.array([0.003, 0.004, 0.002])
        assert compute_yield_proxy(monthly) is None


class TestDurationAdjustedDrawdown:
    def test_high_duration_good_management(self) -> None:
        """Duration=8, drawdown=-8% -> DAD = -1.0%."""
        dad = compute_duration_adjusted_drawdown(-0.08, 8.0)
        assert dad is not None
        assert abs(dad - (-0.01)) < 1e-9

    def test_low_duration_poor_management(self) -> None:
        """Duration=2, drawdown=-5% -> DAD = -2.5%."""
        dad = compute_duration_adjusted_drawdown(-0.05, 2.0)
        assert dad is not None
        assert abs(dad - (-0.025)) < 1e-9

    def test_none_duration_returns_none(self) -> None:
        assert compute_duration_adjusted_drawdown(-0.05, None) is None

    def test_duration_floor_at_one(self) -> None:
        """Duration < 1 should be floored at 1 to avoid division issues."""
        dad = compute_duration_adjusted_drawdown(-0.03, 0.5)
        assert dad is not None
        assert abs(dad - (-0.03)) < 1e-9
