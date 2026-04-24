"""Unit tests for equity characteristics derivation functions."""

from __future__ import annotations

import math
from datetime import date

import pandas as pd
import pytest

from app.domains.wealth.services.characteristics_derivation import (
    derive_book_to_market,
    derive_investment_growth,
    derive_momentum_12_1,
    derive_profitability_gross,
    derive_quality_roa,
    derive_size,
)


class TestDeriveSize:
    def test_positive_market_cap(self):
        assert derive_size(1e9) == pytest.approx(math.log(1e9))

    def test_none_returns_none(self):
        assert derive_size(None) is None

    def test_negative_returns_none(self):
        assert derive_size(-1) is None

    def test_zero_returns_none(self):
        assert derive_size(0) is None

    def test_small_positive(self):
        assert derive_size(1.0) == pytest.approx(0.0)


class TestDeriveBookToMarket:
    def test_normal(self):
        assert derive_book_to_market(500, 1000) == pytest.approx(0.5)

    def test_none_equity(self):
        assert derive_book_to_market(None, 1000) is None

    def test_none_market_cap(self):
        assert derive_book_to_market(500, None) is None

    def test_zero_market_cap(self):
        assert derive_book_to_market(500, 0) is None

    def test_negative_market_cap(self):
        assert derive_book_to_market(500, -100) is None


class TestDeriveMomentum12_1:
    def _make_series(self, n_months: int, start_val: float = 100.0, growth: float = 0.01):
        dates = pd.date_range("2024-01-31", periods=n_months, freq="ME")
        values = [start_val * (1 + growth) ** i for i in range(n_months)]
        return pd.Series(values, index=dates)

    def test_13_month_series(self):
        series = self._make_series(14)
        as_of = series.index[-1].date()
        result = derive_momentum_12_1(series, as_of)
        assert result is not None
        expected = series.iloc[-2] / series.iloc[-13] - 1
        assert result == pytest.approx(expected, rel=1e-6)

    def test_short_series_returns_none(self):
        series = self._make_series(8)
        as_of = series.index[-1].date()
        assert derive_momentum_12_1(series, as_of) is None

    def test_exact_11_months(self):
        series = self._make_series(12)
        as_of = series.index[-1].date()
        result = derive_momentum_12_1(series, as_of)
        assert result is not None

    def test_empty_series(self):
        assert derive_momentum_12_1(pd.Series(dtype=float), date(2024, 12, 31)) is None

    def test_zero_start_returns_none(self):
        """When the 12-1 momentum window's start value is 0, the function
        must return None (division by zero / undefined momentum).

        The window is iloc[-13:-1] of the series, so we place the zero at
        position 1 (index -13 from the tail) — the first element (index 0)
        is dropped by the slice.
        """
        dates = pd.date_range("2023-01-31", periods=14, freq="ME")
        values = [100, 0] + [100] * 12  # zero at position 1 = window start
        series = pd.Series(values, index=dates)
        as_of = dates[-1].date()
        assert derive_momentum_12_1(series, as_of) is None


class TestDeriveQualityRoa:
    def test_normal(self):
        assert derive_quality_roa(50, 1000) == pytest.approx(0.05)

    def test_none_income(self):
        assert derive_quality_roa(None, 1000) is None

    def test_none_assets(self):
        assert derive_quality_roa(50, None) is None

    def test_zero_assets(self):
        assert derive_quality_roa(50, 0) is None

    def test_negative_income(self):
        assert derive_quality_roa(-50, 1000) == pytest.approx(-0.05)


class TestDeriveInvestmentGrowth:
    def test_ten_percent_growth(self):
        assert derive_investment_growth(110, 100) == pytest.approx(0.10)

    def test_decline(self):
        assert derive_investment_growth(90, 100) == pytest.approx(-0.10)

    def test_none_now(self):
        assert derive_investment_growth(None, 100) is None

    def test_none_yoy(self):
        assert derive_investment_growth(110, None) is None

    def test_zero_yoy(self):
        assert derive_investment_growth(110, 0) is None


class TestDeriveProfitabilityGross:
    def test_uses_gross_profit(self):
        assert derive_profitability_gross(300, 1000, 700) == pytest.approx(0.30)

    def test_fallback_to_cost_of_revenue(self):
        assert derive_profitability_gross(None, 1000, 700) == pytest.approx(0.30)

    def test_none_revenue(self):
        assert derive_profitability_gross(300, None, 700) is None

    def test_zero_revenue(self):
        assert derive_profitability_gross(300, 0, 700) is None

    def test_all_none(self):
        assert derive_profitability_gross(None, 1000, None) is None

    def test_gross_profit_preferred_over_fallback(self):
        result = derive_profitability_gross(400, 1000, 500)
        assert result == pytest.approx(0.40)
