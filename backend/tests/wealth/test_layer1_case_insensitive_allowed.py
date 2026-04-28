"""Regression tests for S08-F08 — allowed_* criterion case-insensitive matching."""

from __future__ import annotations

from vertical_engines.wealth.screener.layer_evaluator import LayerEvaluator


def test_allowed_domicile_case_insensitive_lowercase_attribute() -> None:
    """Lowercase domicile attribute ('ie') matches uppercase allowed list ['IE']."""
    evaluator = LayerEvaluator({})
    result = evaluator._evaluate_criterion(
        criterion="allowed_domicile",
        expected=["IE", "LU", "KY"],
        attributes={"domicile": "ie"},
        instrument_type="fund",
        layer=1,
    )
    assert result is not None
    assert result.passed is True


def test_allowed_structure_case_insensitive() -> None:
    """Lowercase structure 'ucits' matches uppercase allowed ['UCITS', 'CIS']."""
    evaluator = LayerEvaluator({})
    result = evaluator._evaluate_criterion(
        criterion="allowed_structure",
        expected=["UCITS", "CIS"],
        attributes={"structure": "ucits"},
        instrument_type="fund",
        layer=1,
    )
    assert result is not None
    assert result.passed is True


def test_allowed_exchange_uppercase_attribute_unchanged() -> None:
    """Uppercase attribute (production canonical) still passes — no regression."""
    evaluator = LayerEvaluator({})
    result = evaluator._evaluate_criterion(
        criterion="allowed_exchange",
        expected=["NYSE", "NASDAQ"],
        attributes={"exchange": "NASDAQ"},
        instrument_type="fund",
        layer=1,
    )
    assert result is not None
    assert result.passed is True


def test_allowed_value_not_in_list_still_fails() -> None:
    """Genuinely-not-allowed value (case-insensitive) still fails."""
    evaluator = LayerEvaluator({})
    result = evaluator._evaluate_criterion(
        criterion="allowed_domicile",
        expected=["IE", "LU"],
        attributes={"domicile": "us"},
        instrument_type="fund",
        layer=1,
    )
    assert result is not None
    assert result.passed is False


def test_allowed_scalar_expected_case_insensitive() -> None:
    """Scalar (non-list) expected value also case-insensitive."""
    evaluator = LayerEvaluator({})
    result = evaluator._evaluate_criterion(
        criterion="allowed_currency",
        expected="USD",
        attributes={"currency": "usd"},
        instrument_type="fund",
        layer=1,
    )
    assert result is not None
    assert result.passed is True
