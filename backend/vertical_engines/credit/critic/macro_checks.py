"""Deterministic macro-consistency checks — no LLM call.

Imports only from models.py (leaf dependency).
"""
from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()


def run_macro_consistency_checks(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Rule-based macro sanity flags.  No LLM call.

    Examines macro_snapshot, macro_stress_flag, and deal intelligence
    to surface deterministic inconsistencies an IC reviewer must see.

    Returns a (possibly empty) list of issue dicts with keys:
        type, severity, detail.
    """
    flags: list[dict[str, Any]] = []

    macro = context.get("macro_snapshot") or {}
    stress = context.get("macro_stress_flag", False)

    # Recommendation from memo / IC brief
    memo_rec = ""
    ic_brief = context.get("ic_brief") or {}
    if isinstance(ic_brief, dict):
        memo_rec = (ic_brief.get("recommendation") or "").upper()
    # Fallback — look in structured_analysis
    if not memo_rec:
        analysis = context.get("structured_analysis") or {}
        memo_rec = (analysis.get("recommendation") or "").upper()

    # Target IRR from quant profile
    quant = context.get("quant_profile") or {}
    target_irr_pct: float | None = None
    raw_irr = quant.get("target_irr_pct") or quant.get("base_irr")
    if raw_irr is not None:
        try:
            target_irr_pct = float(raw_irr)
        except (ValueError, TypeError):
            pass

    # ── Rule 1 — Exit Optimism in Stress Regime ──────────────────
    if stress and memo_rec == "STRONG BUY":
        flags.append({
            "type": "MACRO_EXIT_OPTIMISM",
            "severity": "HIGH",
            "detail": (
                "Strong recommendation during macro stress regime requires "
                "explicit refinancing downside justification."
            ),
        })

    # ── Rule 2 — Spread Regime Mismatch ──────────────────────────
    risk_free_10y = macro.get("risk_free_10y")
    if risk_free_10y is not None and target_irr_pct is not None:
        try:
            if float(risk_free_10y) > 4.5 and target_irr_pct < 9.0:
                flags.append({
                    "type": "RETURN_INADEQUATE_FOR_RATE_REGIME",
                    "severity": "HIGH",
                    "detail": (
                        "Target IRR appears insufficient relative to "
                        "current risk-free rate regime."
                    ),
                })
        except (ValueError, TypeError):
            pass

    # ── Rule 3 — Yield Curve Inversion Warning ───────────────────
    yield_curve_2s10s = macro.get("yield_curve_2s10s")
    if yield_curve_2s10s is not None:
        try:
            if float(yield_curve_2s10s) < 0:
                flags.append({
                    "type": "INVERTED_CURVE_REFINANCING_RISK",
                    "severity": "MEDIUM",
                    "detail": (
                        "Yield curve inversion increases refinancing risk; "
                        "exit timing assumptions must be conservative."
                    ),
                })
        except (ValueError, TypeError):
            pass

    if flags:
        logger.info(
            "macro_consistency_flags_raised",
            count=len(flags),
            types=[f["type"] for f in flags],
        )

    return flags
