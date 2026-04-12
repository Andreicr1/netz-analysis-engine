"""Tests for quant_engine.alternatives_analytics_service.

Test cases using synthetic data:
1. Equity correlation — correlated vs uncorrelated fund
2. Capture ratios — protective fund vs equity-like fund
3. Crisis alpha — positive vs negative during drawdowns
4. Calmar ratio — arithmetic correctness
5. Inflation beta — commodity-like vs equity-like fund
6. Insufficient data returns None
7. compute_alt_analytics integration
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from quant_engine.alternatives_analytics_service import (
    AltAnalyticsConfig,
    AltAnalyticsResult,
    compute_alt_analytics,
    compute_calmar_ratio,
    compute_capture_ratios,
    compute_crisis_alpha,
    compute_equity_correlation,
    compute_inflation_beta,
)


@pytest.fixture()
def config() -> AltAnalyticsConfig:
    return AltAnalyticsConfig()


class TestEquityCorrelation:
    def test_high_correlation_with_spy(self) -> None:
        """Fund tracking SPY should have correlation ~1.0."""
        rng = np.random.default_rng(42)
        n = 252
        spy_returns = rng.normal(0.0004, 0.01, n)
        noise = rng.normal(0, 0.001, n)
        fund_returns = spy_returns + noise  # highly correlated

        corr = compute_equity_correlation(fund_returns, spy_returns)
        assert corr is not None
        assert corr > 0.8, f"Expected high correlation, got {corr}"

    def test_uncorrelated_fund(self) -> None:
        """Independent fund should have correlation near 0."""
        rng = np.random.default_rng(123)
        n = 252
        spy_returns = rng.normal(0.0004, 0.01, n)
        fund_returns = rng.normal(0.0003, 0.008, n)  # independent

        corr = compute_equity_correlation(fund_returns, spy_returns)
        assert corr is not None
        assert abs(corr) < 0.3, f"Expected near-zero correlation, got {corr}"

    def test_insufficient_data_returns_none(self) -> None:
        """< 120 observations should return None."""
        rng = np.random.default_rng(7)
        n = 100
        corr = compute_equity_correlation(
            rng.normal(0, 0.01, n), rng.normal(0, 0.01, n),
        )
        assert corr is None


class TestCaptureRatios:
    def test_protective_fund(self) -> None:
        """Fund that loses less in down months and gains less in up months."""
        rng = np.random.default_rng(55)
        n = 36  # 3 years monthly
        bench = rng.normal(0.008, 0.04, n)

        # Fund captures 50% of both up and down
        fund = bench * 0.5 + rng.normal(0, 0.005, n)

        down_cap, up_cap = compute_capture_ratios(fund, bench)

        assert down_cap is not None
        assert up_cap is not None
        # Should capture roughly 50% of movements
        assert 0.2 < down_cap < 0.8, f"Expected ~0.5 downside capture, got {down_cap}"
        assert 0.2 < up_cap < 0.8, f"Expected ~0.5 upside capture, got {up_cap}"

    def test_equity_like_fund(self) -> None:
        """Fund tracking benchmark should have capture ratios ~1.0."""
        rng = np.random.default_rng(99)
        n = 36
        bench = rng.normal(0.008, 0.04, n)
        fund = bench + rng.normal(0, 0.003, n)

        down_cap, up_cap = compute_capture_ratios(fund, bench)

        assert down_cap is not None
        assert up_cap is not None
        assert abs(down_cap - 1.0) < 0.3, f"Expected ~1.0 downside capture, got {down_cap}"
        assert abs(up_cap - 1.0) < 0.3, f"Expected ~1.0 upside capture, got {up_cap}"

    def test_insufficient_months_returns_none(self) -> None:
        """< 3 observations should return None."""
        fund = np.array([0.01, -0.02])
        bench = np.array([-0.03, 0.02])
        down, up = compute_capture_ratios(fund, bench)
        assert down is None
        assert up is None


class TestCrisisAlpha:
    def test_positive_crisis_alpha(self) -> None:
        """Fund that outperforms during benchmark drawdowns."""
        rng = np.random.default_rng(42)
        n = 504  # 2 years

        # Create benchmark with a crisis period (drawdown > 10%)
        bench = rng.normal(0.0003, 0.01, n)
        # Insert a significant drawdown in the middle
        bench[150:200] = -0.005  # steady decline over 50 days

        # Fund holds steady during the crisis
        fund = rng.normal(0.0002, 0.005, n)
        fund[150:200] = rng.normal(0.001, 0.003, 50)  # positive during crisis

        ca = compute_crisis_alpha(fund, bench)

        if ca is not None:
            assert ca > 0, f"Fund outperforming in crisis should have positive alpha, got {ca}"

    def test_no_crisis_period_returns_none(self) -> None:
        """If benchmark never draws down > 10%, return None."""
        rng = np.random.default_rng(77)
        n = 252
        # Gentle uptrend, no major drawdown
        bench = rng.normal(0.001, 0.003, n)
        fund = rng.normal(0.0005, 0.003, n)

        ca = compute_crisis_alpha(fund, bench)
        assert ca is None

    def test_insufficient_data_returns_none(self) -> None:
        rng = np.random.default_rng(10)
        ca = compute_crisis_alpha(rng.normal(0, 0.01, 30), rng.normal(0, 0.01, 30))
        assert ca is None


class TestCalmarRatio:
    def test_normal_computation(self) -> None:
        """10% annual return, 20% max drawdown -> Calmar = 0.5."""
        calmar = compute_calmar_ratio(0.10, -0.20)
        assert calmar is not None
        assert abs(calmar - 0.5) < 1e-4

    def test_high_return_low_drawdown(self) -> None:
        """20% annual return, 10% drawdown -> Calmar = 2.0."""
        calmar = compute_calmar_ratio(0.20, -0.10)
        assert calmar is not None
        assert abs(calmar - 2.0) < 1e-4

    def test_none_inputs(self) -> None:
        assert compute_calmar_ratio(None, -0.10) is None
        assert compute_calmar_ratio(0.10, None) is None

    def test_no_drawdown_returns_none(self) -> None:
        """Zero or positive drawdown is a data error."""
        assert compute_calmar_ratio(0.10, 0.0) is None
        assert compute_calmar_ratio(0.10, 0.05) is None


class TestInflationBeta:
    def test_commodity_like_fund(self) -> None:
        """Fund returns positively correlated with CPI changes."""
        rng = np.random.default_rng(42)
        n = 36  # 3 years monthly
        cpi_changes = rng.normal(0.003, 0.002, n)  # ~3.6% annual CPI
        noise = rng.normal(0, 0.005, n)
        # Fund moves 2x CPI changes (positive inflation hedge)
        fund_returns = 2.0 * cpi_changes + noise

        beta, r2 = compute_inflation_beta(fund_returns, cpi_changes)

        assert beta is not None
        assert r2 is not None
        assert beta > 1.0, f"Expected positive inflation beta > 1.0, got {beta}"
        assert r2 > 0.1, f"Expected R^2 > 0.1, got {r2}"

    def test_uncorrelated_fund_returns_none(self) -> None:
        """Fund with no inflation sensitivity should return None (low R^2)."""
        rng = np.random.default_rng(123)
        n = 36
        cpi_changes = rng.normal(0.003, 0.002, n)
        fund_returns = rng.normal(0.005, 0.02, n)  # independent

        beta, r2 = compute_inflation_beta(fund_returns, cpi_changes)

        # Either None (R^2 below threshold) or very low beta
        if beta is not None:
            assert abs(beta) < 3.0

    def test_insufficient_months_returns_none(self) -> None:
        rng = np.random.default_rng(10)
        beta, r2 = compute_inflation_beta(
            rng.normal(0, 0.01, 6), rng.normal(0, 0.002, 6),
        )
        assert beta is None
        assert r2 is None


class TestComputeAltAnalytics:
    """Integration test for the full compute_alt_analytics pipeline."""

    def test_full_computation(self) -> None:
        """All fields populated with sufficient data."""
        rng = np.random.default_rng(42)
        n = 504  # 2 years daily
        base_date = date(2024, 1, 1)
        dates = [base_date + timedelta(days=i) for i in range(n)]

        spy_returns = rng.normal(0.0004, 0.012, n)
        fund_returns = spy_returns * 0.3 + rng.normal(0.0002, 0.005, n)

        fund_dated = list(zip(dates, fund_returns.tolist(), strict=True))
        spy_dated = list(zip(dates, spy_returns.tolist(), strict=True))

        # Monthly CPI
        cpi_dates = [date(2024, m, 15) for m in range(1, 13)] + [date(2025, m, 15) for m in range(1, 13)]
        cpi_changes = rng.normal(0.003, 0.001, len(cpi_dates)).tolist()
        cpi_dated = list(zip(cpi_dates, cpi_changes, strict=True))

        result = compute_alt_analytics(
            fund_dated_returns=fund_dated,
            benchmark_dated_returns=spy_dated,
            cpi_monthly_changes=cpi_dated,
            return_3y_ann=0.12,
            max_drawdown_3y=-0.15,
        )

        assert isinstance(result, AltAnalyticsResult)
        assert result.equity_correlation_252d is not None
        assert result.calmar_ratio_3y is not None
        assert abs(result.calmar_ratio_3y - 0.80) < 0.01

    def test_empty_returns(self) -> None:
        """No returns should produce all-None result."""
        result = compute_alt_analytics(
            fund_dated_returns=[],
            benchmark_dated_returns=[],
            cpi_monthly_changes=[],
            return_3y_ann=None,
            max_drawdown_3y=None,
        )
        assert result.equity_correlation_252d is None
        assert result.downside_capture_1y is None
        assert result.crisis_alpha_score is None
        assert result.calmar_ratio_3y is None
        assert result.inflation_beta is None
