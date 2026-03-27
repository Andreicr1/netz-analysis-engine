"""Critic engine service — orchestrator.

Never-raises contract: returns CriticVerdict with status='NOT_ASSESSED'
on failure. Logs with exc_info=True for diagnostics.

Imports all domain modules (sole orchestrator).
"""
from __future__ import annotations

from typing import Any

import structlog

from vertical_engines.credit.critic.macro_checks import run_macro_consistency_checks
from vertical_engines.credit.critic.models import CriticVerdict
from vertical_engines.credit.critic.parser import parse_critic_response
from vertical_engines.credit.critic.prompt_builder import build_critic_input, build_critic_prompt

logger = structlog.get_logger()


def critique_intelligence(
    context: dict[str, Any],
    *,
    call_openai_fn: Any = None,
) -> CriticVerdict:
    """Run adversarial IC critique on the deep review context payload.

    Never raises — returns a NOT_ASSESSED verdict on failure.

    Args:
        context: Dict containing keys:
            - structured_analysis: dict from Stage 2
            - ic_brief: dict from Stage 5
            - full_memo: str from Stage 6
            - quant_profile: dict from ic_quant_engine
            - concentration_profile: dict from concentration_engine
            - policy_compliance: dict from policy analysis
            - deal_fields: dict with deal_name, sponsor_name, etc.
        call_openai_fn: Callable matching _call_openai(system, user, *, max_tokens)
            signature.  Injected from deep_review.py to reuse the centralised
            OpenAI provider.

    Returns:
        CriticVerdict dataclass.

    """
    if call_openai_fn is None:
        logger.error("critic_missing_openai_fn")
        return CriticVerdict(
            confidence_score=0.0,
            overall_assessment="Critic engine requires LLM access (call_openai_fn not provided).",
            rewrite_required=True,
        )

    try:
        return _run_critique(context, call_openai_fn=call_openai_fn)
    except Exception:
        logger.error("critic_stage_failed", exc_info=True)
        return CriticVerdict(
            confidence_score=0.0,
            overall_assessment="NOT_ASSESSED — critic engine encountered an error.",
            rewrite_required=True,
        )


def _run_critique(
    context: dict[str, Any],
    *,
    call_openai_fn: Any,
) -> CriticVerdict:
    """Internal critique logic — may raise."""
    user_content = build_critic_input(context)

    if not user_content.strip():
        logger.warning("critic_empty_input")
        return CriticVerdict(
            confidence_score=0.0,
            overall_assessment="No context provided for critique.",
            rewrite_required=True,
        )

    instrument_type = context.get("instrument_type", "UNKNOWN")
    critic_prompt = build_critic_prompt(instrument_type)
    logger.info(
        "critic_stage_start",
        input_chars=len(user_content),
        instrument_type=instrument_type,
    )

    data = call_openai_fn(critic_prompt, user_content, max_tokens=8000)
    verdict = parse_critic_response(data)

    # ── Deterministic macro-consistency checks (no GPT) ──────────
    macro_flags = run_macro_consistency_checks(context)

    # Merge macro flags into verdict (frozen dataclass — reconstruct)
    if macro_flags:
        verdict = CriticVerdict(
            fatal_flaws=verdict.fatal_flaws,
            material_gaps=verdict.material_gaps,
            optimism_bias=verdict.optimism_bias,
            portfolio_conflicts=verdict.portfolio_conflicts,
            citation_issues=verdict.citation_issues,
            macro_consistency_flags=macro_flags,
            confidence_score=verdict.confidence_score,
            overall_assessment=verdict.overall_assessment,
            rewrite_required=verdict.rewrite_required,
        )

    logger.info(
        "critic_stage_complete",
        fatal_flaws=len(verdict.fatal_flaws),
        material_gaps=len(verdict.material_gaps),
        optimism_bias=len(verdict.optimism_bias),
        macro_consistency_flags=len(verdict.macro_consistency_flags),
        confidence_score=verdict.confidence_score,
        rewrite_required=verdict.rewrite_required,
        total_issues=verdict.total_issues,
    )

    return verdict


def build_critic_packet(structured: dict) -> dict:
    """Build a compressed IC packet for critic consumption.

    Critic must NEVER receive raw documents or full narratives.
    Only structured summaries enter the critic prompt.
    """
    overview = structured.get("deal_overview", {})
    if isinstance(overview, str):
        overview = {"summary": overview[:2000]}

    terms = structured.get("terms_and_covenants", {})
    if isinstance(terms, str):
        terms = {"summary": terms[:2000]}

    risk_map = structured.get("risk_map", {})
    if isinstance(risk_map, str):
        risk_map = {"summary": risk_map[:2000]}

    memo = structured.get("investment_memo", "")
    if isinstance(memo, str) and len(memo) > 2000:
        memo = memo[:2000]

    return {
        "overview": overview,
        "terms": terms,
        "risk_map": risk_map,
        "executive_summary": memo,
    }
