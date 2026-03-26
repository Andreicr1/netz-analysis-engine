"""Tests for quant_engine/rolling_service.py."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from quant_engine.rolling_service import (
    ROLLING_WINDOWS,
    RollingSeriesResult,
    compute_rolling_returns,
)


class TestComputeRollingReturns:
    def _dates(self, n: int) -> list[str]:
        return [(date(2025, 1, 2) + timedelta(days=i)).isoformat() for i in range(n)]

    def test_empty_returns(self):
        result = compute_rolling_returns([], np.array([]))
        assert result == []

    def test_insufficient_data(self):
        """10 days < smallest window (21d) → empty."""
        result = compute_rolling_returns(self._dates(10), np.full(10, 0.001))
        assert result == []

    def test_one_month_window(self):
        n = 30
        dates = self._dates(n)
        returns = np.full(n, 0.001)
        result = compute_rolling_returns(dates, returns)
        labels = [s.window_label for s in result]
        assert "1M" in labels
        assert "3M" not in labels  # 30 < 63

    def test_all_windows(self):
        n = 300
        dates = self._dates(n)
        returns = np.full(n, 0.0004)
        result = compute_rolling_returns(dates, returns)
        labels = [s.window_label for s in result]
        assert "1M" in labels
        assert "3M" in labels
        assert "6M" in labels
        assert "1Y" in labels

    def test_output_length(self):
        """1Y window on 252 points → exactly 1 output point."""
        n = 252
        result = compute_rolling_returns(self._dates(n), np.full(n, 0.0004))
        one_y = next(s for s in result if s.window_label == "1Y")
        assert len(one_y.values) == 1
        assert len(one_y.dates) == 1

    def test_annualized_positive(self):
        """Constant positive daily return → positive annualized return."""
        n = 63
        result = compute_rolling_returns(self._dates(n), np.full(n, 0.001))
        three_m = next(s for s in result if s.window_label == "3M")
        assert three_m.values[0] > 0

    def test_custom_windows(self):
        n = 50
        custom = [("2W", 10), ("1M", 21)]
        result = compute_rolling_returns(self._dates(n), np.full(n, 0.001), windows=custom)
        labels = [s.window_label for s in result]
        assert "2W" in labels
        assert "1M" in labels

    def test_result_type(self):
        n = 30
        result = compute_rolling_returns(self._dates(n), np.full(n, 0.001))
        for s in result:
            assert isinstance(s, RollingSeriesResult)
            assert isinstance(s.window_days, int)

    def test_frozen_dataclass(self):
        n = 30
        result = compute_rolling_returns(self._dates(n), np.full(n, 0.001))
        with pytest.raises(AttributeError):
            result[0].window_label = "X"  # type: ignore[misc]

    def test_default_windows_constant(self):
        assert len(ROLLING_WINDOWS) == 4
        labels = [w[0] for w in ROLLING_WINDOWS]
        assert labels == ["1M", "3M", "6M", "1Y"]
