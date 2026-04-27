"""PR-Q36 F05: rank_transform dynamic time-level extraction."""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant_engine.ipca.preprocessing import rank_transform


class TestRankTransformDynamicLevel:
    """F05: groups by named time level, falls back to positional level=1."""

    def test_named_date_level_at_position_zero(self):
        """rank_transform groups by 'date' even when it's at level=0."""
        dates = pd.date_range("2024-01-01", periods=3)
        instruments = ["A", "B"]
        # date at level=0 (non-standard ordering)
        idx = pd.MultiIndex.from_product(
            [dates, instruments], names=["date", "instrument_id"]
        )
        chars = pd.DataFrame(
            {"book_to_market": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}, index=idx
        )

        result = rank_transform(chars)

        # Per-date ranking: within each date, 2 instruments get distinct ranks
        for date in dates:
            date_slice = result.xs(date, level="date")
            assert len(date_slice) == 2
            assert date_slice["book_to_market"].nunique() == 2

    def test_named_month_level(self):
        """rank_transform groups by 'month' level when present."""
        months = pd.date_range("2024-01-31", periods=3, freq="ME")
        instruments = ["X", "Y", "Z"]
        idx = pd.MultiIndex.from_product(
            [instruments, months], names=["instrument_id", "month"]
        )
        chars = pd.DataFrame(
            {"x": np.arange(9, dtype=float)}, index=idx
        )

        result = rank_transform(chars)
        assert result.shape == chars.shape
        # Values must be in [-0.5, +0.5]
        assert result["x"].min() >= -0.5
        assert result["x"].max() <= 0.5

    def test_named_as_of_level(self):
        """rank_transform groups by 'as_of' level when present."""
        dates = pd.date_range("2024-01-01", periods=2)
        instruments = ["A", "B"]
        idx = pd.MultiIndex.from_product(
            [instruments, dates], names=["instrument_id", "as_of"]
        )
        chars = pd.DataFrame({"y": [10.0, 20.0, 30.0, 40.0]}, index=idx)

        result = rank_transform(chars)
        assert result.shape == chars.shape

    def test_positional_fallback_unnamed_index(self):
        """Falls back to level=1 for unnamed MultiIndex."""
        instruments = ["A", "B"]
        dates = pd.date_range("2024-01-01", periods=3)
        idx = pd.MultiIndex.from_product([instruments, dates])  # no names
        chars = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}, index=idx)

        result = rank_transform(chars)
        assert result.shape == chars.shape

    def test_single_index_fallback(self):
        """Single-index DataFrame doesn't crash."""
        chars = pd.DataFrame({"x": [3.0, 1.0, 2.0]}, index=["a", "b", "c"])
        result = rank_transform(chars)
        assert result.shape == chars.shape
