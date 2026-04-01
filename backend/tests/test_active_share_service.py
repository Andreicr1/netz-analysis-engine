"""Tests for quant_engine/active_share_service.py — eVestment p.73."""

from __future__ import annotations

import pytest

from quant_engine.active_share_service import (
    ActiveShareResult,
    compute_active_share,
)

# ── Basic functionality ──────────────────────────────────────────────


class TestComputeActiveShare:
    def test_returns_result_type(self):
        result = compute_active_share(
            portfolio_weights={"A": 0.5, "B": 0.5},
            benchmark_weights={"A": 0.5, "B": 0.5},
        )
        assert isinstance(result, ActiveShareResult)

    def test_identical_portfolios(self):
        """Identical portfolios → active share = 0%."""
        result = compute_active_share(
            portfolio_weights={"A": 0.4, "B": 0.3, "C": 0.3},
            benchmark_weights={"A": 0.4, "B": 0.3, "C": 0.3},
        )
        assert result.active_share == pytest.approx(0.0, abs=0.01)
        assert result.overlap == pytest.approx(100.0, abs=0.01)

    def test_no_overlap(self):
        """Completely different portfolios → active share = 100%."""
        result = compute_active_share(
            portfolio_weights={"A": 0.5, "B": 0.5},
            benchmark_weights={"C": 0.5, "D": 0.5},
        )
        assert result.active_share == pytest.approx(100.0, abs=0.01)
        assert result.overlap == pytest.approx(0.0, abs=0.01)

    def test_known_active_share(self):
        """Known example: fund overweights A, underweights B."""
        result = compute_active_share(
            portfolio_weights={"A": 0.60, "B": 0.40},
            benchmark_weights={"A": 0.50, "B": 0.50},
        )
        # |0.60-0.50| + |0.40-0.50| = 0.10 + 0.10 = 0.20 → AS = 10%
        assert result.active_share == pytest.approx(10.0, abs=0.01)

    def test_partial_overlap(self):
        """Fund has positions not in benchmark and vice versa."""
        result = compute_active_share(
            portfolio_weights={"A": 0.40, "B": 0.30, "C": 0.30},
            benchmark_weights={"A": 0.50, "B": 0.50},
        )
        # A: |0.40-0.50|=0.10, B: |0.30-0.50|=0.20, C: |0.30-0|=0.30
        # total_diff = 0.60, AS = 0.60/2 * 100 = 30%
        assert result.active_share == pytest.approx(30.0, abs=0.01)


# ── Position Counts ──────────────────────────────────────────────────


class TestPositionCounts:
    def test_position_counts(self):
        result = compute_active_share(
            portfolio_weights={"A": 0.3, "B": 0.3, "C": 0.4},
            benchmark_weights={"A": 0.5, "D": 0.5},
        )
        assert result.n_portfolio_positions == 3
        assert result.n_benchmark_positions == 2
        assert result.n_common_positions == 1  # only A

    def test_all_common(self):
        result = compute_active_share(
            portfolio_weights={"A": 0.5, "B": 0.5},
            benchmark_weights={"A": 0.5, "B": 0.5},
        )
        assert result.n_common_positions == 2


# ── Active Share Efficiency ──────────────────────────────────────────


class TestActiveShareEfficiency:
    def test_efficiency_computed(self):
        result = compute_active_share(
            portfolio_weights={"A": 0.60, "B": 0.40},
            benchmark_weights={"A": 0.50, "B": 0.50},
            excess_return=0.03,
        )
        # AS = 10%, efficiency = 0.03 / 0.10 = 0.3
        assert result.active_share_efficiency is not None
        assert result.active_share_efficiency == pytest.approx(0.3, abs=0.01)

    def test_efficiency_none_without_excess(self):
        result = compute_active_share(
            portfolio_weights={"A": 0.5, "B": 0.5},
            benchmark_weights={"A": 0.4, "B": 0.6},
        )
        assert result.active_share_efficiency is None

    def test_efficiency_none_when_zero_as(self):
        """Efficiency undefined when active share is 0."""
        result = compute_active_share(
            portfolio_weights={"A": 0.5, "B": 0.5},
            benchmark_weights={"A": 0.5, "B": 0.5},
            excess_return=0.02,
        )
        assert result.active_share_efficiency is None


# ── Edge Cases ───────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_portfolio(self):
        result = compute_active_share(
            portfolio_weights={},
            benchmark_weights={"A": 0.5, "B": 0.5},
        )
        assert result.active_share == 100.0
        assert result.n_portfolio_positions == 0
        assert result.n_common_positions == 0

    def test_empty_benchmark(self):
        result = compute_active_share(
            portfolio_weights={"A": 0.5, "B": 0.5},
            benchmark_weights={},
        )
        assert result.active_share == 100.0

    def test_single_position(self):
        result = compute_active_share(
            portfolio_weights={"A": 1.0},
            benchmark_weights={"A": 1.0},
        )
        assert result.active_share == pytest.approx(0.0, abs=0.01)

    def test_active_share_bounded(self):
        """Active share should always be in [0, 100]."""
        result = compute_active_share(
            portfolio_weights={"A": 1.0},
            benchmark_weights={"B": 1.0},
        )
        assert 0.0 <= result.active_share <= 100.0

    def test_overlap_complement(self):
        """Overlap should be 100 - active_share."""
        result = compute_active_share(
            portfolio_weights={"A": 0.6, "B": 0.4},
            benchmark_weights={"A": 0.5, "C": 0.5},
        )
        assert result.active_share + result.overlap == pytest.approx(100.0, abs=0.01)

    def test_frozen_dataclass(self):
        result = compute_active_share(
            portfolio_weights={"A": 0.5, "B": 0.5},
            benchmark_weights={"A": 0.5, "B": 0.5},
        )
        with pytest.raises(AttributeError):
            result.active_share = 0.0  # type: ignore[misc]
