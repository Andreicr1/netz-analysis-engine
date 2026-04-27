import numpy as np
import pytest

from quant_engine.optimizer_service import (
    BlockConstraint,
    ProfileConstraints,
    optimize_portfolio,
    optimize_portfolio_pareto,
)

# ── Regression tests for S04-F01 (Tier 1) ──────────────────────────────────


@pytest.mark.asyncio
async def test_optimize_portfolio_raises_on_missing_expected_returns():
    """Block-level optimize_portfolio must raise ValueError when
    expected_returns is missing any block_id, matching optimize_fund_portfolio."""
    with pytest.raises(ValueError, match="expected_returns missing"):
        await optimize_portfolio(
            block_ids=["a", "b", "c"],
            expected_returns={"a": 0.05, "c": 0.07},  # "b" missing
            cov_matrix=np.eye(3) * 0.04,
            constraints=ProfileConstraints(blocks=[]),
        )


@pytest.mark.asyncio
async def test_optimize_portfolio_succeeds_with_complete_expected_returns():
    """Control: complete expected_returns must continue to work."""
    result = await optimize_portfolio(
        block_ids=["a", "b"],
        expected_returns={"a": 0.05, "b": 0.07},
        cov_matrix=np.eye(2) * 0.04,
        constraints=ProfileConstraints(
            blocks=[
                BlockConstraint("a", 0.0, 1.0),
                BlockConstraint("b", 0.0, 1.0),
            ],
            max_single_fund_weight=1.0,
        ),
    )
    assert result.status in ("optimal", "optimal_inaccurate")


@pytest.mark.asyncio
async def test_optimize_portfolio_pareto_raises_on_missing_expected_returns():
    """optimize_portfolio_pareto must also raise ValueError on missing returns."""
    pytest.importorskip("pymoo")  # pareto path requires pymoo
    with pytest.raises(ValueError, match="expected_returns missing"):
        await optimize_portfolio_pareto(
            block_ids=["a", "b", "c"],
            expected_returns={"a": 0.05},  # "b" and "c" missing
            cov_matrix=np.eye(3) * 0.04,
            constraints=ProfileConstraints(blocks=[]),
        )


@pytest.mark.asyncio
async def test_optimize_portfolio_pareto_succeeds_with_complete_expected_returns():
    """Control for pareto path."""
    pytest.importorskip("pymoo")
    result = await optimize_portfolio_pareto(
        block_ids=["a", "b"],
        expected_returns={"a": 0.05, "b": 0.07},
        cov_matrix=np.eye(2) * 0.04,
        constraints=ProfileConstraints(
            blocks=[
                BlockConstraint("a", 0.0, 1.0),
                BlockConstraint("b", 0.0, 1.0),
            ],
        ),
    )
    assert result.status in ("optimal", "fallback_clarabel")


@pytest.mark.asyncio
async def test_error_message_includes_missing_block_ids():
    """Error message must list the missing block IDs (or a truncated sample)
    for debuggability."""
    with pytest.raises(ValueError) as exc_info:
        await optimize_portfolio(
            block_ids=["a", "b", "c", "d", "e", "f", "g"],
            expected_returns={"a": 0.05},  # 6 missing
            cov_matrix=np.eye(7) * 0.04,
            constraints=ProfileConstraints(blocks=[]),
        )
    error_msg = str(exc_info.value)
    assert "6 block(s)" in error_msg or "missing 6" in error_msg
    # Should include at least one missing id (truncated to first 5)
    assert any(bid in error_msg for bid in ["b", "c", "d", "e", "f"])


# ── Symmetry verification ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_all_three_entry_points_share_missing_returns_behavior():
    """optimize_portfolio, optimize_portfolio_pareto, optimize_fund_portfolio
    must all raise ValueError consistently on missing expected_returns."""
    from quant_engine.optimizer_service import optimize_fund_portfolio

    # Block-level
    with pytest.raises(ValueError, match="missing"):
        await optimize_portfolio(
            block_ids=["a"],
            expected_returns={},
            cov_matrix=np.array([[0.04]]),
            constraints=ProfileConstraints(blocks=[]),
        )

    # Fund-level (already implemented; sanity check)
    with pytest.raises(ValueError, match="missing"):
        await optimize_fund_portfolio(
            fund_ids=["a"],
            fund_blocks={"a": "block_x"},
            expected_returns={},
            constraints=ProfileConstraints(
                blocks=[BlockConstraint("block_x", 0.0, 1.0)],
            ),
            cov_matrix=np.array([[0.04]]),
        )

    # Pareto (skip if pymoo missing)
    pytest.importorskip("pymoo")
    with pytest.raises(ValueError, match="missing"):
        await optimize_portfolio_pareto(
            block_ids=["a"],
            expected_returns={},
            cov_matrix=np.array([[0.04]]),
            constraints=ProfileConstraints(blocks=[]),
        )
