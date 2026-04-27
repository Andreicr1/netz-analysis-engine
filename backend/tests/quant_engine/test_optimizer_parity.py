"""Regression tests for optimizer parity fixes (PR-Q41).

S04-F02: optimize_portfolio post-solve constraint verification.
S04-F09: Pareto upper-bound parity with CLARABEL concentration cap.
"""

import numpy as np
import pytest

from quant_engine.optimizer_service import (
    BlockConstraint,
    ProfileConstraints,
    _verify_block_weights,
    optimize_portfolio_pareto,
)

# ── F02: Post-solve constraint verification via _verify_block_weights ────


def test_verify_block_weights_rejects_block_bound_violation():
    """
    When post-solve weights violate a block's max_weight beyond tolerance
    (1e-4), _verify_block_weights must return a violation string.
    """
    block_bounds = {
        "a": BlockConstraint("a", 0.0, 0.20),
        "b": BlockConstraint("b", 0.0, 0.80),
    }
    # Block "a" at 0.45 clearly violates max 0.20
    weights = np.array([0.45, 0.55])
    violation = _verify_block_weights(weights, ["a", "b"], block_bounds, 0.40)
    assert violation is not None
    assert "block_a" in violation
    assert "outside" in violation


def test_verify_block_weights_rejects_min_weight_violation():
    """Block weight below min_weight beyond tolerance must be rejected."""
    block_bounds = {
        "a": BlockConstraint("a", 0.10, 0.60),
        "b": BlockConstraint("b", 0.0, 0.90),
    }
    # Block "a" at 0.05 violates min 0.10
    weights = np.array([0.05, 0.95])
    violation = _verify_block_weights(weights, ["a", "b"], block_bounds, 0.99)
    assert violation is not None
    assert "block_a" in violation


def test_verify_block_weights_rejects_concentration_cap_violation():
    """
    If an unbounded block exceeds max_single_fund_weight beyond tolerance
    after renormalization, the verification must return a violation.
    """
    # No block bounds — only the concentration cap applies
    weights = np.array([0.45, 0.55])
    violation = _verify_block_weights(weights, ["a", "b"], {}, 0.15)
    assert violation is not None
    assert "max_single_fund_weight" in violation


def test_verify_block_weights_accepts_within_tolerance():
    """
    Numerical noise within tolerance (1e-4) must NOT trigger a violation.
    """
    block_bounds = {
        "a": BlockConstraint("a", 0.0, 0.60),
        "b": BlockConstraint("b", 0.0, 0.60),
    }
    # "a" at 0.60005 is within 1e-4 of the 0.60 cap
    weights = np.array([0.60005, 0.39995])
    violation = _verify_block_weights(weights, ["a", "b"], block_bounds, 0.70)
    assert violation is None


def test_verify_block_weights_accepts_exact_bound():
    """Weights exactly at bounds should pass."""
    block_bounds = {"a": BlockConstraint("a", 0.0, 0.50)}
    weights = np.array([0.50, 0.50])
    violation = _verify_block_weights(weights, ["a", "b"], block_bounds, 0.50)
    assert violation is None


# ── F09: Pareto upper bounds ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pareto_upper_bounds_respect_max_single_fund_weight():
    """
    Pareto frontier upper bounds for unconstrained blocks must equal
    max_single_fund_weight, not 1.0. All weights in the frontier must
    satisfy the same concentration cap CLARABEL enforces.
    """
    pytest.importorskip("pymoo")
    constraints = ProfileConstraints(
        blocks=[BlockConstraint("a", 0.0, 0.40)],  # only "a" bounded explicitly
        max_single_fund_weight=0.15,
    )
    result = await optimize_portfolio_pareto(
        block_ids=["a", "b"],
        expected_returns={"a": 0.05, "b": 0.08},
        cov_matrix=np.eye(2) * 0.04,
        constraints=constraints,
    )
    # Block "a" can go up to 0.40 (explicit BlockConstraint).
    # Block "b" must be capped at 0.15 (concentration cap, not 1.0).
    for w_vec in result.pareto_weights:
        assert w_vec[0] <= 0.40 + 1e-4, f"block 'a' violated: {w_vec[0]}"
        assert w_vec[1] <= 0.15 + 1e-4, f"block 'b' violated: {w_vec[1]} > 0.15"

    rec_b = result.recommended_weights.get("b", 0.0)
    assert rec_b <= 0.15 + 1e-4


@pytest.mark.asyncio
async def test_pareto_explicit_bound_respected():
    """Control: explicitly bounded blocks use BlockConstraint.max_weight, not the cap."""
    pytest.importorskip("pymoo")
    # Block "a" explicitly bounded at 0.60, block "b" at 0.50.
    # max_single_fund_weight=0.50 so "b" uses its cap. Sum feasible.
    constraints = ProfileConstraints(
        blocks=[BlockConstraint("a", 0.0, 0.60), BlockConstraint("b", 0.40, 1.0)],
        max_single_fund_weight=1.0,
    )
    result = await optimize_portfolio_pareto(
        block_ids=["a", "b"],
        expected_returns={"a": 0.10, "b": 0.05},
        cov_matrix=np.eye(2) * 0.04,
        constraints=constraints,
    )
    # Block "a" explicit bound 0.60 takes precedence over the 1.0 cap.
    assert result.n_solutions > 0, f"No feasible solutions: {result.status}"
    for w_vec in result.pareto_weights:
        if w_vec:  # skip empty fallback vectors
            assert w_vec[0] <= 0.60 + 1e-4
