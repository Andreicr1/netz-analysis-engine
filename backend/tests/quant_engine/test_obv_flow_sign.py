"""Regression tests for S07-F02 — OBV flow sign inversion (PR-Q58).

Pre-fix bug: on NAV-down days with outflows, flow_obv increased instead of
decreased (double-negation: obv -= -50 = obv + 50). Distress scenarios were
silently reported as accumulation.
"""

from __future__ import annotations

import pytest

from quant_engine.talib_momentum_service import compute_flow_momentum


def _build_navs(direction: str, n: int = 30) -> list[float]:
    """Synthesize a NAV series with constant direction."""
    if direction == "up":
        return [100.0 + i * 0.5 for i in range(n)]
    if direction == "down":
        return [100.0 - i * 0.5 for i in range(n)]
    raise ValueError(direction)


# -- F02 regression: the canonical defect ----------------------------------------


def test_nav_down_outflow_produces_negative_obv_slope() -> None:
    """NAV-down + sustained outflows -> flow_obv must trend NEGATIVE
    (strong distribution). Pre-fix: trended POSITIVE due to double-negation."""
    navs = _build_navs("down")
    flows = [-50.0] * len(navs)
    score = compute_flow_momentum(navs, flows, period=20)
    assert score < 0, f"Expected negative slope (distribution), got {score}"


def test_nav_down_inflow_produces_negative_obv_slope() -> None:
    """NAV-down + inflows -> price/money disagreement -> flow_obv negative."""
    navs = _build_navs("down")
    flows = [+100.0] * len(navs)
    score = compute_flow_momentum(navs, flows, period=20)
    assert score < 0, f"Expected negative slope (price disagreement), got {score}"


def test_nav_up_inflow_produces_positive_obv_slope() -> None:
    """NAV-up + inflows -> flow_obv positive (clean accumulation)."""
    navs = _build_navs("up")
    flows = [+100.0] * len(navs)
    score = compute_flow_momentum(navs, flows, period=20)
    assert score > 0, f"Expected positive slope (accumulation), got {score}"


def test_nav_up_outflow_produces_negative_obv_slope() -> None:
    """NAV-up + outflows -> selling into strength -> flow_obv negative.

    This case must remain UNCHANGED post-fix (bug was exclusively in the
    NAV-down branch). If abs() were naively applied to both branches this
    test would flip sign -- kept here as a guard against over-fixing."""
    navs = _build_navs("up")
    flows = [-50.0] * len(navs)
    score = compute_flow_momentum(navs, flows, period=20)
    assert score < 0, (
        f"Expected negative slope (selling into strength), got {score}. "
        f"If this regressed, the fix was applied to BOTH branches incorrectly."
    )


# -- Direction matrix sanity (full 2x2) ------------------------------------------


@pytest.mark.parametrize("nav_dir,flow_sign,expected_sign", [
    ("up",   +1, +1),  # accumulation
    ("down", +1, -1),  # price disagrees
    ("up",   -1, -1),  # selling into strength
    ("down", -1, -1),  # F02: distribution (was +1 pre-fix)
])
def test_obv_direction_matrix(
    nav_dir: str, flow_sign: int, expected_sign: int,
) -> None:
    navs = _build_navs(nav_dir)
    flows = [flow_sign * 50.0] * len(navs)
    score = compute_flow_momentum(navs, flows, period=20)
    if expected_sign > 0:
        assert score > 0, f"{nav_dir}+{flow_sign}: expected positive, got {score}"
    else:
        assert score < 0, f"{nav_dir}+{flow_sign}: expected negative, got {score}"


# -- Edge cases unchanged --------------------------------------------------------


def test_zero_flow_produces_zero_slope() -> None:
    navs = _build_navs("up")
    flows = [0.0] * len(navs)
    score = compute_flow_momentum(navs, flows, period=20)
    assert score == pytest.approx(0.0)


def test_short_series_returns_zero() -> None:
    """Single observation returns 0.0 (len < 2 guard)."""
    score = compute_flow_momentum([100.0], [+100.0], period=20)
    assert score == 0.0


def test_nan_in_flows_returns_zero() -> None:
    """NaN propagation guarded -- fallback 0.0."""
    navs = _build_navs("up")
    flows = [+100.0] * (len(navs) - 1) + [float("nan")]
    score = compute_flow_momentum(navs, flows, period=20)
    assert score == 0.0
