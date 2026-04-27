"""Regression tests for S07-F08 — FI duration_adjusted_drawdown bounds.

Pre-fix bug: bounds [-5.0, 0.0] vs decimal-scale dad → all realistic FI
funds collapsed to 96-100 score range, destroying signal of a 25%-weight
component."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from quant_engine.scoring_service import _compute_fi_score


@dataclass
class _FI:
    empirical_duration: float | None = 5.0
    credit_beta: float | None = 1.0
    yield_proxy_12m: float | None = 0.04
    duration_adj_drawdown_1y: float | None = -0.01


def test_severe_drawdown_scores_low() -> None:
    """Severe FI drawdown → low duration_adjusted_drawdown component (≤ 50)."""
    fi = _FI(duration_adj_drawdown_1y=-0.03)  # dad = -0.03
    result = _compute_fi_score(fi, None, 0.005, None)
    score = result.components["duration_adjusted_drawdown"]
    assert score <= 50.0, f"Severe drawdown should score ≤ 50, got {score}"


def test_mild_drawdown_scores_high() -> None:
    """Mild FI drawdown → high duration_adjusted_drawdown component (≥ 70)."""
    fi = _FI(duration_adj_drawdown_1y=-0.003125)  # mild
    result = _compute_fi_score(fi, None, 0.005, None)
    score = result.components["duration_adjusted_drawdown"]
    assert score >= 70.0, f"Mild drawdown should score ≥ 70, got {score}"


def test_zero_drawdown_scores_at_top() -> None:
    """Zero drawdown → top of range (100)."""
    fi = _FI(duration_adj_drawdown_1y=0.0)
    result = _compute_fi_score(fi, None, 0.005, None)
    score = result.components["duration_adjusted_drawdown"]
    assert score == pytest.approx(100.0)


def test_at_or_beyond_lower_bound_clamps_to_zero() -> None:
    """dad at or below -0.05 → clamps to 0."""
    fi = _FI(duration_adj_drawdown_1y=-0.06)  # beyond -0.05
    result = _compute_fi_score(fi, None, 0.005, None)
    score = result.components["duration_adjusted_drawdown"]
    assert score == pytest.approx(0.0)


def test_signal_separation_severe_vs_mild() -> None:
    """The component must distinguish severe from mild (≥ 25-pt gap).
    Pre-fix: all funds compressed to 96-100 (≤ 4-pt gap)."""
    severe = _compute_fi_score(_FI(duration_adj_drawdown_1y=-0.03), None, 0.005, None)
    mild = _compute_fi_score(_FI(duration_adj_drawdown_1y=-0.003125), None, 0.005, None)
    severe_score = severe.components["duration_adjusted_drawdown"]
    mild_score = mild.components["duration_adjusted_drawdown"]
    assert (mild_score - severe_score) >= 25.0, (
        f"Signal separation insufficient: mild={mild_score}, severe={severe_score}, "
        f"gap={mild_score - severe_score}"
    )


def test_composite_score_uses_corrected_bounds() -> None:
    """End-to-end: severe FI fund composite must score below mild FI fund."""
    severe = _compute_fi_score(_FI(duration_adj_drawdown_1y=-0.03), None, 0.005, None)
    mild = _compute_fi_score(_FI(duration_adj_drawdown_1y=-0.003125), None, 0.005, None)
    assert severe.score < mild.score, (
        f"Severe ({severe.score}) should score below mild ({mild.score})"
    )
