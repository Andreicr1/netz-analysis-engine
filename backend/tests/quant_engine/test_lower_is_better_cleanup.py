"""Regression tests for S08-F06 — lower_is_better key cleanup (PR-Q68).

The frozenset previously contained "max_drawdown_pct" but the production
metrics_dict uses key "max_drawdown" (not "max_drawdown_pct"), so the
inversion never fired. The negative-sign convention of max_drawdown values
made the un-inverted behavior accidentally correct. Q68 removes the dead
entry to prevent future regression on a key alignment "fix"."""

from __future__ import annotations

from vertical_engines.wealth.screener.quant_metrics import composite_score


def test_max_drawdown_with_negative_sign_no_inversion_correct() -> None:
    """Production key "max_drawdown" with negative values: best drawdown
    (least negative) ranks at high percentile WITHOUT inversion.

    Pre-fix: lower_is_better contained "max_drawdown_pct" (key mismatch
    meant inversion never fired, and that was correct).
    Post-fix: frozenset doesn't contain max_drawdown_pct OR max_drawdown,
    documenting that the negative-sign convention makes inversion unneeded.
    """
    metrics = {"max_drawdown": -0.05}  # best drawdown (least negative)
    peers = {"max_drawdown": [-0.50, -0.30, -0.20, -0.10, -0.05]}  # negative scale
    weights = {"max_drawdown": 1.0}
    score = composite_score(metrics, peers, weights)
    assert score is not None
    # Best drawdown -0.05 should score at TOP percentile (>= 0.75).
    # If inversion were applied, it would score at BOTTOM (incorrect).
    assert score >= 0.75
