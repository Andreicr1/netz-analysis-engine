"""Tests for the Entity Analytics Vitrine.

Verifies the 5 metric groups: Risk Statistics, Drawdown, Capture,
Rolling Returns, and Return Distribution. Uses synthetic NAV data
to validate computation correctness without DB dependency.

Drawdown and rolling math lives in quant_engine (reusable).
Capture, monthly aggregation, and distribution remain in the route (endpoint-specific).
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from app.domains.wealth.routes.entity_analytics import (
    _compute_capture_ratios,
    _compute_distribution,
    _monthly_returns_from_daily,
)
from quant_engine.drawdown_service import (
    compute_drawdown_series,
    extract_drawdown_periods,
)
from quant_engine.rolling_service import compute_rolling_returns

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _synthetic_nav_series(n: int = 252, start_nav: float = 1000.0, seed: int = 42):
    """Generate synthetic daily NAV with realistic return characteristics."""
    rng = np.random.default_rng(seed)
    daily_returns = rng.normal(0.0003, 0.01, size=n)
    navs = [start_nav]
    for r in daily_returns:
        navs.append(navs[-1] * (1 + r))
    dates = [date(2025, 1, 2) + timedelta(days=i) for i in range(n + 1)]
    return dates, np.array(navs), daily_returns


# ---------------------------------------------------------------------------
# Drawdown
# ---------------------------------------------------------------------------


class TestDrawdownSeries:
    def test_flat_nav_zero_drawdown(self):
        navs = np.array([100.0, 100.0, 100.0, 100.0])
        dd = compute_drawdown_series(navs)
        assert all(v == 0.0 for v in dd)

    def test_monotonic_up_zero_drawdown(self):
        navs = np.array([100.0, 101.0, 102.0, 103.0])
        dd = compute_drawdown_series(navs)
        assert all(v == 0.0 for v in dd)

    def test_drawdown_depth(self):
        navs = np.array([100.0, 110.0, 99.0, 105.0])
        dd = compute_drawdown_series(navs)
        # After peak of 110, drop to 99 = -10%
        assert dd[2] == pytest.approx(-0.1, abs=0.001)

    def test_drawdown_recovery(self):
        navs = np.array([100.0, 110.0, 99.0, 115.0])
        dd = compute_drawdown_series(navs)
        # After 115 > 110, drawdown is 0
        assert dd[3] == pytest.approx(0.0)


class TestDrawdownPeriods:
    def test_extracts_periods(self):
        navs = np.array([100.0, 110.0, 99.0, 108.0, 112.0])
        dd = compute_drawdown_series(navs)
        dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(5)]
        periods = extract_drawdown_periods(dates, dd)
        assert len(periods) >= 1
        assert periods[0].depth < 0

    def test_open_drawdown(self):
        navs = np.array([100.0, 110.0, 95.0, 90.0])
        dd = compute_drawdown_series(navs)
        dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(4)]
        periods = extract_drawdown_periods(dates, dd)
        assert len(periods) == 1
        assert periods[0].end_date is None
        assert periods[0].recovery_days is None


# ---------------------------------------------------------------------------
# Capture Ratios
# ---------------------------------------------------------------------------


class TestCaptureRatios:
    def test_perfect_tracking(self):
        """Entity == benchmark → 100% capture."""
        monthly = [0.02, -0.01, 0.03, -0.02, 0.01]
        result = _compute_capture_ratios(monthly, monthly)
        assert result.up_capture == pytest.approx(100.0)
        assert result.down_capture == pytest.approx(100.0)

    def test_amplified_upside(self):
        """Entity doubles benchmark gains."""
        bm = [0.02, -0.01, 0.03]
        entity = [0.04, -0.01, 0.06]
        result = _compute_capture_ratios(entity, bm)
        assert result.up_capture is not None
        assert result.up_capture > 100.0

    def test_defensive_downside(self):
        """Entity loses less than benchmark in down months."""
        bm = [0.02, -0.03, -0.02, 0.01]
        entity = [0.02, -0.01, -0.005, 0.01]
        result = _compute_capture_ratios(entity, bm)
        assert result.down_capture is not None
        assert result.down_capture < 100.0

    def test_empty_returns(self):
        result = _compute_capture_ratios([], [])
        assert result.up_capture is None
        assert result.down_capture is None


# ---------------------------------------------------------------------------
# Monthly aggregation
# ---------------------------------------------------------------------------


class TestMonthlyReturns:
    def test_single_month(self):
        dates = [date(2025, 3, d) for d in range(3, 8)]
        returns = [0.01, -0.005, 0.02, 0.003, -0.01]
        labels, monthly = _monthly_returns_from_daily(dates, returns)
        assert len(labels) == 1
        assert labels[0] == "2025-03"

    def test_two_months(self):
        dates = [
            date(2025, 1, 30), date(2025, 1, 31),
            date(2025, 2, 1), date(2025, 2, 2),
        ]
        returns = [0.01, 0.02, -0.01, 0.005]
        labels, monthly = _monthly_returns_from_daily(dates, returns)
        assert len(labels) == 2
        assert labels[0] == "2025-01"
        assert labels[1] == "2025-02"


# ---------------------------------------------------------------------------
# Rolling Returns
# ---------------------------------------------------------------------------


class TestRollingReturns:
    def test_insufficient_data(self):
        """Shorter than smallest window → empty result."""
        dates = [f"2025-01-{d:02d}" for d in range(1, 11)]
        returns = np.array([0.001] * 10)
        result = compute_rolling_returns(dates, returns)
        assert len(result) == 0

    def test_one_year_window(self):
        """252 days of data → 1 point for 1Y rolling."""
        n = 252
        dates = [(date(2025, 1, 2) + timedelta(days=i)).isoformat() for i in range(n)]
        returns = np.full(n, 0.0004)  # ~10% annualized
        result = compute_rolling_returns(dates, returns)
        # Should have 1M (21d), 3M (63d), 6M (126d), 1Y (252d)
        labels = [s.window_label for s in result]
        assert "1M" in labels
        assert "1Y" in labels
        # 1Y rolling should have exactly 1 point (252 - 252 + 1 = 1)
        one_y = next(s for s in result if s.window_label == "1Y")
        assert len(one_y.values) == 1


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------


class TestDistribution:
    def test_normal_returns(self):
        rng = np.random.default_rng(42)
        returns = rng.normal(0.0, 0.01, 500)
        dist = _compute_distribution(returns)
        assert len(dist.bin_edges) > 2
        assert len(dist.bin_counts) == len(dist.bin_edges) - 1
        assert dist.mean is not None
        assert abs(dist.mean) < 0.005  # close to 0
        assert dist.skewness is not None
        assert dist.cvar_95 is not None
        assert dist.var_95 is not None

    def test_insufficient_data(self):
        returns = np.array([0.01, -0.01])
        dist = _compute_distribution(returns)
        assert len(dist.bin_edges) == 0

    def test_skewed_returns(self):
        """Left-skewed distribution should show negative skewness."""
        rng = np.random.default_rng(42)
        returns = -np.abs(rng.normal(0, 0.01, 500)) + 0.001
        dist = _compute_distribution(returns)
        assert dist.skewness is not None
        # Heavy left tail
        assert dist.skewness < 0


# ---------------------------------------------------------------------------
# Schema contract
# ---------------------------------------------------------------------------


class TestSchemaContract:
    def test_response_schema_fields(self):
        from app.domains.wealth.schemas.entity_analytics import EntityAnalyticsResponse

        fields = set(EntityAnalyticsResponse.model_fields.keys())
        assert "risk_statistics" in fields
        assert "drawdown" in fields
        assert "capture" in fields
        assert "rolling_returns" in fields
        assert "distribution" in fields
        assert "entity_type" in fields
        assert "entity_id" in fields

    def test_capture_benchmark_source_enum(self):
        from app.domains.wealth.schemas.entity_analytics import CaptureRatios

        c = CaptureRatios(benchmark_source="param", benchmark_label="TEST")
        assert c.benchmark_source == "param"
        c2 = CaptureRatios(benchmark_source="block", benchmark_label="AGG")
        assert c2.benchmark_source == "block"
        c3 = CaptureRatios()
        assert c3.benchmark_source == "spy_fallback"
