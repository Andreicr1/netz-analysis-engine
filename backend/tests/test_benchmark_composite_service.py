"""Tests for quant_engine.benchmark_composite_service."""

from __future__ import annotations

from datetime import date

import pytest

from quant_engine.benchmark_composite_service import NavRow, compute_composite_nav


class TestComputeCompositeNav:
    """Weighted cross-product of block benchmark NAVs."""

    def test_single_block_replicates_benchmark(self) -> None:
        """With one block at 100% weight, composite NAV = benchmark NAV."""
        block_weights = {"equity_us": 1.0}
        benchmark_navs = {
            "equity_us": [
                {"nav_date": date(2024, 1, 2), "return_1d": 0.01},
                {"nav_date": date(2024, 1, 3), "return_1d": -0.005},
                {"nav_date": date(2024, 1, 4), "return_1d": 0.02},
            ],
        }
        result = compute_composite_nav(block_weights, benchmark_navs)

        assert len(result) == 3
        # NAV_0 = 1000, NAV_1 = 1000 * 1.01 = 1010
        assert result[0].nav == pytest.approx(1010.0, abs=1e-8)
        # NAV_2 = 1010 * 0.995 = 1004.95
        assert result[1].nav == pytest.approx(1004.95, abs=1e-8)
        # NAV_3 = 1004.95 * 1.02 = 1025.049
        assert result[2].nav == pytest.approx(1025.049, abs=1e-8)

    def test_two_blocks_weighted_product(self) -> None:
        """Two blocks with 60/40 split produce correct weighted return."""
        block_weights = {"equity": 0.6, "fixed_income": 0.4}
        benchmark_navs = {
            "equity": [
                {"nav_date": date(2024, 1, 2), "return_1d": 0.02},
            ],
            "fixed_income": [
                {"nav_date": date(2024, 1, 2), "return_1d": 0.01},
            ],
        }
        result = compute_composite_nav(block_weights, benchmark_navs, inception_nav=1000.0)

        # R = 0.6*0.02 + 0.4*0.01 = 0.012 + 0.004 = 0.016
        # NAV = 1000 * 1.016 = 1016.0
        assert len(result) == 1
        assert result[0].daily_return == pytest.approx(0.016, abs=1e-8)
        assert result[0].nav == pytest.approx(1016.0, abs=1e-8)

    def test_missing_block_renormalized(self) -> None:
        """If a block has no data for a day, return is renormalized."""
        block_weights = {"a": 0.5, "b": 0.5}
        benchmark_navs = {
            "a": [
                {"nav_date": date(2024, 1, 2), "return_1d": 0.04},
            ],
            # "b" has no data for this date
        }
        result = compute_composite_nav(block_weights, benchmark_navs, inception_nav=1000.0)

        # Only block "a" is active: R_raw = 0.5 * 0.04 = 0.02
        # Renormalize: R = 0.02 * (1.0 / 0.5) = 0.04
        assert len(result) == 1
        assert result[0].daily_return == pytest.approx(0.04, abs=1e-8)
        assert result[0].nav == pytest.approx(1040.0, abs=1e-8)

    def test_empty_inputs_return_empty(self) -> None:
        """Empty weights or empty NAVs return empty list."""
        assert compute_composite_nav({}, {"a": []}) == []
        assert compute_composite_nav({"a": 0.5}, {}) == []

    def test_multi_day_compounding(self) -> None:
        """Multi-day compounding produces correct final NAV."""
        block_weights = {"eq": 1.0}
        benchmark_navs = {
            "eq": [
                {"nav_date": date(2024, 1, i), "return_1d": 0.01}
                for i in range(2, 7)  # 5 days of 1% return
            ],
        }
        result = compute_composite_nav(block_weights, benchmark_navs, inception_nav=100.0)

        # 100 * 1.01^5 = 105.10100501
        assert len(result) == 5
        assert result[-1].nav == pytest.approx(105.10100501, abs=1e-6)

    def test_custom_inception_nav(self) -> None:
        """Custom inception_nav is used as starting value."""
        block_weights = {"eq": 1.0}
        benchmark_navs = {
            "eq": [{"nav_date": date(2024, 1, 2), "return_1d": 0.05}],
        }
        result = compute_composite_nav(block_weights, benchmark_navs, inception_nav=500.0)
        assert result[0].nav == pytest.approx(525.0, abs=1e-8)

    def test_result_is_frozen_navrow(self) -> None:
        """Results are frozen NavRow dataclasses."""
        block_weights = {"eq": 1.0}
        benchmark_navs = {
            "eq": [{"nav_date": date(2024, 1, 2), "return_1d": 0.01}],
        }
        result = compute_composite_nav(block_weights, benchmark_navs)
        assert isinstance(result[0], NavRow)
        with pytest.raises(AttributeError):
            result[0].nav = 999  # type: ignore[misc]

    def test_ignores_block_not_in_weights(self) -> None:
        """Benchmark NAVs for blocks not in weights are ignored."""
        block_weights = {"eq": 1.0}
        benchmark_navs = {
            "eq": [{"nav_date": date(2024, 1, 2), "return_1d": 0.01}],
            "bond": [{"nav_date": date(2024, 1, 2), "return_1d": 0.05}],
        }
        result = compute_composite_nav(block_weights, benchmark_navs)
        assert result[0].daily_return == pytest.approx(0.01, abs=1e-8)
