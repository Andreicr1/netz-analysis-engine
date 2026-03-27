"""Configurable macro stress severity scoring.

Sync service — pure computation, no I/O.
Sub-dimensions provided as config parameter, not via registration.

Config is injected as parameter by callers — no YAML, no @lru_cache.

Grade scale (lowercase, matching existing quant_engine conventions):
  0-15:  none
  16-35: mild
  36-65: moderate
  66+:   severe
"""

from __future__ import annotations

from typing import Any, TypedDict

import structlog

from app.shared.schemas import StressSeverityResult

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
#  Config types
# ---------------------------------------------------------------------------


class StressIndicatorConfig(TypedDict, total=False):
    """Configuration for a single stress indicator check."""

    key: str  # snapshot dict key path (dot-separated for nested)
    severe_threshold: float
    severe_points: int
    elevated_threshold: float
    elevated_points: int
    label: str


class StressDimensionConfig(TypedDict, total=False):
    """Configuration for a named stress sub-dimension."""

    name: str
    indicators: list[StressIndicatorConfig]


class StressSeverityConfig(TypedDict, total=False):
    """Full stress severity configuration."""

    dimensions: list[StressDimensionConfig]
    grade_boundaries: list[tuple[int, str]]


# ---------------------------------------------------------------------------
#  Default credit stress configuration
# ---------------------------------------------------------------------------

_DEFAULT_GRADE_BOUNDARIES: list[tuple[int, str]] = [
    (15, "none"),
    (35, "mild"),
    (65, "moderate"),
    (100, "severe"),
]

# Sub-dimension grading uses tighter boundaries (matches original _grade function)
_DEFAULT_SUBDIM_BOUNDARIES: list[tuple[int, str]] = [
    (0, "none"),
    (9, "mild"),  # matches original credit_stress: score < 10 = MILD, score >= 10 = MODERATE
    (29, "moderate"),
    (100, "severe"),
]

_DEFAULT_CREDIT_DIMENSIONS: list[StressDimensionConfig] = [
    {
        "name": "recession",
        "indicators": [
            {"key": "recession_flag", "severe_threshold": 1.0, "severe_points": 40,
             "elevated_threshold": 1.0, "elevated_points": 40,
             "label": "NBER recession indicator active"},
        ],
    },
    {
        "name": "financial_conditions",
        "indicators": [
            {"key": "financial_conditions_index", "severe_threshold": 1.0, "severe_points": 25,
             "elevated_threshold": 0.0, "elevated_points": 10,
             "label": "NFCI"},
        ],
    },
    {
        "name": "yield_curve",
        "indicators": [
            {"key": "yield_curve_2s10s", "severe_threshold": -0.50, "severe_points": 20,
             "elevated_threshold": 0.0, "elevated_points": 10,
             "label": "Yield curve"},
        ],
    },
    {
        "name": "rate_stress",
        "indicators": [
            {"key": "baa_spread", "severe_threshold": 3.0, "severe_points": 20,
             "elevated_threshold": 2.0, "elevated_points": 8,
             "label": "Baa spread"},
            {"key": "hy_spread_proxy", "severe_threshold": 8.0, "severe_points": 15,
             "elevated_threshold": 5.0, "elevated_points": 5,
             "label": "HY spread"},
        ],
    },
    {
        "name": "real_estate_stress",
        "indicators": [
            {"key": "real_estate_national.CSUSHPINSA.delta_12m_pct",
             "severe_threshold": -5.0, "severe_points": 20,
             "elevated_threshold": 0.0, "elevated_points": 10,
             "label": "National HPI YoY"},
            {"key": "mortgage.DRSFRMACBS.latest",
             "severe_threshold": 4.0, "severe_points": 15,
             "elevated_threshold": 4.0, "elevated_points": 15,
             "label": "Mortgage delinquency"},
        ],
    },
    {
        "name": "credit_stress",
        "indicators": [
            {"key": "credit_quality.DRALACBN.latest",
             "severe_threshold": 2.5, "severe_points": 10,
             "elevated_threshold": 2.5, "elevated_points": 10,
             "label": "Overall loan delinquency"},
        ],
    },
]

_DEFAULT_CONFIG: StressSeverityConfig = {
    "dimensions": _DEFAULT_CREDIT_DIMENSIONS,
    "grade_boundaries": _DEFAULT_GRADE_BOUNDARIES,
}


# ---------------------------------------------------------------------------
#  Config resolution
# ---------------------------------------------------------------------------


def resolve_stress_config(config: dict | None = None) -> StressSeverityConfig:
    """Extract stress severity config from calibration config dict.

    Falls back to hardcoded credit defaults if config is None or malformed.
    """
    if config is None:
        return _DEFAULT_CONFIG
    try:
        raw = config.get("stress_severity", {})
        if not raw:
            return _DEFAULT_CONFIG
        return StressSeverityConfig(
            dimensions=raw.get("dimensions", _DEFAULT_CREDIT_DIMENSIONS),
            grade_boundaries=raw.get("grade_boundaries", _DEFAULT_GRADE_BOUNDARIES),
        )
    except (KeyError, TypeError, ValueError) as e:
        logger.error("Malformed stress severity config, using defaults", error=str(e))
        return _DEFAULT_CONFIG


# ---------------------------------------------------------------------------
#  Core scoring
# ---------------------------------------------------------------------------


def _resolve_nested_key(snapshot: dict[str, Any], key: str) -> Any:
    """Resolve a dot-separated key path in a nested dict.

    Example: "real_estate_national.CSUSHPINSA.delta_12m_pct"
    """
    parts = key.split(".")
    current: Any = snapshot
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _grade_score(score: int, boundaries: list[tuple[int, str]]) -> str:
    """Map numeric score to grade label."""
    for threshold, grade in boundaries:
        if score <= threshold:
            return grade
    return boundaries[-1][1] if boundaries else "severe"


def compute_stress_severity(
    snapshot: dict[str, Any],
    *,
    config: dict | None = None,
) -> StressSeverityResult:
    """Compute graded stress severity from a macro snapshot.

    Fully deterministic — no LLM, no randomness.

    Args:
        snapshot: Macro snapshot dict (from market_data_engine or FRED cache).
        config: Calibration config with stress_severity section.
            Falls back to default credit dimensions if None.

    Returns:
        StressSeverityResult with score, level, triggers, sub_dimensions.

    """
    resolved = resolve_stress_config(config)
    dimensions = resolved.get("dimensions", _DEFAULT_CREDIT_DIMENSIONS)
    boundaries = resolved.get("grade_boundaries", _DEFAULT_GRADE_BOUNDARIES)

    total_score = 0
    all_triggers: list[str] = []
    sub_dimensions: dict[str, str] = {}

    for dim in dimensions:
        dim_name = dim.get("name", "unknown")
        dim_score = 0
        indicators = dim.get("indicators", [])

        for ind in indicators:
            key = ind.get("key", "")
            value = _resolve_nested_key(snapshot, key)

            if value is None:
                continue

            # Handle boolean flags (recession_flag)
            if isinstance(value, bool):
                value = 1.0 if value else 0.0
            try:
                value = float(value)
            except (ValueError, TypeError):
                continue

            severe_thresh = ind.get("severe_threshold", float("inf"))
            elevated_thresh = ind.get("elevated_threshold", float("inf"))
            label = ind.get("label", key)

            # For inverted metrics (yield curve, HPI): "below threshold" = stress
            is_inverted = key in (
                "yield_curve_2s10s",
                "real_estate_national.CSUSHPINSA.delta_12m_pct",
            )

            if is_inverted:
                if value < severe_thresh:
                    pts = ind.get("severe_points", 0)
                    dim_score += pts
                    all_triggers.append(f"{label} severely stressed ({value:.2f} < {severe_thresh})")
                elif value < elevated_thresh:
                    pts = ind.get("elevated_points", 0)
                    dim_score += pts
                    all_triggers.append(f"{label} elevated ({value:.2f})")
            elif value >= severe_thresh:
                pts = ind.get("severe_points", 0)
                dim_score += pts
                all_triggers.append(f"{label} severely stressed ({value:.2f} >= {severe_thresh})")
            elif value > elevated_thresh:
                pts = ind.get("elevated_points", 0)
                dim_score += pts
                all_triggers.append(f"{label} elevated ({value:.2f})")

        total_score += dim_score
        sub_dimensions[dim_name] = _grade_score(dim_score, _DEFAULT_SUBDIM_BOUNDARIES)

    total_score = min(total_score, 100)

    return StressSeverityResult(
        score=float(total_score),
        level=_grade_score(total_score, boundaries),
        triggers=all_triggers,
        sub_dimensions=sub_dimensions,
    )
