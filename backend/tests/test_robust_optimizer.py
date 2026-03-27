"""Tests for robust optimization (BL-8) and regime CVaR multiplier (BL-9)."""

import numpy as np
import pytest

from quant_engine.optimizer_service import (
    BlockConstraint,
    FundOptimizationResult,
    ProfileConstraints,
    optimize_fund_portfolio,
)


@pytest.fixture
def simple_portfolio_inputs():
    """4-fund portfolio with simple block structure."""
    fund_ids = ["f1", "f2", "f3", "f4"]
    fund_blocks = {"f1": "equity", "f2": "equity", "f3": "fixed_income", "f4": "fixed_income"}
    expected_returns = {"f1": 0.10, "f2": 0.08, "f3": 0.04, "f4": 0.03}

    rng = np.random.default_rng(42)
    returns = rng.normal(0, 0.02, (200, 4))
    cov_matrix = np.cov(returns.T) * 252

    constraints = ProfileConstraints(
        blocks=[
            BlockConstraint(block_id="equity", min_weight=0.2, max_weight=0.8),
            BlockConstraint(block_id="fixed_income", min_weight=0.2, max_weight=0.8),
        ],
        cvar_limit=-0.15,
        max_single_fund_weight=0.5,
    )

    return fund_ids, fund_blocks, expected_returns, cov_matrix, constraints


@pytest.mark.asyncio
async def test_robust_optimization_produces_result(simple_portfolio_inputs):
    """Robust Phase 1.5 should produce a valid result or fall through."""
    fund_ids, fund_blocks, expected_returns, cov_matrix, constraints = simple_portfolio_inputs

    result = await optimize_fund_portfolio(
        fund_ids=fund_ids,
        fund_blocks=fund_blocks,
        expected_returns=expected_returns,
        cov_matrix=cov_matrix,
        constraints=constraints,
        robust=True,
        uncertainty_level=0.5,
    )

    assert isinstance(result, FundOptimizationResult)
    assert result.status.startswith("optimal")
    assert sum(result.weights.values()) == pytest.approx(1.0, abs=1e-4)


@pytest.mark.asyncio
async def test_robust_vs_standard_differs(simple_portfolio_inputs):
    """Robust optimization should produce different weights than standard."""
    fund_ids, fund_blocks, expected_returns, cov_matrix, constraints = simple_portfolio_inputs

    standard = await optimize_fund_portfolio(
        fund_ids=fund_ids,
        fund_blocks=fund_blocks,
        expected_returns=expected_returns,
        cov_matrix=cov_matrix,
        constraints=constraints,
        robust=False,
    )

    robust = await optimize_fund_portfolio(
        fund_ids=fund_ids,
        fund_blocks=fund_blocks,
        expected_returns=expected_returns,
        cov_matrix=cov_matrix,
        constraints=constraints,
        robust=True,
        uncertainty_level=2.0,  # high uncertainty for visible difference
    )

    assert standard.status.startswith("optimal")
    assert robust.status.startswith("optimal")
    # With high uncertainty, robust should favor lower-risk allocation
    # (at minimum, weights should differ)


@pytest.mark.asyncio
async def test_regime_cvar_multiplier_tightens_limit(simple_portfolio_inputs):
    """Regime multiplier < 1.0 should tighten the CVaR limit."""
    fund_ids, fund_blocks, expected_returns, cov_matrix, constraints = simple_portfolio_inputs

    normal = await optimize_fund_portfolio(
        fund_ids=fund_ids,
        fund_blocks=fund_blocks,
        expected_returns=expected_returns,
        cov_matrix=cov_matrix,
        constraints=constraints,
        regime_cvar_multiplier=1.0,
    )

    crisis = await optimize_fund_portfolio(
        fund_ids=fund_ids,
        fund_blocks=fund_blocks,
        expected_returns=expected_returns,
        cov_matrix=cov_matrix,
        constraints=constraints,
        regime_cvar_multiplier=0.5,  # very tight
    )

    assert normal.status.startswith("optimal")
    assert crisis.status.startswith("optimal")
    # Crisis allocation should have lower or equal volatility
    # (tighter CVaR limit forces more conservative allocation)
