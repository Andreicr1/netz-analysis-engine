"""Tests for quant_engine/drawdown_service.py."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from quant_engine.drawdown_service import (
    DrawdownPeriodResult,
    DrawdownResult,
    analyze_drawdowns,
    compute_drawdown_series,
    extract_drawdown_periods,
)


class TestComputeDrawdownSeries:
    def test_empty_array(self):
        dd = compute_drawdown_series(np.array([]))
        assert len(dd) == 0

    def test_single_value(self):
        dd = compute_drawdown_series(np.array([100.0]))
        assert dd[0] == 0.0

    def test_monotonic_up(self):
        dd = compute_drawdown_series(np.array([100.0, 101.0, 102.0]))
        assert all(v == 0.0 for v in dd)

    def test_correct_depth(self):
        dd = compute_drawdown_series(np.array([100.0, 120.0, 90.0]))
        # 90 from peak 120 = -25%
        assert dd[2] == pytest.approx(-0.25)

    def test_recovery_to_zero(self):
        dd = compute_drawdown_series(np.array([100.0, 120.0, 100.0, 130.0]))
        assert dd[3] == pytest.approx(0.0)


class TestExtractDrawdownPeriods:
    def _dates(self, n: int) -> list[date]:
        return [date(2025, 1, 1) + timedelta(days=i) for i in range(n)]

    def test_no_drawdown(self):
        navs = np.array([100.0, 101.0, 102.0])
        dd = compute_drawdown_series(navs)
        periods = extract_drawdown_periods(self._dates(3), dd)
        assert periods == []

    def test_single_period(self):
        navs = np.array([100.0, 110.0, 95.0, 115.0])
        dd = compute_drawdown_series(navs)
        periods = extract_drawdown_periods(self._dates(4), dd)
        assert len(periods) == 1
        p = periods[0]
        assert isinstance(p, DrawdownPeriodResult)
        assert p.depth < 0
        assert p.end_date is not None
        assert p.recovery_days is not None

    def test_open_period(self):
        navs = np.array([100.0, 110.0, 90.0, 85.0])
        dd = compute_drawdown_series(navs)
        periods = extract_drawdown_periods(self._dates(4), dd)
        assert len(periods) == 1
        assert periods[0].end_date is None

    def test_top_n_limit(self):
        # Create multiple drawdown periods
        navs = np.array([100, 110, 95, 115, 130, 100, 135, 140, 120, 145])
        dd = compute_drawdown_series(np.array(navs, dtype=float))
        dates = self._dates(len(navs))
        periods = extract_drawdown_periods(dates, dd, top_n=2)
        assert len(periods) <= 2

    def test_period_start_anchored_to_preceding_peak(self):
        """For NAV [100, 100, 90, 100], duration_days from peak (i=1) to recovery (i=3) = 2 days."""
        base = date(2024, 1, 1)
        dates = [base + timedelta(days=i) for i in range(4)]
        dd_series = np.array([0.0, 0.0, -0.10, 0.0])

        periods = extract_drawdown_periods(dates, dd_series, top_n=5)
        assert len(periods) == 1
        period = periods[0]
        assert period.start_date == dates[1]   # last peak before trough
        assert period.trough_date == dates[2]
        assert period.end_date == dates[3]
        assert period.duration_days == 2       # was 1 pre-fix
        assert period.recovery_days == 1

    def test_sorted_by_depth(self):
        navs = np.array([100, 110, 105, 115, 130, 90, 135])
        dd = compute_drawdown_series(np.array(navs, dtype=float))
        periods = extract_drawdown_periods(self._dates(len(navs)), dd, top_n=5)
        if len(periods) > 1:
            assert periods[0].depth <= periods[1].depth


class TestAnalyzeDrawdowns:
    def _dates(self, n: int) -> list[date]:
        return [date(2025, 1, 1) + timedelta(days=i) for i in range(n)]

    def test_returns_result(self):
        navs = np.array([100.0, 110.0, 95.0, 115.0, 120.0])
        result = analyze_drawdowns(navs, self._dates(5))
        assert isinstance(result, DrawdownResult)
        assert len(result.series) == 5
        assert result.max_drawdown < 0
        assert result.current_drawdown == pytest.approx(0.0)
        assert len(result.periods) >= 1

    def test_summary_stats(self):
        navs = np.array([100.0, 110.0, 90.0, 115.0])
        result = analyze_drawdowns(navs, self._dates(4))
        assert result.longest_duration_days is not None
        assert result.avg_recovery_days is not None

    def test_frozen_dataclass(self):
        navs = np.array([100.0, 110.0, 95.0, 115.0])
        result = analyze_drawdowns(navs, self._dates(4))
        with pytest.raises(AttributeError):
            result.max_drawdown = 0.0  # type: ignore[misc]
