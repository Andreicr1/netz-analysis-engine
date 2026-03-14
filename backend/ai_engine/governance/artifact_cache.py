"""Artifact Cache Lock - prevent costly re-runs on existing artifacts.

If a versioned artifact (intelligence profile, IM draft, IC brief)
already exists for a given (deal_id, version_tag), return the cached
output instead of burning another $30 on OpenAI calls.

Architecture:
  - ``artifact_exists()`` checks DB for existing current IM draft.
  - ``load_cached_artifact()`` returns a summary dict mimicking normal output.
  - Deep Review calls ``check_and_load_cache()`` at the top to short-circuit.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def artifact_exists(
    db: Session,
    *,
    deal_id: Any,
    version_prefix: str = "v3-",
) -> bool:
    """Return True if a current IM draft with the given version prefix exists."""
    from app.domains.credit.modules.ai.models import InvestmentMemorandumDraft

    row = db.execute(
        select(InvestmentMemorandumDraft.id).where(
            InvestmentMemorandumDraft.deal_id == deal_id,
            InvestmentMemorandumDraft.is_current == True,  # noqa: E712
            InvestmentMemorandumDraft.version_tag.like(f"{version_prefix}%"),
        ).limit(1),
    ).scalar_one_or_none()

    return row is not None


def load_cached_artifact(
    db: Session,
    *,
    deal_id: Any,
    fund_id: Any,
) -> dict[str, Any] | None:
    """Load existing deep review artifacts and return a summary dict.

    Returns None if no cached artifacts exist.
    """
    from app.domains.credit.modules.ai.models import (
        DealICBrief,
        DealIntelligenceProfile,
        InvestmentMemorandumDraft,
    )

    profile = db.execute(
        select(DealIntelligenceProfile).where(
            DealIntelligenceProfile.deal_id == deal_id,
            DealIntelligenceProfile.fund_id == fund_id,
        ),
    ).scalar_one_or_none()

    im_draft = db.execute(
        select(InvestmentMemorandumDraft).where(
            InvestmentMemorandumDraft.deal_id == deal_id,
            InvestmentMemorandumDraft.fund_id == fund_id,
            InvestmentMemorandumDraft.is_current == True,  # noqa: E712
        ),
    ).scalar_one_or_none()

    brief = db.execute(
        select(DealICBrief).where(
            DealICBrief.deal_id == deal_id,
            DealICBrief.fund_id == fund_id,
        ),
    ).scalar_one_or_none()

    if not profile or not im_draft:
        return None

    logger.info(
        "ARTIFACT_CACHE_HIT deal_id=%s version_tag=%s",
        deal_id, im_draft.version_tag,
    )

    metadata = profile.metadata_json or {}

    return {
        "dealId": str(deal_id),
        "dealName": profile.summary_ic_ready[:80] if profile.summary_ic_ready else "",
        "profileCreated": True,
        "riskFlagsCount": len(profile.key_risks) if profile.key_risks else 0,
        "icBriefCreated": brief is not None,
        "imDraftCreated": True,
        "imVersionTag": im_draft.version_tag,
        "quantStatus": metadata.get("quant_profile", {}).get("metrics_status"),
        "concentrationBreached": metadata.get("concentration_profile", {}).get("any_limit_breached", False),
        "boardOverrideRequired": metadata.get("concentration_profile", {}).get("requires_board_override", False),
        "policyStatus": metadata.get("policy_compliance", {}).get("overall_status"),
        "criticFatalFlaws": len(metadata.get("critic_output", {}).get("fatal_flaws", [])),
        "criticConfidence": metadata.get("critic_output", {}).get("confidence_score"),
        "finalConfidence": metadata.get("confidence_score"),
        "rewriteTriggered": metadata.get("rewrite_triggered", False),
        "macroStressFlag": metadata.get("macro_stress_flag", False),
        "pipelineVersion": metadata.get("pipeline_version", "v3"),
        "cachedResult": True,
        "asOf": im_draft.generated_at.isoformat() if im_draft.generated_at else "",
    }


# ═══════════════════════════════════════════════════════════════════
# V4 Cache Helpers — EvidencePack + Chapter-level resume safety
# ═══════════════════════════════════════════════════════════════════

def artifact_exists_v4(
    db: Session,
    *,
    deal_id: Any,
    version_prefix: str = "v4-",
) -> bool:
    """Return True if an EvidencePack with the given version prefix exists."""
    from app.domains.credit.modules.ai.models import MemoEvidencePack

    row = db.execute(
        select(MemoEvidencePack.id).where(
            MemoEvidencePack.deal_id == deal_id,
            MemoEvidencePack.is_current == True,  # noqa: E712
            MemoEvidencePack.version_tag.like(f"{version_prefix}%"),
        ).limit(1),
    ).scalar_one_or_none()

    return row is not None


def load_cached_artifact_v4(
    db: Session,
    *,
    deal_id: Any,
    fund_id: Any,
) -> dict[str, Any] | None:
    """Load existing V4 artifacts (EvidencePack + chapters) and return summary.

    Returns None if no cached V4 artifacts exist.
    """
    from app.domains.credit.modules.ai.models import MemoChapter, MemoEvidencePack

    pack = db.execute(
        select(MemoEvidencePack).where(
            MemoEvidencePack.deal_id == deal_id,
            MemoEvidencePack.fund_id == fund_id,
            MemoEvidencePack.is_current == True,  # noqa: E712
        ).order_by(MemoEvidencePack.generated_at.desc()).limit(1),
    ).scalar_one_or_none()

    if not pack:
        return None

    chapters = db.execute(
        select(MemoChapter).where(
            MemoChapter.evidence_pack_id == pack.id,
            MemoChapter.is_current == True,  # noqa: E712
        ).order_by(MemoChapter.chapter_number),
    ).scalars().all()

    chapter_list = [
        {
            "chapter_number": ch.chapter_number,
            "chapter_tag": ch.chapter_tag,
            "chapter_title": ch.chapter_title,
            "model_version": ch.model_version,
            "token_count_output": ch.token_count_output,
        }
        for ch in chapters
    ]

    logger.info(
        "ARTIFACT_CACHE_HIT_V4 deal_id=%s version_tag=%s chapters=%d",
        deal_id, pack.version_tag, len(chapter_list),
    )

    return {
        "dealId": str(deal_id),
        "evidencePackId": str(pack.id),
        "evidencePackVersion": pack.version_tag,
        "evidencePackTokens": pack.token_count,
        "chaptersCompleted": len(chapter_list),
        "chaptersTotal": 13,
        "chapters": chapter_list,
        "pipelineVersion": "v4",
        "cachedResult": True,
        "asOf": pack.generated_at.isoformat() if pack.generated_at else "",
    }


def chapter_exists(
    db: Session,
    *,
    evidence_pack_id: Any,
    chapter_number: int,
) -> bool:
    """Return True if a specific chapter already exists for this pack."""
    from app.domains.credit.modules.ai.models import MemoChapter

    row = db.execute(
        select(MemoChapter.id).where(
            MemoChapter.evidence_pack_id == evidence_pack_id,
            MemoChapter.chapter_number == chapter_number,
            MemoChapter.is_current == True,  # noqa: E712
        ).limit(1),
    ).scalar_one_or_none()

    return row is not None


def load_cached_chapter(
    db: Session,
    *,
    evidence_pack_id: Any,
    chapter_number: int,
) -> dict[str, Any] | None:
    """Load a cached chapter by pack + number. Returns None if not found.

    Prefers is_current=True rows; falls back to latest by generated_at
    for resilience against partial runs.
    """
    from app.domains.credit.modules.ai.models import MemoChapter

    # Try current first
    ch = db.execute(
        select(MemoChapter).where(
            MemoChapter.evidence_pack_id == evidence_pack_id,
            MemoChapter.chapter_number == chapter_number,
            MemoChapter.is_current == True,  # noqa: E712
        ).limit(1),
    ).scalar_one_or_none()

    # Fallback: latest by generated_at regardless of is_current
    if not ch:
        ch = db.execute(
            select(MemoChapter).where(
                MemoChapter.evidence_pack_id == evidence_pack_id,
                MemoChapter.chapter_number == chapter_number,
            ).order_by(MemoChapter.generated_at.desc()).limit(1),
        ).scalar_one_or_none()

    if not ch:
        return None

    logger.info(
        "CHAPTER_CACHE_HIT pack=%s ch=%d tag=%s",
        evidence_pack_id, chapter_number, ch.chapter_tag,
    )

    return {
        "chapter_number": ch.chapter_number,
        "chapter_tag": ch.chapter_tag,
        "chapter_title": ch.chapter_title,
        "content_md": ch.content_md,
        "model_version": ch.model_version,
        "token_count_input": ch.token_count_input,
        "token_count_output": ch.token_count_output,
        "generated_at": ch.generated_at.isoformat() if ch.generated_at else "",
    }
