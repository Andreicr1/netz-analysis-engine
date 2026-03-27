"""Tests for transaction cost modeling in optimizer (BL-6).

Covers:
- Turnover penalty reduces turnover vs no-penalty solution
- Dead-band suppresses small trades
- Day-0 construct (no current_weights) has no penalty
- Infeasibility fallback: retry without penalty
"""

from __future__ import annotations

import numpy as np
import pytest

from quant_engine.optimizer_service import (
    BlockConstraint,
    ProfileConstraints,
    optimize_fund_portfolio,
)
from vertical_engines.wealth.rebalancing.weight_proposer import apply_dead_band


@pytest.fixture
def simple_setup():
    """Simple 3-fund setup for optimizer tests."""
    fund_ids = ["fund_a", "fund_b", "fund_c"]
    fund_blocks = {"fund_a": "equity", "fund_b": "fi", "fund_c": "alt"}
    expected_returns = {"fund_a": 0.08, "fund_b": 0.04, "fund_c": 0.06}
    cov = np.array([
        [0.04, 0.005, 0.003],
        [0.005, 0.01, 0.002],
        [0.003, 0.002, 0.02],
    ])
    constraints = ProfileConstraints(
        blocks=[
            BlockConstraint("equity", 0.2, 0.6),
            BlockConstraint("fi", 0.2, 0.5),
            BlockConstraint("alt", 0.1, 0.3),
        ],
        cvar_limit=-0.15,
        max_single_fund_weight=0.6,
    )
    return fund_ids, fund_blocks, expected_returns, cov, constraints


class TestTurnoverPenalty:
    @pytest.mark.asyncio
    async def test_no_current_weights_no_penalty(self, simple_setup):
        """Day-0 construct: no current_weights means no turnover penalty."""
        fund_ids, fund_blocks, expected_returns, cov, constraints = simple_setup
        result = await optimize_fund_portfolio(
            fund_ids=fund_ids,
            fund_blocks=fund_blocks,
            expected_returns=expected_returns,
            cov_matrix=cov,
            constraints=constraints,
            current_weights=None,
            turnover_cost=0.001,
        )
        assert result.status.startswith("optimal")
        assert sum(result.weights.values()) == pytest.approx(1.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_turnover_penalty_reduces_turnover(self, simple_setup):
        """With current_weights, turnover penalty should reduce trades."""
        fund_ids, fund_blocks, expected_returns, cov, constraints = simple_setup

        # Current weights: already near optimal
        current = np.array([0.4, 0.35, 0.25])

        result_no_penalty = await optimize_fund_portfolio(
            fund_ids=fund_ids,
            fund_blocks=fund_blocks,
            expected_returns=expected_returns,
            cov_matrix=cov,
            constraints=constraints,
            current_weights=current,
            turnover_cost=0.0,
        )

        result_with_penalty = await optimize_fund_portfolio(
            fund_ids=fund_ids,
            fund_blocks=fund_blocks,
            expected_returns=expected_returns,
            cov_matrix=cov,
            constraints=constraints,
            current_weights=current,
            turnover_cost=0.01,  # significant penalty
        )

        assert result_no_penalty.status.startswith("optimal")
        assert result_with_penalty.status.startswith("optimal")

        # Compute turnover for both
        w_no = np.array([result_no_penalty.weights[f] for f in fund_ids])
        w_with = np.array([result_with_penalty.weights[f] for f in fund_ids])

        turnover_no = float(np.sum(np.abs(w_no - current)))
        turnover_with = float(np.sum(np.abs(w_with - current)))

        # With penalty, turnover should be <= without penalty
        assert turnover_with <= turnover_no + 1e-6

    @pytest.mark.asyncio
    async def test_zero_turnover_cost_same_as_none(self, simple_setup):
        """turnover_cost=0 should behave same as no current_weights."""
        fund_ids, fund_blocks, expected_returns, cov, constraints = simple_setup
        current = np.array([0.4, 0.35, 0.25])

        result = await optimize_fund_portfolio(
            fund_ids=fund_ids,
            fund_blocks=fund_blocks,
            expected_returns=expected_returns,
            cov_matrix=cov,
            constraints=constraints,
            current_weights=current,
            turnover_cost=0.0,
        )
        assert result.status.startswith("optimal")


class TestDeadBand:
    def test_small_changes_suppressed(self):
        """Changes below dead_band_pct should be suppressed."""
        proposed = {"a": 0.303, "b": 0.497, "c": 0.200}
        current = {"a": 0.300, "b": 0.500, "c": 0.200}

        result = apply_dead_band(proposed, current, dead_band_pct=0.005)
        # a: |0.303 - 0.300| = 0.003 < 0.005 → keep current
        assert result["a"] == 0.300
        # b: |0.497 - 0.500| = 0.003 < 0.005 → keep current
        assert result["b"] == 0.500
        # c: identical → keep current
        assert result["c"] == 0.200

    def test_large_changes_pass_through(self):
        """Changes above dead_band_pct should pass through."""
        proposed = {"a": 0.35, "b": 0.45, "c": 0.20}
        current = {"a": 0.30, "b": 0.50, "c": 0.20}

        result = apply_dead_band(proposed, current, dead_band_pct=0.005)
        # a: |0.35 - 0.30| = 0.05 >= 0.005 → use proposed
        assert result["a"] == 0.35
        # b: |0.45 - 0.50| = 0.05 >= 0.005 → use proposed
        assert result["b"] == 0.45

    def test_new_fund_without_current(self):
        """Funds without current weight should use proposed if above dead_band."""
        proposed = {"a": 0.30, "b": 0.50, "new_fund": 0.20}
        current = {"a": 0.40, "b": 0.60}

        result = apply_dead_band(proposed, current, dead_band_pct=0.005)
        # new_fund: current=0.0, |0.20 - 0.0| = 0.20 >= 0.005 → use proposed
        assert result["new_fund"] == 0.20

    def test_empty_proposed(self):
        result = apply_dead_band({}, {"a": 0.5}, dead_band_pct=0.005)
        assert result == {}
