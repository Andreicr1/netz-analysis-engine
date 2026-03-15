"""Deep review policy compliance — governance checks, decision anchoring, and confidence scoring."""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import TYPE_CHECKING, Any

from ai_engine.prompts import prompt_registry
from vertical_engines.credit.deep_review_helpers import _MODEL, _call_openai, _now_utc  # noqa: F401

if TYPE_CHECKING:
    from ai_engine.governance.policy_loader import PolicyThresholds

logger = logging.getLogger(__name__)


def _get_policy_compliance_system() -> str:
    return prompt_registry.render("services/policy_compliance_system.j2")


def _parse_lockup_to_years(raw_value: Any) -> float | None:
    """Parse free-form lock-up text into years.

    Accepts plain numeric years for legacy payloads and converts
    explicit day/month units when present.
    """
    if raw_value is None:
        return None

    raw_str = str(raw_value).strip().lower()
    if raw_str in ("", "none", "n/a", "pending diligence", "not specified"):
        return None

    match = re.search(r"(\d+(?:\.\d+)?)", raw_str)
    if not match:
        return None

    value = float(match.group(1))
    if any(token in raw_str for token in (" day", " days")):
        return round(value / 365.0, 3)
    if any(token in raw_str for token in (" month", " months", " mo", " mos")):
        return round(value / 12.0, 3)
    return value


def _gather_policy_context(
    fund_id: uuid.UUID,
    deal_name: str,
    deal_folder_path: str | None = None,
) -> str:
    """Retrieve fund-level policy/governance chunks via v5 index RAG.

    Uses AzureSearchChunksClient with doc_type filter scoped to compliance,
    regulatory, and credit policy documents.
    Returns concatenated policy text or empty string if none found.
    """
    from app.services.search_index import AzureSearchChunksClient

    f_id = str(fund_id)
    searcher = AzureSearchChunksClient()

    # Resolve actual fund_id in the index (v5 uses folder-derived names)
    f_id, _, _scope_mode = searcher.resolve_index_scope(
        fund_id=f_id,
        deal_name=deal_name,
        deal_folder_path=deal_folder_path,
    )

    policy_doc_type_filter = (
        "doc_type eq 'regulatory_compliance'"
        " or doc_type eq 'regulatory_qdd'"
        " or doc_type eq 'regulatory_cima'"
        " or doc_type eq 'credit_policy'"
        " or doc_type eq 'fund_policy'"
    )

    queries = [
        f"{deal_name} investment policy compliance governance limits",
        f"{deal_name} AML KYC regulatory requirements",
        f"{deal_name} credit policy underwriting standards concentration limits",
    ]

    policy_hits: dict[str, dict] = {}
    for query in queries:
        try:
            hits = searcher.search_institutional_hybrid(
                query=query,
                fund_id=f_id,
                top=30,
                k=60,
                doc_type_filter=policy_doc_type_filter,
            )
            for hit in hits:
                title = hit.title or hit.blob_name or ""
                dedup_key = f"{title}::{hit.chunk_index or 0}"
                score = hit.reranker_score or hit.score or 0.0
                existing = policy_hits.get(dedup_key)
                if existing is None or score > existing.get("_score", 0.0):
                    policy_hits[dedup_key] = {
                        "content": hit.content_text or "",
                        "doc_type": hit.doc_type or "unknown",
                        "title": title,
                        "_score": score,
                    }
        except Exception:
            logger.warning(
                "Policy RAG query failed fund=%s query='%s'",
                f_id,
                query[:60],
                exc_info=True,
            )

    if not policy_hits:
        logger.info("POLICY_RAG_EMPTY fund=%s — no compliance chunks in v4 index", f_id)
        return ""

    parts: list[str] = []
    total = 0
    budget = 30_000
    for chunk in sorted(policy_hits.values(), key=lambda c: c["_score"], reverse=True):
        content = chunk.get("content", "")
        remaining = budget - total
        if remaining <= 0:
            break
        snippet = content[:remaining]
        header = f"--- POLICY | {chunk.get('doc_type', 'unknown')} | {chunk.get('title', '')} ---"
        parts.append(f"{header}\n{snippet}")
        total += len(snippet)

    logger.info(
        "POLICY_RAG_COMPLETE fund=%s chunks=%d chars=%d", f_id, len(policy_hits), total,
    )
    return "\n\n".join(parts)


def _run_hard_policy_checks(
    *,
    concentration_dict: dict[str, Any],
    analysis: dict[str, Any],
    deal_fields: dict[str, Any],
    policy: PolicyThresholds | None = None,  # noqa: F821
) -> dict[str, Any]:
    """Deterministic hard policy limit checks.  NEVER LLM-decided.

    These checks MUST run before any LLM call.  Hard breaches are
    arithmetic — no subjectivity, no override by model.

    Thresholds are sourced from PolicyThresholds (loaded from Azure AI
    Search indices with auditable default fallbacks).

    Hard limits enforced:
      1. Manager concentration > single_manager_pct → hard_breach
      2. Single investment size > single_investment_pct → hard_breach
      3. Non-USD exposure unhedged → hard_breach
      4. Illiquidity lock-up > max_lockup_years → hard_breach

    Returns:
        {
            "hard_limit_breaches": [...],
            "requires_board_override": bool,
            "has_hard_breaches": bool,
            "policy_source": dict,  # audit trail of threshold sources
        }

    """
    from ai_engine.governance.policy_loader import load_policy_thresholds

    if policy is None:
        policy = load_policy_thresholds()

    manager_limit = policy.single_manager_pct.value
    deal_limit = policy.single_investment_pct.value
    lockup_limit = policy.max_lockup_years.value

    breaches: list[dict[str, Any]] = []

    # ── 1. Manager concentration ─────────────────────────────────
    manager_buckets = concentration_dict.get("manager_buckets", [])
    for bucket in manager_buckets:
        weight = bucket.get("weight_pct", 0.0)
        if weight > manager_limit:
            breaches.append(
                {
                    "limit": "MANAGER_CONCENTRATION",
                    "threshold": manager_limit,
                    "threshold_source": policy.single_manager_pct.source,
                    "observed": weight,
                    "detail": f"Manager '{bucket.get('name', 'Unknown')}' at {weight}% exceeds {manager_limit}% limit",
                    "requires_board_override": True,
                },
            )

    # ── 2. Single investment size ────────────────────────────────
    total_exposure = concentration_dict.get(
        "total_exposure_usd",
    ) or concentration_dict.get("total_nav_usd", 0.0)
    requested_amount = deal_fields.get("requested_amount") or 0.0
    if total_exposure > 0 and requested_amount > 0:
        deal_exposure_pct = round(
            (requested_amount / (total_exposure + requested_amount)) * 100.0, 2,
        )
        if deal_exposure_pct > deal_limit:
            breaches.append(
                {
                    "limit": "SINGLE_INVESTMENT_SIZE",
                    "threshold": deal_limit,
                    "threshold_source": policy.single_investment_pct.source,
                    "observed": deal_exposure_pct,
                    "detail": f"Deal at {deal_exposure_pct}% of portfolio exceeds {deal_limit}% limit",
                    "requires_board_override": True,
                },
            )

    # ── 3. Non-USD exposure unhedged ─────────────────────────────
    currency = (deal_fields.get("currency") or "USD").upper()
    # Check structured analysis for hedge info
    terms = analysis.get("investmentTerms", {})
    collateral_text = (terms.get("collateral") or "").lower()
    security_text = (terms.get("securityPackage") or "").lower()
    is_hedged = any(
        kw in collateral_text or kw in security_text
        for kw in ("hedge", "hedged", "swap", "fx swap", "currency swap")
    )
    if currency != "USD" and not is_hedged:
        breaches.append(
            {
                "limit": "NON_USD_UNHEDGED",
                "threshold": f"USD required or hedged (max {policy.non_usd_unhedged_pct.value}% unhedged)",
                "threshold_source": policy.non_usd_unhedged_pct.source,
                "observed": currency,
                "detail": f"Deal denominated in {currency} with no hedge identified",
                "requires_board_override": True,
            },
        )

    # ── 4. Illiquidity lock-up > max_lockup_years ────────────────
    # Primary source: fundLiquidityTerms.investorLockupYears (structured).
    # Fallback: scan explicit investor-level lock-up language only.
    # NEVER infer lock-up from maturityDate — that is asset maturity.
    lockup_years: float | None = None

    # (a) Try structured field first
    fund_liquidity = analysis.get("fundLiquidityTerms") or {}
    raw_lockup = fund_liquidity.get("investorLockupYears")
    if raw_lockup is not None:
        lockup_years = _parse_lockup_to_years(raw_lockup)

    # (b) Fallback: scan liquidity profile for explicit lock-up language
    if lockup_years is None:
        liquidity_text = (analysis.get("liquidityProfile") or "").lower()
        lockup_match = re.search(
            r"(?:lock[\s-]?up|redemption\s+restriction|withdrawal\s+restriction)"
            r"[^.]{0,60}?(\d+(?:\.\d+)?)\s*(?:year|yr|y)",
            liquidity_text,
        )
        if lockup_match:
            lockup_years = _parse_lockup_to_years(lockup_match.group(0))

    if lockup_years is not None and lockup_years > lockup_limit:
        breaches.append(
            {
                "limit": "ILLIQUIDITY_LOCKUP",
                "threshold": lockup_limit,
                "threshold_source": policy.max_lockup_years.source,
                "observed": lockup_years,
                "detail": f"Lock-up of {lockup_years} years exceeds {lockup_limit}-year limit",
                "requires_board_override": True,
            },
        )

    has_hard_breaches = len(breaches) > 0

    return {
        "hard_limit_breaches": breaches,
        "requires_board_override": has_hard_breaches,
        "has_hard_breaches": has_hard_breaches,
        "policy_source": {
            "single_manager_pct": {
                "value": manager_limit,
                "source": policy.single_manager_pct.source,
            },
            "single_investment_pct": {
                "value": deal_limit,
                "source": policy.single_investment_pct.source,
            },
            "max_lockup_years": {
                "value": lockup_limit,
                "source": policy.max_lockup_years.source,
            },
            "non_usd_unhedged_pct": {
                "value": policy.non_usd_unhedged_pct.value,
                "source": policy.non_usd_unhedged_pct.source,
            },
        },
    }


def _run_policy_compliance(
    corpus: str,
    policy_text: str,
    analysis: dict[str, Any],
    *,
    hard_check_results: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stage 5: Assess deal compliance against fund policy documents.

    Architecture:
      1. Hard limits are checked DETERMINISTICALLY by _run_hard_policy_checks()
         (called before this function).  If hard breaches exist, compliance
         status is NON_COMPLIANT — the LLM is NOT called.
      2. If no hard breaches, the LLM assesses SOFT guidelines only.
      3. The LLM CANNOT override hard breach decisions.

    Returns the unified compliance output contract:
        {
            "hard_limit_breaches": [...],
            "soft_guideline_exceptions": [...],
            "requires_board_override": bool,
            "compliance_status": "COMPLIANT" | "CONDITIONAL" | "NON_COMPLIANT",
            "overall_status": str,  # backward compat alias
            "violations": [...],
            "waivers_required": [...],
            "conditions": [...],
            "summary": str,
        }
    """
    hard_breaches = (hard_check_results or {}).get("hard_limit_breaches", [])
    has_hard_breaches = len(hard_breaches) > 0

    # If hard breaches → NON_COMPLIANT, LLM NOT called
    if has_hard_breaches:
        breach_summary = "; ".join(b["detail"] for b in hard_breaches)
        return {
            "hard_limit_breaches": hard_breaches,
            "soft_guideline_exceptions": [],
            "requires_board_override": True,
            "compliance_status": "NON_COMPLIANT",
            "overall_status": "NON_COMPLIANT",  # backward compat
            "violations": [
                {
                    "policy": b["limit"],
                    "clause": "Hard Limit",
                    "issue": b["detail"],
                    "severity": "BLOCKING",
                }
                for b in hard_breaches
            ],
            "waivers_required": [],
            "conditions": [],
            "summary": f"DETERMINISTIC NON_COMPLIANT: {breach_summary}",
        }

    # No hard breaches — check if policy text is available for soft guideline assessment
    if not policy_text.strip():
        return {
            "hard_limit_breaches": [],
            "soft_guideline_exceptions": [],
            "requires_board_override": False,
            "compliance_status": "COMPLIANT",
            "overall_status": "NOT_ASSESSED",  # backward compat
            "violations": [],
            "waivers_required": [],
            "conditions": [],
            "summary": "No hard limit breaches.  No fund policy documents available for soft guideline check.",
        }

    # LLM soft guideline assessment — hard check results injected as context
    user_content = (
        f"=== HARD LIMIT CHECK RESULTS (DETERMINISTIC — DO NOT OVERRIDE) ===\n"
        f"All hard limits passed.  No hard breaches detected.\n\n"
        f"=== FUND POLICY DOCUMENTS ===\n{policy_text}\n\n"
        f"=== DEAL STRUCTURED ANALYSIS ===\n{json.dumps(analysis, indent=2, default=str)}\n\n"
        f"IMPORTANT: You are assessing SOFT GUIDELINES ONLY.\n"
        f"Hard limits (manager concentration, single deal size, currency, lock-up) "
        f"have already been checked deterministically and passed.\n"
        f"Focus on qualitative policy alignment, strategy fit, and governance guidelines."
    )
    try:
        from vertical_engines.credit import deep_review as _deep_review

        openai_caller = getattr(_deep_review, "_call_openai", _call_openai)
    except Exception:
        openai_caller = _call_openai

    data = openai_caller(_get_policy_compliance_system(), user_content, max_tokens=4000)

    # Extract soft guideline exceptions from LLM response
    llm_violations = data.get("violations", [])
    soft_exceptions = [
        {
            "guideline": v.get("policy", ""),
            "clause": v.get("clause", ""),
            "issue": v.get("issue", ""),
            "severity": v.get("severity", "MINOR"),
        }
        for v in llm_violations
    ]

    # LLM can return COMPLIANT or CONDITIONAL, but NEVER NON_COMPLIANT
    # (only hard checks produce NON_COMPLIANT)
    llm_status = data.get("overall_status", "COMPLIANT")
    if llm_status == "NON_COMPLIANT":
        # LLM cannot override to NON_COMPLIANT — downgrade to CONDITIONAL
        llm_status = "CONDITIONAL"

    compliance_status = (
        llm_status if llm_status in ("COMPLIANT", "CONDITIONAL") else "COMPLIANT"
    )

    return {
        "hard_limit_breaches": [],
        "soft_guideline_exceptions": soft_exceptions,
        "requires_board_override": False,
        "compliance_status": compliance_status,
        "overall_status": compliance_status,  # backward compat
        "violations": llm_violations,
        "waivers_required": data.get("waivers_required", []),
        "conditions": data.get("conditions", []),
        "summary": data.get("summary", "Soft guideline assessment complete."),
    }


# ---------------------------------------------------------------------------
# Decision Anchor — single authoritative pipeline decision
# ---------------------------------------------------------------------------


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
    reflect this decision — they explain and justify, never re-adjudicate.

    ``critic_dict`` may be ``None`` when computing a *pre-critic* anchor
    (V3 pipeline: critic runs after brief/longform).  In that case the
    decision is based only on hard checks, policy, concentration and
    quant completeness.  The anchor is recomputed with the full critic
    output after Stage 8.

    Decision hierarchy (first match wins):
      1. Hard policy breach → PASS
      2. ≥ 2 confirmed fatal flaws → PASS
      3. 1 confirmed fatal flaw → CONDITIONAL
      4. Concentration board override required → CONDITIONAL
      5. Policy NON_COMPLIANT or CONDITIONAL → CONDITIONAL
      6. Insufficient quant data → CONDITIONAL
      7. Otherwise → INVEST

    Returns:
        dict with keys: finalDecision, decisionRationale,
        policyStatus, confirmedFatalFlaws, hardBreaches, icGate.

    """

    _critic = critic_dict or {}
    _concentration = concentration_dict or {}

    # ── 1. Hard policy breaches ──────────────────────────────
    hard_breaches = hard_check_results.get("hard_limit_breaches", [])

    # ── 2. Confirmed fatal flaws from critic ─────────────────
    raw_flaws = _critic.get("fatal_flaws", [])
    confirmed_flaws = [
        f
        for f in raw_flaws
        if f.get("confirmed", True)  # default True for legacy dicts
    ]

    # ── 3. Concentration ─────────────────────────────────────
    conc_board_override = bool(
        _concentration.get("requires_board_override", False),
    )
    conc_any_breach = bool(
        _concentration.get("any_limit_breached", False),
    )

    # ── 4. Policy status ─────────────────────────────────────
    policy_status = policy_dict.get("overall_status", "NOT_ASSESSED")

    # ── 5. Quant completeness ────────────────────────────────
    quant_status = (quant_dict or {}).get("metrics_status", "INSUFFICIENT_DATA")

    # ── Decision logic (deterministic, no LLM) ───────────────
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

    # ── IC Gate (mirrors _compute_confidence_score layer 2) ──
    if decision == "PASS":
        ic_gate = "BLOCKED"
    elif decision == "CONDITIONAL":
        ic_gate = "CONDITIONAL"
    else:
        ic_gate = "CLEAR"

    # ── Diligence gaps (NOT blockers unless stated) ───────────
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
      - "evidence_confidence": float 0.0–1.0
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

      - "final_confidence": float 0.0–1.0
            Composite scalar for backward-compat dashboard display.
            = evidence_confidence, capped by ic_gate ceiling and
              im_recommendation ceiling.
            Monotonic guarantee: more violations → never higher score.

    Design invariants:
      - fatal_flaws penalise multiplicatively (not additively).
      - rewrite_required hard-caps evidence_confidence at 0.35.
      - board_override hard-caps evidence_confidence at 0.25.
      - im_recommendation caps final_confidence via a ceiling table.
      - quant_quality modulates critic reliability (amplifier, not addend).
      - policy contributes as gate input, not as independent score addend.
    """

    # ── Layer 1: Evidence Confidence ─────────────────────────────────────────
    # "Do we have enough data to underwrite?"
    # Sources: quant completeness (evidence quality) × critic quality

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
    # range: critic_conf × 0.60  (quant=0)  →  critic_conf × 1.00  (quant=1.0)
    # This replaces the old additive sum and makes quant a reliability modulator.
    evidence_raw: float = critic_conf * (0.60 + 0.40 * quant_quality)

    # Fatal flaws: multiplicative penalty — each flaw degrades evidence quality.
    # 0 flaws → ×1.00  |  1 → ×0.82  |  2 → ×0.64  |  4 → ×0.30 (floor)
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

    # ── Layer 2: IC Gate ──────────────────────────────────────────────────────
    # "Can this deal go to IC?" — deterministic, boolean-logic, no floats.
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

    # ── Final Confidence (backward-compat scalar) ─────────────────────────────
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
