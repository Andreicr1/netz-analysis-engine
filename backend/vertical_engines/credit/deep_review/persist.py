"""Deep Review V4 — persistence helpers.

Self-contained helpers used by the Stage 13 persist logic in service.py.
Extracted during Phase 3 sync/async deduplication — single source of truth
for profile metadata, ORM artifact construction, and return dict building.

All helpers are sync (CPU-bound dict manipulation / DB writes).
Async callers wrap persist_review_artifacts() with asyncio.to_thread().
"""
from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ai_engine.governance.output_safety import sanitize_llm_text
from app.domains.credit.modules.ai.models import (
    DealICBrief,
    DealIntelligenceProfile,
    DealRiskFlag,
)
from vertical_engines.credit.deep_review.helpers import (
    _title_case_strategy,
    _trunc,
)

if TYPE_CHECKING:
    from app.services.storage_client import StorageClient

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════════════════
# Existing helpers (unchanged)
# ═══════════════════════════════════════════════════════════════════════════


def _index_chapter_citations(
    chapters: list[dict[str, Any]],
    citations: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group flat memo citations by chapter tag for eval consumers."""
    by_number: dict[int, str] = {}
    for ch in chapters:
        chapter_number = ch.get("chapter_number")
        chapter_tag = ch.get("chapter_tag")
        if chapter_number is None or not chapter_tag:
            continue
        try:
            by_number[int(chapter_number)] = str(chapter_tag)
        except (TypeError, ValueError):
            continue
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in citations or []:
        citation = dict(raw or {})
        chapter_tag = str(citation.get("chapter_tag") or "").strip()
        if not chapter_tag:
            chapter_number = citation.get("chapter_number")
            if isinstance(chapter_number, int):
                chapter_tag = by_number.get(chapter_number, "")
        if not chapter_tag:
            continue
        citation["chapter_tag"] = chapter_tag
        grouped.setdefault(chapter_tag, []).append(citation)
    return grouped


def _build_tone_artifacts(
    *,
    pre_tone_chapters: dict[str, str],
    post_tone_chapters: dict[str, str],
    tone_review_log: list[Any],
    tone_pass1_changes: dict[str, Any],
    tone_pass2_changes: list[Any],
    signal_original: str,
    signal_final: str,
) -> dict[str, Any]:
    """Persist only changed chapter snapshots to keep the audit payload compact."""
    changed_chapters = sorted(
        chapter_tag
        for chapter_tag in set(pre_tone_chapters) | set(post_tone_chapters)
        if (pre_tone_chapters.get(chapter_tag) or "") != (post_tone_chapters.get(chapter_tag) or "")
    )
    return {
        "signal_original": signal_original,
        "signal_final": signal_final,
        "changed_chapters": changed_chapters,
        "pre_tone_snapshots": {
            chapter_tag: pre_tone_chapters.get(chapter_tag, "")
            for chapter_tag in changed_chapters
        },
        "post_tone_snapshots": {
            chapter_tag: post_tone_chapters.get(chapter_tag, "")
            for chapter_tag in changed_chapters
        },
        "pass1_changes": tone_pass1_changes,
        "pass2_changes": tone_pass2_changes,
        "review_log": tone_review_log,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Phase 3 extracted helpers — sync/async dedup
# ═══════════════════════════════════════════════════════════════════════════


def build_profile_metadata(
    *,
    evidence_map: dict[str, Any],
    quant_dict: dict[str, Any],
    concentration_dict: dict[str, Any],
    macro_snapshot: dict[str, Any] | None,
    macro_stress_flag: bool,
    critic_dict: dict[str, Any],
    policy_dict: dict[str, Any],
    decision_anchor: dict[str, Any],
    confidence_score: int,
    confidence_level: str,
    confidence_breakdown: dict[str, Any],
    confidence_caps: list[str],
    final_confidence: float,
    evidence_confidence: str,
    ic_gate: str,
    ic_gate_reasons: list[str],
    instrument_type: str,
    token_summary: dict[str, Any],
    chapter_citations: dict[str, Any],
    tone_artifacts: dict[str, Any],
    tone_signal_original: str,
    tone_signal_final: str,
) -> dict[str, Any]:
    """Build the metadata dict for DealIntelligenceProfile.metadata_json.

    Single source of truth — called by both sync and async pipelines.
    """
    return {
        "evidence_map": evidence_map,
        "quant_profile": quant_dict,
        "sensitivity_matrix": quant_dict.get("sensitivity_matrix", []),
        "concentration_profile": concentration_dict,
        "macro_snapshot": macro_snapshot,
        "macro_stress_flag": macro_stress_flag,
        "critic_output": critic_dict,
        "policy_compliance": policy_dict,
        "decision_anchor": decision_anchor,
        "confidence_score": confidence_score,
        "confidence_level": confidence_level,
        "confidence_breakdown": confidence_breakdown,
        "confidence_caps_applied": confidence_caps,
        "legacy_confidence_score": final_confidence,
        "evidence_confidence": evidence_confidence,
        "ic_gate": ic_gate,
        "ic_gate_reasons": ic_gate_reasons,
        "instrument_type": instrument_type,
        "pipeline_version": "v4",
        "token_budget": token_summary,
        "chapter_citations": chapter_citations,
        "tone_artifacts": tone_artifacts,
        "tone_signal_original": tone_signal_original,
        "tone_signal_final": tone_signal_final,
    }


def persist_review_artifacts(
    db: Session,
    *,
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    analysis: dict[str, Any],
    chapter_texts: dict[str, str],
    deal_fields: dict[str, Any],
    profile_metadata: dict[str, Any],
    im_recommendation: str | None,
    decision_anchor: dict[str, Any],
    actor_id: str,
    deal_folder_path: str,
    now: dt.datetime,
) -> None:
    """Persist DealIntelligenceProfile + DealICBrief + DealRiskFlag.

    Both sync and async callers pass their db session directly.
    The async path ensures all to_thread tasks have completed before
    calling this function, so the session is exclusively owned.

    All LLM-sourced string fields sanitized via sanitize_llm_text() before DB write.
    """
    # Function-level import to avoid circular dependency (underwriting package)
    from vertical_engines.credit.underwriting import derive_risk_band as _derive_risk_band

    risk_band = _derive_risk_band(analysis)
    risk_band_label = {"HIGH": "HIGH", "MEDIUM": "MODERATE", "LOW": "LOW"}.get(
        risk_band, risk_band,
    )

    returns = analysis.get("expectedReturns", {})
    risks = analysis.get("riskFactors", [])
    if not isinstance(risks, list):
        risks = []

    # ── Build DealIntelligenceProfile ──────────────────────────────
    profile = DealIntelligenceProfile(
        fund_id=fund_id,
        deal_id=deal_id,
        strategy_type=sanitize_llm_text(
            _title_case_strategy(
                _trunc(
                    analysis.get("strategyType")
                    or deal_fields.get("strategy_type")
                    or "Private Credit",
                    80,
                ),
            ),
            strip_all_html=True, max_length=80,
        ),
        geography=sanitize_llm_text(
            _trunc(analysis.get("geography") or deal_fields.get("geography"), 120),
            strip_all_html=True, max_length=120,
        ),
        sector_focus=sanitize_llm_text(
            _trunc(analysis.get("sectorFocus"), 160),
            strip_all_html=True, max_length=160,
        ),
        target_return=_trunc(
            returns.get("targetIRR") or returns.get("couponRate"), 60,
        ),
        risk_band=_trunc(risk_band_label, 20),
        liquidity_profile=sanitize_llm_text(
            _trunc(analysis.get("liquidityProfile"), 80),
            strip_all_html=True, max_length=80,
        ),
        capital_structure_type=sanitize_llm_text(
            _trunc(analysis.get("capitalStructurePosition"), 80),
            strip_all_html=True, max_length=80,
        ),
        key_risks=[
            {
                "riskType": r.get("factor", ""),
                "severity": r.get("severity", "LOW"),
                "mitigation": sanitize_llm_text(
                    r.get("mitigation", ""),
                    strip_all_html=True, max_length=500,
                ) or "",
            }
            for r in risks
            if isinstance(r, dict)
        ],
        differentiators=[
            sanitize_llm_text(d, strip_all_html=True, max_length=500) or ""
            for d in (analysis.get("keyDifferentiators") or [])
            if isinstance(d, str)
        ],
        summary_ic_ready=sanitize_llm_text(
            analysis.get("executiveSummary", "AI review pending."),
        ),
        last_ai_refresh=now,
        metadata_json=profile_metadata,
        created_by=actor_id,
        updated_by=actor_id,
    )

    # ── Build DealICBrief ─────────────────────────────────────────
    exec_summary = chapter_texts.get(
        "ch01_executive_summary", analysis.get("executiveSummary", ""),
    )
    opp_overview = chapter_texts.get(
        "ch02_opportunity", analysis.get("opportunityOverview", ""),
    )
    return_profile = chapter_texts.get(
        "ch08_returns", analysis.get("returnProfile", ""),
    )
    downside_case = chapter_texts.get(
        "ch09_downside", analysis.get("downsideCase", ""),
    )
    risk_summary = chapter_texts.get("ch10_risk", analysis.get("riskSummary", ""))
    peer_compare = chapter_texts.get("ch12_peers", analysis.get("peerComparison", ""))
    rec_signal = _trunc(
        (
            im_recommendation or decision_anchor.get("finalDecision", "CONDITIONAL")
        ).upper(),
        20,
    )

    brief = DealICBrief(
        fund_id=fund_id,
        deal_id=deal_id,
        executive_summary=sanitize_llm_text(exec_summary) or "See IC Memorandum.",
        opportunity_overview=sanitize_llm_text(opp_overview) or "See IC Memorandum.",
        return_profile=sanitize_llm_text(return_profile) or "See IC Memorandum.",
        downside_case=sanitize_llm_text(downside_case) or "See IC Memorandum.",
        risk_summary=sanitize_llm_text(risk_summary) or "See IC Memorandum.",
        comparison_peer_funds=sanitize_llm_text(peer_compare) or "See IC Memorandum.",
        recommendation_signal=rec_signal,
        created_by=actor_id,
        updated_by=actor_id,
    )

    # ── Build DealRiskFlags ───────────────────────────────────────
    risk_flags = [
        DealRiskFlag(
            fund_id=fund_id,
            deal_id=deal_id,
            risk_type=_trunc(risk.get("factor", "UNKNOWN"), 40),
            severity=_trunc(risk.get("severity", "LOW"), 20),
            reasoning=sanitize_llm_text(
                f"{risk.get('factor', '')}: "
                f"{risk.get('mitigation', 'No mitigation identified.')}",
                strip_all_html=True,
            ),
            source_document=_trunc(deal_folder_path, 800),
            created_by=actor_id,
            updated_by=actor_id,
        )
        for risk in risks
        if isinstance(risk, dict)
    ]

    # ── Atomic persist ────────────────────────────────────────────
    with db.begin_nested():
        db.execute(
            delete(DealIntelligenceProfile).where(
                DealIntelligenceProfile.fund_id == fund_id,
                DealIntelligenceProfile.deal_id == deal_id,
            ),
        )
        db.execute(
            delete(DealRiskFlag).where(
                DealRiskFlag.fund_id == fund_id,
                DealRiskFlag.deal_id == deal_id,
            ),
        )
        db.execute(
            delete(DealICBrief).where(
                DealICBrief.fund_id == fund_id,
                DealICBrief.deal_id == deal_id,
            ),
        )
        db.flush()
        db.add(profile)
        db.add_all(risk_flags)
        db.add(brief)

    logger.info(
        "deep_review.v4.profile_brief.persisted",
        deal_id=str(deal_id),
        strategy=profile.strategy_type,
        risk_band=risk_band_label,
        signal=rec_signal,
        flags=len(risk_flags),
    )


def build_return_dict(
    *,
    deal_id: str,
    deal_name: str,
    version_tag: str,
    evidence_pack_id: str,
    evidence_pack_tokens: int,
    chapters: list[dict[str, Any]],
    critic_dict: dict[str, Any],
    critic_dict_default: dict[str, Any],
    critic_escalated: bool,
    full_mode: bool,
    final_confidence: float,
    evidence_confidence: str,
    confidence_score: int,
    confidence_level: str,
    confidence_breakdown: dict[str, Any],
    confidence_caps: list[str],
    ic_gate: str,
    ic_gate_reasons: list[str],
    instrument_type: str,
    quant_dict: dict[str, Any],
    concentration_dict: dict[str, Any],
    policy_dict: dict[str, Any],
    sponsor_output: dict[str, Any],
    macro_stress_flag: bool,
    kyc_results: dict[str, Any],
    decision_anchor: dict[str, Any],
    token_summary: dict[str, Any],
    citations_used: list[dict[str, Any]],
    unsupported_claims_detected: bool,
    tone_review_log: list[Any],
    tone_pass1_changes: dict[str, Any],
    tone_pass2_changes: list[Any],
    tone_signal_original: str,
    tone_signal_final: str,
    full_memo_text: str,
    now: dt.datetime,
) -> dict[str, Any]:
    """Build the canonical deep review return dict.

    Single source of truth — called by both sync and async pipelines.
    """
    return {
        "dealId": deal_id,
        "dealName": deal_name,
        "pipelineVersion": "v4",
        "versionTag": version_tag,
        "evidencePackId": evidence_pack_id,
        "evidencePackTokens": evidence_pack_tokens,
        "chaptersCompleted": len(chapters),
        "chaptersTotal": 13,
        "chapters": [
            {
                "chapter_number": ch["chapter_number"],
                "chapter_tag": ch["chapter_tag"],
                "chapter_title": ch["chapter_title"],
            }
            for ch in chapters
        ],
        "criticConfidence": critic_dict.get("confidence_score"),
        "criticDefaultConfidence": critic_dict_default.get("confidence_score"),
        "criticFatalFlaws": len(critic_dict.get("fatal_flaws", [])),
        "criticRewriteRequired": critic_dict.get("rewrite_required", False),
        "criticEscalated": critic_escalated,
        "fullMode": full_mode,
        "finalConfidence": final_confidence,
        "evidenceConfidence": evidence_confidence,
        "confidenceScore": confidence_score,
        "confidenceLevel": confidence_level,
        "confidenceBreakdown": confidence_breakdown,
        "confidenceCapsApplied": confidence_caps,
        "icGate": ic_gate,
        "icGateReasons": ic_gate_reasons,
        "instrumentType": instrument_type,
        "quantStatus": quant_dict.get("metrics_status"),
        "concentrationBreached": concentration_dict.get("any_limit_breached", False),
        "policyStatus": policy_dict.get("overall_status"),
        "sponsorFlags": len(sponsor_output.get("governance_red_flags", [])),
        "macroStressFlag": macro_stress_flag,
        "kycScreeningSummary": kyc_results.get("summary", {}),
        "decisionAnchor": decision_anchor,
        "tokenUsage": token_summary,
        "citationGovernance": {
            "citationsUsed": len(citations_used),
            "uniqueChunks": len(
                {
                    c.get("chunk_id")
                    for c in citations_used
                    if c.get("chunk_id") != "NONE"
                },
            ),
            "unsupportedClaimsDetected": unsupported_claims_detected,
            "selfAuditPass": not unsupported_claims_detected,
        },
        "toneReviewLog": tone_review_log,
        "tonePass1Changes": tone_pass1_changes,
        "tonePass2Changes": tone_pass2_changes,
        "toneSignalOriginal": tone_signal_original,
        "toneSignalFinal": tone_signal_final,
        "fullMemo": full_memo_text,
        "asOf": now.isoformat(),
    }


async def write_gold_memo(
    storage_client: StorageClient,
    *,
    organization_id: str,
    memo_id: str,
    result_dict: dict[str, Any],
) -> None:
    """Fire-and-forget write of the review result to the ADLS gold layer.

    Path: gold/{org_id}/credit/memos/{memo_id}.json
    Gated by caller — only called when FEATURE_ADLS_ENABLED is true.
    Failures are logged but never propagate to the caller.
    """
    from ai_engine.pipeline.storage_routing import gold_memo_path

    try:
        path = gold_memo_path(uuid.UUID(organization_id), "credit", memo_id)
        data = json.dumps(result_dict, default=str, ensure_ascii=False).encode("utf-8")
        await storage_client.write(path, data, content_type="application/json")
        logger.info("gold_memo_written", path=path, size_bytes=len(data))
    except Exception:
        logger.warning("gold_memo_write_failed", memo_id=memo_id, exc_info=True)


__all__ = [
    "_index_chapter_citations",
    "_build_tone_artifacts",
    "build_profile_metadata",
    "persist_review_artifacts",
    "build_return_dict",
    "write_gold_memo",
]
