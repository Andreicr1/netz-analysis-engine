"""Regression tests for S07-F03 — expense ratio threshold (PR-Q57).

The defect: `to_decimal_fraction` previously treated any `abs(value) <= 1.0`
as already-a-fraction, silently inverting cheap N-CEN inputs (0.5 meaning 0.5%
became 50% → clamped to 15%).
"""

from __future__ import annotations

import pytest

from quant_engine.expense_ratio_validator import (
    MAX_REASONABLE_EXPENSE_RATIO,
    to_decimal_fraction,
)

# ── F03 regression: the canonical defect ────────────────────────────────


def test_ncen_sub_one_percent_treated_as_percent_not_fraction() -> None:
    """0.5 (N-CEN: 0.5%) → 0.005 fraction, NOT 0.15 clamp from 0.5."""
    assert to_decimal_fraction(0.5) == pytest.approx(0.005)


def test_ncen_quarter_percent_treated_as_percent() -> None:
    """0.25 (N-CEN: 0.25%) → 0.0025 fraction, NOT clamp from 0.25."""
    assert to_decimal_fraction(0.25) == pytest.approx(0.0025)


def test_ncen_threshold_boundary_just_above() -> None:
    """0.16 (just above 0.15) → percent branch → 0.0016."""
    assert to_decimal_fraction(0.16) == pytest.approx(0.0016)


def test_ncen_threshold_boundary_exactly_at_max() -> None:
    """0.15 (exactly at MAX_REASONABLE_EXPENSE_RATIO) → fraction branch → 0.15.

    Decision rationale: the threshold uses STRICT > so 0.15 stays in the
    fraction branch. A true 15% ER quoted as fraction is allowed; quoted as
    whole percent (0.15 meaning 0.15%) it would be misclassified, but the
    audit jury confirmed this band is dominated by XBRL fraction inputs.
    """
    assert to_decimal_fraction(0.15) == pytest.approx(0.15)


# ── Pre-existing behavior (must still work) ─────────────────────────────


def test_xbrl_canonical_fraction_unchanged() -> None:
    """0.0125 (XBRL: 1.25%) → 0.0125 fraction (no scaling)."""
    assert to_decimal_fraction(0.0125) == pytest.approx(0.0125)


def test_xbrl_zero_fee_unchanged() -> None:
    """0.0 → 0.0 fraction."""
    assert to_decimal_fraction(0.0) == 0.0


def test_whole_percent_above_one_unchanged() -> None:
    """1.5 (whole percent: 1.5%) → 0.015 fraction."""
    assert to_decimal_fraction(1.5) == pytest.approx(0.015)


def test_whole_percent_two_percent_unchanged() -> None:
    """2.0 (whole percent: 2.0%) → 0.02 fraction."""
    assert to_decimal_fraction(2.0) == pytest.approx(0.02)


def test_basis_points_above_one_hundred_unchanged() -> None:
    """150 (bps: 1.5%) → 0.015 fraction."""
    assert to_decimal_fraction(150) == pytest.approx(0.015)


def test_basis_points_high_unchanged() -> None:
    """800 (bps: 8.0%) → 0.08 fraction."""
    assert to_decimal_fraction(800) == pytest.approx(0.08)


# ── Sentinel handling unchanged ─────────────────────────────────────────


def test_none_returns_none() -> None:
    assert to_decimal_fraction(None) is None


def test_nan_returns_none() -> None:
    assert to_decimal_fraction(float("nan")) is None


def test_inf_returns_none() -> None:
    assert to_decimal_fraction(float("inf")) is None


def test_non_numeric_returns_none() -> None:
    assert to_decimal_fraction("not a number") is None


def test_empty_string_returns_none() -> None:
    assert to_decimal_fraction("") is None


# ── Clamp behavior unchanged ────────────────────────────────────────────


def test_clamp_above_max_still_works_for_truly_outlier_input() -> None:
    """20.0 (whole percent: 20% — above MAX 15%) → clamped to 0.15."""
    assert to_decimal_fraction(20.0) == MAX_REASONABLE_EXPENSE_RATIO


def test_clamp_below_zero() -> None:
    """Negative input → clamped to 0.0."""
    assert to_decimal_fraction(-0.01) == 0.0


# ── Caller-end regression: fee_efficiency computation ──────────────────


def test_fee_efficiency_for_cheap_etf_post_fix() -> None:
    """Conceptual: 0.5% ER → fraction 0.005 → er_human_pct 0.5 →
    fee_efficiency = max(0, 100 - 0.5*50) = 75.

    This test does NOT import the scoring service (kept loose-coupled);
    it documents the post-fix expected outcome at the consumer end.
    """
    fraction = to_decimal_fraction(0.5)
    assert fraction is not None
    er_human_pct = fraction * 100.0
    fee_efficiency = max(0.0, 100.0 - er_human_pct * 50.0)
    assert fee_efficiency == pytest.approx(75.0)


def test_fee_efficiency_for_typical_fund_unchanged() -> None:
    """Conceptual: 1.5% ER → fraction 0.015 → er_human_pct 1.5 →
    fee_efficiency = max(0, 100 - 1.5*50) = 25. Same pre/post fix."""
    fraction = to_decimal_fraction(1.5)
    assert fraction is not None
    er_human_pct = fraction * 100.0
    fee_efficiency = max(0.0, 100.0 - er_human_pct * 50.0)
    assert fee_efficiency == pytest.approx(25.0)
