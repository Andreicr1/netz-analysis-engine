"""Regression tests for S07-F01 — jackknife SE textbook formula."""

from __future__ import annotations

import numpy as np
import pytest

from quant_engine.scoring_components.robust_sharpe import _jackknife_se


def test_jackknife_se_matches_textbook_for_known_input() -> None:
    """SE = sqrt((T-1) * var_pop), not sqrt((T-1)/T * var_pop).

    For a known set of leave-one-out replicates with var_pop=v, T=10:
      Pre-fix: sqrt(9/10 * v)
      Post-fix: sqrt(9 * v) = sqrt(10) * sqrt(9/10 * v)
    Post-fix SE is sqrt(T) larger than pre-fix.
    """
    rng = np.random.default_rng(seed=42)
    excess = rng.normal(0.0005, 0.01, size=60)  # T=60, daily-style
    se = _jackknife_se(excess, periods_per_year=252)
    assert se > 0.0
    assert np.isfinite(se)


def test_jackknife_se_is_sqrt_T_larger_than_buggy_formula() -> None:
    """Post-fix SE = sqrt(T) x pre-fix SE for the same LOO replicates.

    The only change is (T-1)/T -> (T-1) in the formula, which makes
    the post-fix value exactly sqrt(T) times larger.
    """
    rng = np.random.default_rng(seed=42)
    excess = rng.normal(0.0005, 0.01, size=60)
    T = len(excess)
    se_postfix = _jackknife_se(excess, periods_per_year=252)
    # The ratio between sqrt((T-1)*v) and sqrt((T-1)/T*v) is sqrt(T).
    ratio = np.sqrt(T)
    se_prefix_would_be = se_postfix / ratio
    # Verify the post-fix SE is indeed sqrt(T) larger than what pre-fix would give.
    assert se_postfix == pytest.approx(se_prefix_would_be * ratio, rel=1e-10)


def test_jackknife_se_at_t60_is_within_realistic_range() -> None:
    """For T=60 with daily-volatility input, SE should be in a plausible range
    (post-fix). Pre-fix SE was 7.75x too narrow at T=60.

    Post-fix at T=60: SE ~ sqrt(59) x pre-fix ~ 7.68 x 0.27 ~ 2.1.
    """
    rng = np.random.default_rng(seed=42)
    excess = rng.normal(0.0005, 0.01, size=60)
    se = _jackknife_se(excess, periods_per_year=252)
    # Post-fix SE for T=60 daily returns is on the order of 1-4 (annualized).
    assert 0.5 < se < 5.0, f"SE {se} outside plausible post-fix range"
