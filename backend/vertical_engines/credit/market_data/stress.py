"""Macro stress severity assessment (fully deterministic, no LLM).

Imports only models.py (leaf).
"""
from __future__ import annotations

from typing import Any

import structlog

from vertical_engines.credit.market_data.models import NFCI_STRESS_THRESHOLD

logger = structlog.get_logger()


def compute_macro_stress_severity(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Compute a graded stress assessment from the expanded macro snapshot.

    Returns:
    {
      "level":              "NONE" | "MILD" | "MODERATE" | "SEVERE",
      "score":              int (0-100),
      "triggers":           list[str],
      "real_estate_stress": "NONE" | "MILD" | "MODERATE" | "SEVERE",
      "credit_stress":      "NONE" | "MILD" | "MODERATE" | "SEVERE",
      "rate_stress":        "NONE" | "MILD" | "MODERATE" | "SEVERE",
    }

    Score scale:
      0-15:  NONE
      16-35: MILD
      36-65: MODERATE
      66+:   SEVERE

    Fully deterministic — no LLM, no randomness.

    Note: This function delegates to quant_engine.stress_severity_service
    but converts the result back to the legacy dict format with UPPERCASE
    grade levels for backward compatibility with existing consumers.
    """
    from quant_engine.stress_severity_service import compute_stress_severity

    result = compute_stress_severity(snapshot)

    # Convert to legacy format (UPPERCASE levels for backward compat)
    sub_dims = result.sub_dimensions or {}

    return {
        "level": result.level.upper(),
        "score": int(result.score),
        "triggers": result.triggers,
        "real_estate_stress": (sub_dims.get("real_estate_stress") or "none").upper(),
        "credit_stress": (sub_dims.get("credit_stress") or "none").upper(),
        "rate_stress": (sub_dims.get("rate_stress") or "none").upper(),
    }


def compute_macro_stress_flag(snapshot: dict[str, Any]) -> bool:
    """Legacy API — preserve simple recession/NFCI threshold behavior.

    Backward-compatible wrapper around compute_macro_stress_severity().
    All existing callers that test the bool flag continue to work.
    """
    if snapshot.get("recession_flag") is True:
        return True

    nfci = snapshot.get("financial_conditions_index")
    if nfci is not None and nfci > NFCI_STRESS_THRESHOLD:
        return True

    sev = compute_macro_stress_severity(snapshot)
    return sev["level"] in ("MODERATE", "SEVERE")
