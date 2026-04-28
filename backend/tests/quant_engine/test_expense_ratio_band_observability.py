"""Codex catch #5 — observability for (0.15, 1.0] ambiguous band (PR-Q71)."""

from __future__ import annotations

import pytest
import structlog.testing

from quant_engine.expense_ratio_validator import to_decimal_fraction


def test_input_in_ambiguous_band_emits_warning():
    """0.20 in (0.15, 1.0] band → warning emitted, conversion proceeds."""
    with structlog.testing.capture_logs() as logs:
        result = to_decimal_fraction(0.20)
    assert result == pytest.approx(0.002)  # treated as 0.2% percent
    assert any(
        entry.get("event") == "expense_ratio_ambiguous_percent_or_fraction"
        for entry in logs
    )


def test_input_just_above_threshold_emits_warning():
    """0.16 (just above MAX_REASONABLE_EXPENSE_RATIO) → warning."""
    with structlog.testing.capture_logs() as logs:
        to_decimal_fraction(0.16)
    assert any(
        "ambiguous" in entry.get("event", "").lower()
        for entry in logs
    )


def test_input_at_one_emits_warning():
    """1.0 (boundary of band) → warning."""
    with structlog.testing.capture_logs() as logs:
        to_decimal_fraction(1.0)
    # 1.0 is treated as percent → 0.01 fraction
    assert any(
        "ambiguous" in entry.get("event", "").lower()
        for entry in logs
    )


def test_input_above_one_no_band_warning():
    """1.5 (above ambiguous band, clearly whole percent) → no ambiguity warning."""
    with structlog.testing.capture_logs() as logs:
        to_decimal_fraction(1.5)
    assert not any(
        "expense_ratio_ambiguous" in entry.get("event", "")
        for entry in logs
    )


def test_input_below_threshold_no_warning():
    """0.10 (below MAX_REASONABLE_EXPENSE_RATIO, fraction branch) → no warning."""
    with structlog.testing.capture_logs() as logs:
        to_decimal_fraction(0.10)
    assert not any(
        "expense_ratio_ambiguous" in entry.get("event", "")
        for entry in logs
    )


def test_input_in_band_still_converts_to_percent_per_q57():
    """Conversion behavior post-Q57 unchanged — only observability added."""
    result = to_decimal_fraction(0.5)
    assert result == pytest.approx(0.005)  # N-CEN 0.5% → 0.005 fraction (Q57 behavior)


def test_basis_points_unchanged():
    """bps branch (>100) — no ambiguity warning, normal conversion."""
    result = to_decimal_fraction(150.0)
    assert result == pytest.approx(0.015)  # 150 bps → 1.5%
