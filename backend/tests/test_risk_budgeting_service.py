"""Tests for quant_engine/risk_budgeting_service.py — eVestment p.43-44."""

from __future__ import annotations

import numpy as np
import pytest

from quant_engine.risk_budgeting_service import (
    FundRiskBudget,
    RiskBudgetResult,
    compute_risk_budget,
)

# ── Fixtures ──────────────────────────────────────────────────────────


def _make_returns_matrix(
    n_days: int = 504, n_funds: int = 4, seed: int = 42,
) -> np.ndarray:
    """Generate synthetic T×N daily returns."""
    rng = np.random.RandomState(seed)
    # Different volatilities per fund
    vols = np.array([0.008, 0.012, 0.015, 0.010])[:n_funds]
    means = np.array([0.0002, 0.0004, 0.0003, 0.0001])[:n_funds]
    return rng.normal(means, vols, (n_days, n_funds))


def _equal_weights(n: int) -> np.ndarray:
    return np.full(n, 1.0 / n)


def _block_ids(n: int) -> list[str]:
    return [f"block_{i}" for i in range(n)]


def _block_names(n: int) -> list[str]:
    return [f"Block {i}" for i in range(n)]


# ── Basic functionality ──────────────────────────────────────────────


class TestComputeRiskBudget:
    def test_returns_result_type(self):
        matrix = _make_returns_matrix()
        n = matrix.shape[1]
        result = compute_risk_budget(
            weights=_equal_weights(n),
            returns_matrix=matrix,
            block_ids=_block_ids(n),
            block_names=_block_names(n),
        )
        assert isinstance(result, RiskBudgetResult)

    def test_correct_number_of_funds(self):
        matrix = _make_returns_matrix(n_funds=4)
        result = compute_risk_budget(
            weights=_equal_weights(4),
            returns_matrix=matrix,
            block_ids=_block_ids(4),
            block_names=_block_names(4),
        )
        assert len(result.funds) == 4

    def test_portfolio_volatility_positive(self):
        matrix = _make_returns_matrix()
        n = matrix.shape[1]
        result = compute_risk_budget(
            weights=_equal_weights(n),
            returns_matrix=matrix,
            block_ids=_block_ids(n),
            block_names=_block_names(n),
        )
        assert result.portfolio_volatility > 0

    def test_portfolio_etl_negative(self):
        """ETL should be negative (it's a tail loss)."""
        matrix = _make_returns_matrix()
        n = matrix.shape[1]
        result = compute_risk_budget(
            weights=_equal_weights(n),
            returns_matrix=matrix,
            block_ids=_block_ids(n),
            block_names=_block_names(n),
        )
        assert result.portfolio_etl < 0

    def test_insufficient_data(self):
        """With < 30 observations, should return empty result."""
        matrix = _make_returns_matrix(n_days=10)
        n = matrix.shape[1]
        result = compute_risk_budget(
            weights=_equal_weights(n),
            returns_matrix=matrix,
            block_ids=_block_ids(n),
            block_names=_block_names(n),
        )
        assert result.portfolio_volatility == 0.0
        assert len(result.funds) == 0


# ── PCTR sum invariant ───────────────────────────────────────────────


class TestPCTR:
    def test_pctr_sums_to_one(self):
        """PCTR must sum to 100% (within tolerance)."""
        matrix = _make_returns_matrix()
        n = matrix.shape[1]
        result = compute_risk_budget(
            weights=_equal_weights(n),
            returns_matrix=matrix,
            block_ids=_block_ids(n),
            block_names=_block_names(n),
        )
        pctr_sum = sum(f.pctr for f in result.funds if f.pctr is not None)
        assert pctr_sum == pytest.approx(1.0, abs=0.01)

    def test_pctr_all_populated(self):
        """All funds should have PCTR populated."""
        matrix = _make_returns_matrix()
        n = matrix.shape[1]
        result = compute_risk_budget(
            weights=_equal_weights(n),
            returns_matrix=matrix,
            block_ids=_block_ids(n),
            block_names=_block_names(n),
        )
        for f in result.funds:
            assert f.pctr is not None


# ── PCETL sum invariant ──────────────────────────────────────────────


class TestPCETL:
    def test_pcetl_sums_to_one(self):
        """PCETL must sum to 100% (within tolerance)."""
        matrix = _make_returns_matrix()
        n = matrix.shape[1]
        result = compute_risk_budget(
            weights=_equal_weights(n),
            returns_matrix=matrix,
            block_ids=_block_ids(n),
            block_names=_block_names(n),
        )
        pcetl_sum = sum(f.pcetl for f in result.funds if f.pcetl is not None)
        assert pcetl_sum == pytest.approx(1.0, abs=0.01)

    def test_pcetl_all_populated(self):
        """All funds should have PCETL populated."""
        matrix = _make_returns_matrix()
        n = matrix.shape[1]
        result = compute_risk_budget(
            weights=_equal_weights(n),
            returns_matrix=matrix,
            block_ids=_block_ids(n),
            block_names=_block_names(n),
        )
        for f in result.funds:
            assert f.pcetl is not None


# ── MCTR consistency ─────────────────────────────────────────────────


class TestMCTR:
    def test_mctr_sum_equals_portfolio_vol(self):
        """Sum of w_i * MCTR_i should equal portfolio volatility."""
        matrix = _make_returns_matrix()
        n = matrix.shape[1]
        w = _equal_weights(n)
        result = compute_risk_budget(
            weights=w,
            returns_matrix=matrix,
            block_ids=_block_ids(n),
            block_names=_block_names(n),
        )
        mctr_weighted_sum = sum(
            f.weight * f.mctr for f in result.funds if f.mctr is not None
        )
        assert mctr_weighted_sum == pytest.approx(result.portfolio_volatility, rel=0.01)


# ── Implied Returns ──────────────────────────────────────────────────


class TestImpliedReturns:
    def test_implied_return_populated(self):
        """Implied returns should be computed for all funds."""
        matrix = _make_returns_matrix()
        n = matrix.shape[1]
        result = compute_risk_budget(
            weights=_equal_weights(n),
            returns_matrix=matrix,
            block_ids=_block_ids(n),
            block_names=_block_names(n),
        )
        for f in result.funds:
            assert f.implied_return_vol is not None
            assert f.implied_return_etl is not None

    def test_difference_is_mean_minus_implied(self):
        """Difference = mean_return - implied_return."""
        matrix = _make_returns_matrix()
        n = matrix.shape[1]
        result = compute_risk_budget(
            weights=_equal_weights(n),
            returns_matrix=matrix,
            block_ids=_block_ids(n),
            block_names=_block_names(n),
        )
        for f in result.funds:
            assert f.difference_vol is not None
            assert f.implied_return_vol is not None
            expected_diff = f.mean_return - f.implied_return_vol
            assert f.difference_vol == pytest.approx(expected_diff, abs=1e-6)


# ── STARR ────────────────────────────────────────────────────────────


class TestSTARR:
    def test_starr_populated(self):
        """Portfolio STARR should be computed."""
        matrix = _make_returns_matrix()
        n = matrix.shape[1]
        result = compute_risk_budget(
            weights=_equal_weights(n),
            returns_matrix=matrix,
            block_ids=_block_ids(n),
            block_names=_block_names(n),
        )
        assert result.portfolio_starr is not None


# ── Edge cases ───────────────────────────────────────────────────────


class TestEdgeCases:
    def test_single_fund(self):
        """Single fund: PCTR and PCETL should be 1.0."""
        matrix = _make_returns_matrix(n_funds=1)
        result = compute_risk_budget(
            weights=np.array([1.0]),
            returns_matrix=matrix,
            block_ids=["block_0"],
            block_names=["Block 0"],
        )
        assert len(result.funds) == 1
        assert result.funds[0].pctr == pytest.approx(1.0, abs=0.01)

    def test_concentrated_weights(self):
        """Highly concentrated portfolio should still produce valid output."""
        matrix = _make_returns_matrix(n_funds=4)
        w = np.array([0.90, 0.05, 0.03, 0.02])
        result = compute_risk_budget(
            weights=w,
            returns_matrix=matrix,
            block_ids=_block_ids(4),
            block_names=_block_names(4),
        )
        pctr_sum = sum(f.pctr for f in result.funds if f.pctr is not None)
        assert pctr_sum == pytest.approx(1.0, abs=0.01)

    def test_frozen_dataclass(self):
        """FundRiskBudget and RiskBudgetResult should be frozen."""
        matrix = _make_returns_matrix()
        n = matrix.shape[1]
        result = compute_risk_budget(
            weights=_equal_weights(n),
            returns_matrix=matrix,
            block_ids=_block_ids(n),
            block_names=_block_names(n),
        )
        with pytest.raises(AttributeError):
            result.portfolio_volatility = 0.0  # type: ignore[misc]
        with pytest.raises(AttributeError):
            result.funds[0].mctr = 0.0  # type: ignore[misc]
