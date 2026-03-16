"""Layer evaluation engine — pure logic, no I/O.

Evaluates instruments against screening criteria per layer.
Layer 1: Eliminatory (any FAIL = immediate discard).
Layer 2: Mandate fit per allocation block (any FAIL = discard).
Layer 3: Quant scoring (no elimination, returns score 0.0-1.0).
"""

from __future__ import annotations

from typing import Any

from vertical_engines.wealth.screener.models import CriterionResult

# ── Watchlist hysteresis ──────────────────────────────────────────
DEFAULT_HYSTERESIS_BUFFER = 0.05
DEFAULT_PASS_THRESHOLD = 0.60
DEFAULT_WATCHLIST_THRESHOLD = 0.40

# ── Credit rating ordering (higher = better) ─────────────────────
_RATING_ORDER = {
    "AAA": 22, "AA+": 21, "AA": 20, "AA-": 19,
    "A+": 18, "A": 17, "A-": 16,
    "BBB+": 15, "BBB": 14, "BBB-": 13,
    "BB+": 12, "BB": 11, "BB-": 10,
    "B+": 9, "B": 8, "B-": 7,
    "CCC+": 6, "CCC": 5, "CCC-": 4,
    "CC": 3, "C": 2, "D": 1,
}


class LayerEvaluator:
    """Evaluates screening criteria per layer. Pure logic, no I/O."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    def evaluate_layer1(
        self,
        instrument_type: str,
        attributes: dict[str, Any],
        criteria: dict[str, Any],
    ) -> list[CriterionResult]:
        """Eliminatory criteria. Any FAIL = immediate discard."""
        type_criteria = criteria.get(instrument_type, {})
        results: list[CriterionResult] = []

        for criterion, expected in type_criteria.items():
            result = self._evaluate_criterion(
                criterion, expected, attributes, instrument_type, layer=1
            )
            if result is not None:
                results.append(result)

        return results

    def evaluate_layer2(
        self,
        instrument_type: str,
        attributes: dict[str, Any],
        block_id: str | None,
        criteria: dict[str, Any],
    ) -> list[CriterionResult]:
        """Mandate fit per block. Any FAIL = discard."""
        if block_id is None:
            return []

        blocks = criteria.get("blocks", {})
        block_criteria = blocks.get(block_id, {}).get("criteria", {})
        results: list[CriterionResult] = []

        for criterion, expected in block_criteria.items():
            result = self._evaluate_criterion(
                criterion, expected, attributes, instrument_type, layer=2
            )
            if result is not None:
                results.append(result)

        return results

    def _evaluate_criterion(
        self,
        criterion: str,
        expected: Any,
        attributes: dict[str, Any],
        instrument_type: str,
        layer: int,
    ) -> CriterionResult | None:
        """Evaluate a single criterion against attributes."""
        # Credit rating floor (special case — before generic min_ handler)
        if criterion == "min_credit_rating":
            actual_rating = attributes.get("credit_rating_sp", "")
            actual_rank = _RATING_ORDER.get(str(actual_rating), 0)
            expected_rank = _RATING_ORDER.get(str(expected), 0)
            return CriterionResult(
                criterion=criterion,
                expected=str(expected),
                actual=str(actual_rating),
                passed=actual_rank >= expected_rank,
                layer=layer,
            )

        # Min thresholds
        if criterion.startswith("min_"):
            field_name = criterion[4:]  # strip "min_"
            actual = self._get_numeric(attributes, field_name)
            if actual is None:
                return CriterionResult(
                    criterion=criterion,
                    expected=str(expected),
                    actual="N/A",
                    passed=False,
                    layer=layer,
                )
            return CriterionResult(
                criterion=criterion,
                expected=str(expected),
                actual=str(actual),
                passed=actual >= float(expected),
                layer=layer,
            )

        # Max thresholds
        if criterion.startswith("max_"):
            field_name = criterion[4:]  # strip "max_"
            actual = self._get_numeric(attributes, field_name)
            if actual is None:
                return CriterionResult(
                    criterion=criterion,
                    expected=str(expected),
                    actual="N/A",
                    passed=False,
                    layer=layer,
                )
            return CriterionResult(
                criterion=criterion,
                expected=str(expected),
                actual=str(actual),
                passed=actual <= float(expected),
                layer=layer,
            )

        # Allowed lists
        if criterion.startswith("allowed_"):
            field_name = criterion[8:]  # strip "allowed_"
            actual_val = attributes.get(field_name, "")
            if isinstance(expected, list):
                passed = str(actual_val) in [str(e) for e in expected]
            else:
                passed = str(actual_val) == str(expected)
            return CriterionResult(
                criterion=criterion,
                expected=str(expected),
                actual=str(actual_val),
                passed=passed,
                layer=layer,
            )

        # Excluded lists
        if criterion.startswith("excluded_"):
            field_name = criterion[9:]  # strip "excluded_"
            actual_val = attributes.get(field_name, "")
            if isinstance(expected, list) and expected:
                passed = str(actual_val) not in [str(e) for e in expected]
            else:
                passed = True  # empty exclusion list = nothing excluded
            return CriterionResult(
                criterion=criterion,
                expected=f"not in {expected}",
                actual=str(actual_val),
                passed=passed,
                layer=layer,
            )

        # Boolean checks (sanctions_check etc.)
        if isinstance(expected, bool):
            actual_val = attributes.get(criterion, not expected)
            return CriterionResult(
                criterion=criterion,
                expected=str(expected),
                actual=str(actual_val),
                passed=bool(actual_val) == expected,
                layer=layer,
            )

        # Asset class / geography match (exact)
        if criterion in ("asset_class", "geography"):
            actual_val = attributes.get(criterion, "")
            return CriterionResult(
                criterion=criterion,
                expected=str(expected),
                actual=str(actual_val),
                passed=str(actual_val).lower() == str(expected).lower(),
                layer=layer,
            )

        return None

    @staticmethod
    def _get_numeric(attributes: dict[str, Any], field_name: str) -> float | None:
        """Try to extract a numeric value from attributes.

        Handles both direct numeric values and string representations
        (e.g., aum_usd stored as text in JSONB for precision).
        """
        # Try multiple field name patterns
        for key in (field_name, f"{field_name}_usd", f"{field_name}_pct"):
            val = attributes.get(key)
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    continue
        return None


def determine_status(
    score: float | None,
    previous_status: str | None,
    thresholds: dict[str, float] | None = None,
) -> str:
    """Determine screening status with hysteresis to prevent oscillation.

    Args:
        score: Composite score 0.0-1.0 (None = insufficient data).
        previous_status: Previous screening status (None = first screening).
        thresholds: Dict with pass_threshold, watchlist_threshold, hysteresis_buffer.

    Returns:
        'PASS', 'FAIL', or 'WATCHLIST'.
    """
    if score is None:
        return "WATCHLIST"

    thresholds = thresholds or {}
    pass_threshold = thresholds.get("pass_threshold", DEFAULT_PASS_THRESHOLD)
    watchlist_threshold = thresholds.get("watchlist_threshold", DEFAULT_WATCHLIST_THRESHOLD)
    hysteresis = thresholds.get("hysteresis_buffer", DEFAULT_HYSTERESIS_BUFFER)

    if previous_status == "WATCHLIST":
        # Must exceed threshold + buffer to promote
        if score >= pass_threshold + hysteresis:
            return "PASS"
        if score < watchlist_threshold - hysteresis:
            return "FAIL"
        return "WATCHLIST"

    if previous_status == "PASS":
        # Must fall below threshold - buffer to demote
        if score < pass_threshold - hysteresis:
            return "WATCHLIST" if score >= watchlist_threshold else "FAIL"
        return "PASS"

    # First screening or previous FAIL — no hysteresis
    if score >= pass_threshold:
        return "PASS"
    if score >= watchlist_threshold:
        return "WATCHLIST"
    return "FAIL"
