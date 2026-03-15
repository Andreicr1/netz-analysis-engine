"""Policy compliance checks — governance RAG, hard limit enforcement, and soft guideline assessment."""

from __future__ import annotations

import json
import re
import uuid
from typing import TYPE_CHECKING, Any

import structlog

from ai_engine.prompts import prompt_registry
from vertical_engines.credit.deep_review_helpers import _MODEL, _call_openai, _now_utc  # noqa: F401

if TYPE_CHECKING:
    from ai_engine.governance.policy_loader import PolicyThresholds

logger = structlog.get_logger()


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
                "Policy RAG query failed",
                fund_id=f_id,
                query=query[:60],
                exc_info=True,
            )

    if not policy_hits:
        logger.info("No compliance chunks in v4 index", event="POLICY_RAG_EMPTY", fund_id=f_id)
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
        "Policy RAG complete",
        event="POLICY_RAG_COMPLETE",
        fund_id=f_id,
        chunks=len(policy_hits),
        chars=total,
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
      1. Manager concentration > single_manager_pct -> hard_breach
      2. Single investment size > single_investment_pct -> hard_breach
      3. Non-USD exposure unhedged -> hard_breach
      4. Illiquidity lock-up > max_lockup_years -> hard_breach

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

    # -- 1. Manager concentration --
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

    # -- 2. Single investment size --
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

    # -- 3. Non-USD exposure unhedged --
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

    # -- 4. Illiquidity lock-up > max_lockup_years --
    # Primary source: fundLiquidityTerms.investorLockupYears (structured).
    # Fallback: scan explicit investor-level lock-up language only.
    # NEVER infer lock-up from maturityDate -- that is asset maturity.
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
         status is NON_COMPLIANT -- the LLM is NOT called.
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

    # If hard breaches -> NON_COMPLIANT, LLM NOT called
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

    # No hard breaches -- check if policy text is available for soft guideline assessment
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

    # LLM soft guideline assessment -- hard check results injected as context
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
    data = _call_openai(_get_policy_compliance_system(), user_content, max_tokens=4000)

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
        # LLM cannot override to NON_COMPLIANT -- downgrade to CONDITIONAL
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


__all__ = [
    "_get_policy_compliance_system",
    "_parse_lockup_to_years",
    "_gather_policy_context",
    "_run_hard_policy_checks",
    "_run_policy_compliance",
]
