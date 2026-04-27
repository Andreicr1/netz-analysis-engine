"""Regression tests for S07-F10 (mid-rank ties) + S07-F09 (min-N guard)."""

from __future__ import annotations

import numpy as np
import pytest

from quant_engine.peer_group_service import (
    MIN_PEER_COHORT_SIZE,
    _percentile_rank,
    compute_peer_rankings,
)

# ── F10: mid-rank convention ────────────────────────────────────────────


def test_all_tied_higher_is_better_ranks_at_median() -> None:
    """4 funds all tied → all rank at 50, not 100. Higher-is-better."""
    rank = _percentile_rank(0.0, np.array([0.0, 0.0, 0.0, 0.0]), higher_is_better=True)
    assert rank == 50.0


def test_all_tied_lower_is_better_ranks_at_median() -> None:
    """4 funds all tied at zero drawdown → 50, not 100. Lower-is-better."""
    rank = _percentile_rank(0.0, np.array([0.0, 0.0, 0.0, 0.0]), higher_is_better=False)
    assert rank == 50.0


def test_single_best_ranks_at_100() -> None:
    """Strict top → 100."""
    rank = _percentile_rank(10.0, np.array([1.0, 2.0, 3.0]), higher_is_better=True)
    assert rank == 100.0


def test_single_worst_ranks_at_0() -> None:
    """Strict bottom → 0."""
    rank = _percentile_rank(0.0, np.array([1.0, 2.0, 3.0]), higher_is_better=True)
    assert rank == 0.0


def test_partial_tie_higher_is_better() -> None:
    """3 peers [1, 2, 2], value=2 (tied with one) → mid-rank.
    below=1, equal=2 → (1 + 1.0)/3 * 100 ≈ 66.67."""
    rank = _percentile_rank(2.0, np.array([1.0, 2.0, 2.0]), higher_is_better=True)
    assert rank == pytest.approx(66.67, abs=0.01)


def test_partial_tie_lower_is_better() -> None:
    """Lower-is-better: peers [1, 2, 2], value=2 → above=0, equal=2 → (0 + 1.0)/3 ≈ 33.33."""
    rank = _percentile_rank(2.0, np.array([1.0, 2.0, 2.0]), higher_is_better=False)
    assert rank == pytest.approx(33.33, abs=0.01)


def test_empty_peers_returns_50() -> None:
    """No peers → median sentinel."""
    rank = _percentile_rank(1.0, np.array([]), higher_is_better=True)
    assert rank == 50.0


# ── F09: min-N guard ───────────────────────────────────────────────────


def _mk_peer(sharpe: float, ret: float = 0.05, dd: float = -0.05) -> dict:
    return {
        "sharpe_1y": sharpe,
        "sortino_1y": sharpe * 1.1,
        "return_1y": ret,
        "max_drawdown_1y": dd,
        "volatility_1y": 0.10,
        "alpha_1y": 0.01,
        "manager_score": 50.0,
    }


def test_thin_cohort_returns_degraded_with_median_percentile() -> None:
    """N=2 cohort → degraded result with all percentiles at 50.0."""
    fund = _mk_peer(1.5)
    peers = [_mk_peer(1.4)]  # N=1 peer + the fund itself in queries
    result = compute_peer_rankings(fund, peers, strategy_label="Niche EM Debt")
    assert result.peer_count == 1
    assert result.degraded is True
    assert "insufficient_peer_cohort" in (result.degraded_reason or "")
    for ranking in result.rankings:
        assert ranking.percentile == 50.0
        assert ranking.quartile == 2


def test_below_min_cohort_returns_degraded() -> None:
    """N just below MIN_PEER_COHORT_SIZE → degraded."""
    fund = _mk_peer(1.5)
    peers = [_mk_peer(1.0 + i * 0.1) for i in range(MIN_PEER_COHORT_SIZE - 1)]
    result = compute_peer_rankings(fund, peers, strategy_label="Tiny Cohort")
    assert result.degraded is True


def test_at_min_cohort_returns_full_ranking() -> None:
    """N exactly at MIN_PEER_COHORT_SIZE → full ranking, not degraded."""
    fund = _mk_peer(2.5)
    peers = [_mk_peer(1.0 + i * 0.1) for i in range(MIN_PEER_COHORT_SIZE)]
    result = compute_peer_rankings(fund, peers, strategy_label="Adequate Cohort")
    assert result.degraded is False
    # Sharpe 2.5 strictly above all peers (max 1.9) → 100th percentile
    sharpe_ranking = next(r for r in result.rankings if r.metric_name == "sharpe_1y")
    assert sharpe_ranking.percentile is not None
    assert sharpe_ranking.percentile == 100.0


def test_zero_peers_returns_degraded_unchanged() -> None:
    """N=0 path preserved (was the only pre-fix guard)."""
    fund = _mk_peer(1.5)
    result = compute_peer_rankings(fund, [], strategy_label="Empty")
    assert result.peer_count == 0
    # Pre-fix code returned no degraded flag; post-fix the new `< MIN_PEER_COHORT_SIZE`
    # guard catches N=0 too and surfaces degraded.
    assert result.degraded is True


# ── F10 end-to-end via compute_peer_rankings ───────────────────────────


def test_all_tied_cohort_via_compute_peer_rankings_ranks_at_median() -> None:
    """End-to-end: cohort all tied at sharpe=1.0 → fund at 50, not 100."""
    fund = _mk_peer(1.0)
    peers = [_mk_peer(1.0) for _ in range(MIN_PEER_COHORT_SIZE)]
    result = compute_peer_rankings(fund, peers, strategy_label="All Tied")
    sharpe_ranking = next(r for r in result.rankings if r.metric_name == "sharpe_1y")
    assert sharpe_ranking.percentile == pytest.approx(50.0, abs=0.5)
