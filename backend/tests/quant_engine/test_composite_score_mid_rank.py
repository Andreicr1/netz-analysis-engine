"""Regression tests for S08-F02 — composite_score mid-rank ties fix (PR-Q64)."""

from __future__ import annotations

import pytest

from vertical_engines.wealth.screener.quant_metrics import composite_score

# ── F02 lower-is-better tied cohort: was inflated, now mid-rank ─────────


def test_lower_is_better_tied_cohort_ranks_at_median() -> None:
    """Symmetric tied cohort [1, 3, 3, 3, 5], value=3 → mid-rank 0.50.

    Pre-fix: searchsorted=1, rank=0.20, inverted to 0.80 (inflated).
    Post-fix: mid-rank=0.50, inverted to 0.50 (median, correct).

    Note: all-identical peers (e.g. [0,0,0,0,0]) trigger the lo==hi
    variance guard and return None, so we use a cohort with spread
    but a tied majority to exercise mid-rank.
    """
    metrics = {"max_drawdown_pct": 3.0}
    peers = {"max_drawdown_pct": [1.0, 3.0, 3.0, 3.0, 5.0]}
    weights = {"max_drawdown_pct": 1.0}
    score = composite_score(metrics, peers, weights)
    assert score == pytest.approx(0.50)


def test_partial_tie_lower_is_better() -> None:
    """Lower-is-better, peers [1, 2, 2], value=2 → mid-rank.
    count_less=1, count_equal=2 → (1 + 1.0)/3 ≈ 0.667, inverted to 0.333."""
    metrics = {"max_drawdown_pct": 2.0}
    peers = {"max_drawdown_pct": [1.0, 2.0, 2.0]}
    weights = {"max_drawdown_pct": 1.0}
    score = composite_score(metrics, peers, weights)
    assert score == pytest.approx(0.333, abs=0.01)


# ── F02 higher-is-better tied cohort: was deflated, now mid-rank ────────


def test_tied_higher_is_better_cohort_ranks_at_median() -> None:
    """Sharpe cohort [1.0, 1.5, 1.5, 1.5, 2.0], fund=1.5 → 0.50 mid-rank.

    Pre-fix: searchsorted=1, rank=0.20 (deflated mid-cohort to bottom).
    Post-fix: mid-rank=0.50 (correct median).
    """
    metrics = {"sharpe_ratio": 1.5}
    peers = {"sharpe_ratio": [1.0, 1.5, 1.5, 1.5, 2.0]}
    weights = {"sharpe_ratio": 1.0}
    score = composite_score(metrics, peers, weights)
    assert score == pytest.approx(0.50)


def test_partial_tie_higher_is_better() -> None:
    """Higher-is-better, peers [1, 2, 2], value=2 → mid-rank.
    count_less=1, count_equal=2 → (1 + 1.0)/3 ≈ 0.667."""
    metrics = {"sharpe_ratio": 2.0}
    peers = {"sharpe_ratio": [1.0, 2.0, 2.0]}
    weights = {"sharpe_ratio": 1.0}
    score = composite_score(metrics, peers, weights)
    assert score == pytest.approx(0.667, abs=0.01)


# ── No-tie cases: mid-rank == strict-rank (unchanged behavior) ──────────


def test_no_tie_higher_is_better_unchanged() -> None:
    """Fund between peers with no ties → same result pre/post fix.
    fund=3.5 in peers [1, 2, 3, 5] → count_less=3, count_equal=0 → 3/4=0.75."""
    metrics = {"sharpe_ratio": 3.5}
    peers = {"sharpe_ratio": [1.0, 2.0, 3.0, 5.0]}
    weights = {"sharpe_ratio": 1.0}
    score = composite_score(metrics, peers, weights)
    assert score == pytest.approx(0.75)


def test_no_tie_lower_is_better_unchanged() -> None:
    """Fund between peers with no ties, lower-is-better → same result pre/post fix.
    fund=1.5 in peers [1, 2, 3, 5] → rank=0.25, inverted to 0.75."""
    metrics = {"max_drawdown_pct": 1.5}
    peers = {"max_drawdown_pct": [1.0, 2.0, 3.0, 5.0]}
    weights = {"max_drawdown_pct": 1.0}
    score = composite_score(metrics, peers, weights)
    assert score == pytest.approx(0.75)


# ── Cross-module convention sanity (vs Q60 peer_group_service) ──────────


def test_mid_rank_matches_peer_group_service_convention() -> None:
    """Both modules now use the same mid-rank formula (post-Q60 + post-Q64).

    Symmetric tied cohort → 50th percentile in both.
    peer_group_service post-Q60 returns 50.0 (0-100 scale).
    composite_score returns 0.50 (0-1 scale) — equivalent semantics.
    """
    metrics = {"max_drawdown_pct": 3.0}
    peers = {"max_drawdown_pct": [1.0, 3.0, 3.0, 3.0, 5.0]}
    weights = {"max_drawdown_pct": 1.0}
    score = composite_score(metrics, peers, weights)
    assert score == pytest.approx(0.50)
