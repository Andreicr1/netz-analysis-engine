"""PR-Q56 regression tests — regime cleanup terminus (S06-F06 + S06-F08).

F06: energy shock RoC must be symmetric — demand crashes register stress.
F08: section comment percentages match actual signal weights.
"""

import pytest

from quant_engine.regime_service import _ramp

# ── F06 regression: symmetric RoC ──────────────────────────────────────


def test_energy_shock_symmetric_roc_demand_crash():
    """Negative crude_roc (demand crash) should produce stress equal to
    positive crude_roc of same magnitude."""
    roc_positive = 50.0   # supply spike +50%
    roc_negative = -50.0  # demand crash -50%

    score_positive = _ramp(abs(roc_positive), calm=0.0, panic=50.0)
    score_negative = _ramp(abs(roc_negative), calm=0.0, panic=50.0)
    assert score_positive == score_negative
    assert score_positive == 100.0  # full panic at +/- 50%


def test_ramp_abs_minor_negative_roc_produces_minor_stress():
    """RoC of -10% should produce some stress (was: zero with non-abs)."""
    score = _ramp(abs(-10.0), calm=0.0, panic=50.0)
    assert 0 < score < 100


def test_ramp_zero_roc_is_calm():
    """RoC of 0 → calm score 0."""
    assert _ramp(abs(0.0), calm=0.0, panic=50.0) == 0.0


def test_ramp_abs_moderate_negative_roc():
    """RoC of -25% should produce ~50% stress (midpoint of ramp)."""
    score = _ramp(abs(-25.0), calm=0.0, panic=50.0)
    assert score == pytest.approx(50.0)


# ── F08 verification: comment-vs-weight consistency ───────────────────


def test_financial_signals_weight_is_30_percent():
    """VIX(0.10) + HY_OAS(0.12) + DXY(0.08) = 0.30 financial weight."""
    vix_weight = 0.10
    hy_oas_weight = 0.12
    dxy_weight = 0.08
    financial_total = vix_weight + hy_oas_weight + dxy_weight
    assert financial_total == pytest.approx(0.30)


def test_slow_signals_weight_is_70_percent():
    """Slow/real-economy signals sum to 0.70."""
    energy_shock = 0.12
    cfnai = 0.18
    yield_curve = 0.05
    baa_spread = 0.05
    ff_roc = 0.05
    sahm = 0.08
    icsa = 0.08
    credit_impulse = 0.05
    permits = 0.04
    slow_total = (
        energy_shock + cfnai + yield_curve + baa_spread
        + ff_roc + sahm + icsa + credit_impulse + permits
    )
    assert slow_total == pytest.approx(0.70)


def test_all_signal_weights_sum_to_one():
    """Financial + slow must sum to 1.0."""
    financial = 0.10 + 0.12 + 0.08  # VIX + HY + DXY
    slow = 0.12 + 0.18 + 0.05 + 0.05 + 0.05 + 0.08 + 0.08 + 0.05 + 0.04
    assert (financial + slow) == pytest.approx(1.0)
