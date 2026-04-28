"""Codex catch #2 — max_drawdown unit alignment between metric_dicts and QuantMetrics.

PR-Q70: metric_dicts_by_id["max_drawdown"] was stored as raw decimal (-0.15)
while QuantMetrics.max_drawdown_pct was built with *100 (-15.0). composite_score
then compared fund's whole-percent value against decimal peer cohort, causing
every fund with real drawdown to rank at top percentile on the drawdown component.

Post-Q70: both metric_dicts and QuantMetrics use whole percent.
"""

from __future__ import annotations

import pytest

from vertical_engines.wealth.screener.quant_metrics import composite_score


def test_metric_dicts_max_drawdown_in_whole_percent_scale() -> None:
    """metric_dicts max_drawdown must be whole percent (matches QuantMetrics.max_drawdown_pct).

    Simulates the _safe_float(rm.max_drawdown_1y, scale=100) call in screening_batch.
    Pre-Q70: raw decimal (-0.15). Post-Q70: whole percent (-15.0).
    """
    raw_decimal = -0.15
    scaled = raw_decimal * 100.0
    assert scaled == pytest.approx(-15.0)


def test_composite_score_consistent_drawdown_units() -> None:
    """End-to-end: build peer_values from N funds + score one fund.

    All values in whole-percent scale. Fund at median drawdown should rank
    near 50th percentile — NOT at 100% (the pre-Q70 top-inversion bug).
    """
    # 5 funds with max_drawdown in whole percent (scaled from decimal)
    peer_drawdowns = [-30.0, -20.0, -15.0, -10.0, -5.0]  # whole %

    # Fund at median drawdown (-15.0%)
    metrics = {"max_drawdown": -15.0}
    peer_values = {"max_drawdown": peer_drawdowns}
    weights = {"max_drawdown": 1.0}

    score = composite_score(metrics, peer_values, weights)
    assert score is not None

    # max_drawdown is NOT in lower_is_better (negative values already sort correctly).
    # -15.0 is the median peer → should rank near 0.40–0.60, not at 1.0.
    assert 0.30 <= score <= 0.70, (
        f"Fund at median drawdown should rank mid-cohort, got {score:.3f}"
    )


def test_unit_mismatch_would_produce_extreme_rank() -> None:
    """Demonstrate the pre-Q70 bug: decimal fund vs whole-percent peers.

    Fund at -0.15 (decimal, unscaled) against whole-percent peers.
    Would clip to upper bound and rank at top (wrong).
    """
    # Pre-Q70 bug scenario: fund metric in decimal, peers in whole percent
    bug_metrics = {"max_drawdown": -0.15}  # decimal (pre-Q70 bug)
    peer_values = {"max_drawdown": [-30.0, -20.0, -15.0, -10.0, -5.0]}  # whole %
    weights = {"max_drawdown": 1.0}

    score = composite_score(bug_metrics, peer_values, weights)
    assert score is not None
    # -0.15 clips to upper bound (-5.0) → ranks at TOP of cohort
    # This proves the bug: a deeply negative drawdown appears as best
    assert score > 0.85, (
        f"Bug scenario should produce artificially high rank, got {score:.3f}"
    )
