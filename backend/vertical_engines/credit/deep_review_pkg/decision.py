"""Decision anchoring and confidence scoring — single authoritative pipeline decision and IC gate."""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()


def _compute_decision_anchor(
    *,
    hard_check_results: dict[str, Any],
    policy_dict: dict[str, Any],
    critic_dict: dict[str, Any] | None = None,
    concentration_dict: dict[str, Any] | None = None,
    quant_dict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute the pipeline's single authoritative decision.

    This is the ONLY function permitted to set ``finalDecision``.
    All downstream stages (IC Brief, IM Longform, Chapter 13) MUST
    reflect this decision -- they explain and justify, never re-adjudicate.

    ``critic_dict`` may be ``None`` when computing a *pre-critic* anchor
    (V3 pipeline: critic runs after brief/longform).  In that case the
    decision is based only on hard checks, policy, concentration and
    quant completeness.  The anchor is recomputed with the full critic
    output after Stage 8.

    Decision hierarchy (first match wins):
      1. Hard policy breach -> PASS
      2. >= 2 confirmed fatal flaws -> PASS
      3. 1 confirmed fatal flaw -> CONDITIONAL
      4. Concentration board override required -> CONDITIONAL
      5. Policy NON_COMPLIANT or CONDITIONAL -> CONDITIONAL
      6. Insufficient quant data -> CONDITIONAL
      7. Otherwise -> INVEST

    Returns:
        dict with keys: finalDecision, decisionRationale,
        policyStatus, confirmedFatalFlaws, hardBreaches, icGate.

    """

    _critic = critic_dict or {}
    _concentration = concentration_dict or {}

    # -- 1. Hard policy breaches --
    hard_breaches = hard_check_results.get("hard_limit_breaches", [])

    # -- 2. Confirmed fatal flaws from critic --
    raw_flaws = _critic.get("fatal_flaws", [])
    confirmed_flaws = [
        f
        for f in raw_flaws
        if f.get("confirmed", True)  # default True for legacy dicts
    ]

    # -- 3. Concentration --
    conc_board_override = bool(
        _concentration.get("requires_board_override", False),
    )
    conc_any_breach = bool(
        _concentration.get("any_limit_breached", False),
    )

    # -- 4. Policy status --
    policy_status = policy_dict.get("overall_status", "NOT_ASSESSED")

    # -- 5. Quant completeness --
    quant_status = (quant_dict or {}).get("metrics_status", "INSUFFICIENT_DATA")

    # -- Decision logic (deterministic, no LLM) --
    rationale_parts: list[str] = []

    if hard_breaches:
        decision = "PASS"
        breach_labels = ", ".join(b.get("limit", "?") for b in hard_breaches[:5])
        rationale_parts.append(
            f"Hard policy breach(es): {breach_labels}",
        )
    elif len(confirmed_flaws) >= 2:
        decision = "PASS"
        flaw_labels = ", ".join(
            (f.get("flaw") or f.get("description") or "unnamed")[:60]
            for f in confirmed_flaws[:5]
        )
        rationale_parts.append(
            f"{len(confirmed_flaws)} confirmed fatal flaw(s): {flaw_labels}",
        )
    elif confirmed_flaws:
        decision = "CONDITIONAL"
        rationale_parts.append(
            f"1 confirmed fatal flaw: "
            f"{(confirmed_flaws[0].get('flaw') or confirmed_flaws[0].get('description') or 'unnamed')[:80]}",
        )
    elif conc_board_override:
        decision = "CONDITIONAL"
        rationale_parts.append("Concentration requires board override.")
    elif policy_status in ("NON_COMPLIANT", "CONDITIONAL"):
        decision = "CONDITIONAL"
        rationale_parts.append(f"Policy compliance: {policy_status}.")
    elif quant_status == "INSUFFICIENT_DATA":
        decision = "CONDITIONAL"
        rationale_parts.append("Insufficient quantitative data for full underwriting.")
    else:
        decision = "INVEST"
        rationale_parts.append("No hard breaches, no confirmed fatal flaws.")

    # Secondary notes (appended, don't change decision)
    if conc_any_breach and decision != "PASS":
        rationale_parts.append("Concentration limit breach noted.")
    if _critic.get("rewrite_required", False):
        rationale_parts.append("Critic flagged rewrite required.")

    # -- IC Gate (mirrors _compute_confidence_score layer 2) --
    if decision == "PASS":
        ic_gate = "BLOCKED"
    elif decision == "CONDITIONAL":
        ic_gate = "CONDITIONAL"
    else:
        ic_gate = "CLEAR"

    # -- Diligence gaps (NOT blockers unless stated) --
    raw_gaps = _critic.get("material_gaps", [])
    diligence_gaps = [
        (g.get("gap") or g.get("description") or "unnamed")[:120] for g in raw_gaps[:5]
    ]

    return {
        "finalDecision": decision,
        "decisionRationale": " | ".join(rationale_parts),
        "policyStatus": policy_status,
        "confirmedFatalFlaws": [
            (f.get("flaw") or f.get("description") or "unnamed")[:120]
            for f in confirmed_flaws
        ],
        "hardBreaches": [b.get("limit", "?") for b in hard_breaches],
        "diligenceGaps": diligence_gaps,
        "concentrationOverride": conc_board_override,
        "icGate": ic_gate,
    }


def _compute_confidence_score(
    *,
    quant_dict: dict[str, Any],
    concentration_dict: dict[str, Any],
    policy_dict: dict[str, Any],
    critic_dict: dict[str, Any],
    im_recommendation: str,
) -> dict[str, Any]:
    """Compute a two-layer institutional confidence assessment.

    Returns a dict with four keys:
      - "evidence_confidence": float 0.0-1.0
            "Do we have enough data to underwrite this deal?"
            Driven by quant completeness and critic memo quality.
            Monotonically reduced by fatal flaws and rewrite_required.

      - "ic_gate": str  "CLEAR" | "CONDITIONAL" | "BLOCKED"
            "Can this deal proceed to IC?"
            Deterministic gate based on hard stops: fatal flaws,
            policy hard breaches, concentration board override, rewrite flag.
            Never increases when violations increase.

      - "ic_gate_reasons": list[str]
            Human-readable reasons for the current ic_gate value.
            Empty list when ic_gate == "CLEAR".

      - "final_confidence": float 0.0-1.0
            Composite scalar for backward-compat dashboard display.
            = evidence_confidence, capped by ic_gate ceiling and
              im_recommendation ceiling.
            Monotonic guarantee: more violations -> never higher score.

    Design invariants:
      - fatal_flaws penalise multiplicatively (not additively).
      - rewrite_required hard-caps evidence_confidence at 0.35.
      - board_override hard-caps evidence_confidence at 0.25.
      - im_recommendation caps final_confidence via a ceiling table.
      - quant_quality modulates critic reliability (amplifier, not addend).
      - policy contributes as gate input, not as independent score addend.
    """

    # -- Layer 1: Evidence Confidence --
    # "Do we have enough data to underwrite?"
    # Sources: quant completeness (evidence quality) x critic quality

    critic_conf: float = float(critic_dict.get("confidence_score", 0.5))
    fatal_flaws: list = critic_dict.get("fatal_flaws", [])
    rewrite_required: bool = bool(critic_dict.get("rewrite_required", False))
    n_fatal: int = len(fatal_flaws)

    # Quant completeness: measures evidence quality, not deal quality.
    # A critic operating under poor data is inherently less reliable,
    # so quant_quality amplifies or dampens critic_conf.
    quant_status: str = quant_dict.get("metrics_status", "INSUFFICIENT_DATA")
    quant_quality: float = {
        "COMPLETE": 1.0,
        "PARTIAL": 0.7,
        "INSUFFICIENT_DATA": 0.35,
    }.get(quant_status, 0.35)

    # Critic confidence modulated by data quality:
    # range: critic_conf x 0.60  (quant=0)  ->  critic_conf x 1.00  (quant=1.0)
    # This replaces the old additive sum and makes quant a reliability modulator.
    evidence_raw: float = critic_conf * (0.60 + 0.40 * quant_quality)

    # Fatal flaws: multiplicative penalty -- each flaw degrades evidence quality.
    # 0 flaws -> x1.00  |  1 -> x0.82  |  2 -> x0.64  |  4 -> x0.30 (floor)
    fatal_multiplier: float = max(0.30, 1.0 - n_fatal * 0.18)
    evidence_confidence: float = evidence_raw * fatal_multiplier

    # Hard caps (applied after multiplier):
    if rewrite_required:
        evidence_confidence = min(evidence_confidence, 0.35)

    conc_board_override: bool = bool(
        concentration_dict.get("requires_board_override", False),
    )
    if conc_board_override:
        evidence_confidence = min(evidence_confidence, 0.25)

    evidence_confidence = round(min(1.0, max(0.0, evidence_confidence)), 3)

    # -- Layer 2: IC Gate --
    # "Can this deal go to IC?" -- deterministic, boolean-logic, no floats.
    # BLOCKED     = hard stop; deal cannot proceed without resolution.
    # CONDITIONAL = material issues identified; proceed with named conditions.
    # CLEAR       = no blocking issues found on current evidence.

    conc_any_breach: bool = bool(concentration_dict.get("any_limit_breached", False))
    policy_status: str = policy_dict.get("overall_status", "NOT_ASSESSED")
    hard_breaches: list = policy_dict.get("hard_limit_breaches", [])

    blocked_reasons: list[str] = []

    if n_fatal >= 1:
        blocked_reasons.append(f"{n_fatal} fatal flaw(s) identified by critic")
    if hard_breaches:
        breach_labels = ", ".join(b.get("limit", "?") for b in hard_breaches[:3])
        blocked_reasons.append(
            f"{len(hard_breaches)} hard policy breach(es): {breach_labels}",
        )
    if conc_board_override:
        blocked_reasons.append("concentration requires board override")
    if rewrite_required and n_fatal >= 1:
        # rewrite_required alone (0 fatal flaws) is CONDITIONAL, not BLOCKED
        blocked_reasons.append("memo rewrite required due to fatal flaws")

    conditional_reasons: list[str] = []
    if not blocked_reasons:
        if policy_status == "CONDITIONAL":
            conditional_reasons.append("policy compliance is CONDITIONAL")
        if conc_any_breach and not conc_board_override:
            conditional_reasons.append(
                "concentration limit breach (no board override required)",
            )
        if quant_status == "INSUFFICIENT_DATA":
            conditional_reasons.append("insufficient quantitative data")
        if rewrite_required and n_fatal == 0:
            conditional_reasons.append("memo rewrite was triggered (no fatal flaws)")

    if blocked_reasons:
        ic_gate: str = "BLOCKED"
        ic_gate_reasons: list[str] = blocked_reasons
    elif conditional_reasons:
        ic_gate = "CONDITIONAL"
        ic_gate_reasons = conditional_reasons
    else:
        ic_gate = "CLEAR"
        ic_gate_reasons = []

    # -- Final Confidence (backward-compat scalar) --
    # = evidence_confidence, capped by ic_gate ceiling and recommendation ceiling.
    # Monotonic guarantee: BLOCKED < CONDITIONAL < CLEAR ceilings are strict,
    # so more violations can never produce a higher final_confidence.

    gate_ceiling: dict[str, float] = {
        "BLOCKED": 0.30,
        "CONDITIONAL": 0.65,
        "CLEAR": 1.00,
    }
    rec_ceiling: dict[str, float] = {
        "INVEST": 1.00,
        "CONDITIONAL": 0.70,
        "PASS": 0.35,
    }

    ceiling: float = min(
        gate_ceiling.get(ic_gate, 0.30),
        rec_ceiling.get(im_recommendation, 0.70),
    )
    final_confidence: float = round(min(ceiling, max(0.0, evidence_confidence)), 3)

    return {
        "evidence_confidence": evidence_confidence,
        "ic_gate": ic_gate,
        "ic_gate_reasons": ic_gate_reasons,
        "final_confidence": final_confidence,
    }


__all__ = [
    "_compute_decision_anchor",
    "_compute_confidence_score",
]
