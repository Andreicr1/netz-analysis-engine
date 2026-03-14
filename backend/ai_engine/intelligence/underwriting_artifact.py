"""Unified Underwriting Artifact — single IC truth source.

This module implements the persistence and query layer for
``deal_underwriting_artifacts``.  Deep Review V4 is the ONLY
authorised writer.  The Pipeline Engine MUST NOT call any
function in this module.

Risk band derivation rule (deterministic, never LLM-decided):
  • ≥ 1 HIGH severity key risk   → risk_band = HIGH
  • ≥ 2 MEDIUM severity key risks → risk_band = MEDIUM
  • Otherwise                      → risk_band = LOW
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.domains.credit.modules.ai.models import DealUnderwritingArtifact

logger = logging.getLogger(__name__)


# ── Risk Band derivation (deterministic) ──────────────────────────────


def derive_risk_band(analysis: dict[str, Any]) -> str:
    """Derive risk band from structured analysis risk factors.

    Rule:
      • ≥ 1 HIGH → HIGH
      • ≥ 2 MEDIUM → MEDIUM
      • Otherwise → LOW
    """
    risks = analysis.get("riskFactors", [])
    if not isinstance(risks, list):
        risks = []

    high_count = sum(
        1 for r in risks
        if isinstance(r, dict) and (r.get("severity") or "").upper() == "HIGH"
    )
    medium_count = sum(
        1 for r in risks
        if isinstance(r, dict) and (r.get("severity") or "").upper() == "MEDIUM"
    )

    if high_count >= 1:
        return "HIGH"
    if medium_count >= 2:
        return "MEDIUM"
    return "LOW"


# ── Confidence → level mapping ────────────────────────────────────────


def confidence_to_level(score: float) -> str:
    """Map a 0.0–1.0 confidence score to HIGH / MEDIUM / LOW."""
    if score >= 0.70:
        return "HIGH"
    if score >= 0.40:
        return "MEDIUM"
    return "LOW"


# ── Evidence pack hash (SHA-256 over canonical JSON) ──────────────────


def compute_evidence_pack_hash(evidence_pack: dict[str, Any]) -> str:
    """Compute a stable SHA-256 hash of the evidence pack JSON."""
    canonical = json.dumps(evidence_pack, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


# ── Persist underwriting artifact ─────────────────────────────────────


def persist_underwriting_artifact(
    db: Session,
    *,
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    evidence_pack: dict[str, Any],
    evidence_pack_id: uuid.UUID,
    im_recommendation: str,
    final_confidence: float,
    analysis: dict[str, Any],
    critic_dict: dict[str, Any],
    policy_dict: dict[str, Any],
    chapters_completed: int,
    model_version: str,
    generated_at: datetime,
    version_tag: str,
    actor_id: str = "ai-engine",
    # ── NEW: deterministic confidence fields ──
    confidence_score: int | None = None,
    confidence_level: str | None = None,
    confidence_breakdown: dict[str, Any] | None = None,
    confidence_caps: list[str] | None = None,
    # ── Approval-blocking data gaps (critical_gaps from all memo chapters) ──
    critical_gaps: list[dict[str, Any]] | None = None,
) -> DealUnderwritingArtifact:
    """Create a new underwriting artifact and deactivate prior versions.

    This is the ONLY function that may write to ``deal_underwriting_artifacts``.
    It MUST be called exclusively from Deep Review V4 Stage 13.
    """

    # ── Compute derived fields ────────────────────────────────────
    risk_band = derive_risk_band(analysis)
    # Use new deterministic confidence_level when available, fallback to legacy
    if confidence_level is not None:
        _confidence_level = confidence_level
    else:
        _confidence_level = confidence_to_level(final_confidence)
    pack_hash = compute_evidence_pack_hash(evidence_pack)

    # Normalise recommendation
    rec_upper = (im_recommendation or "CONDITIONAL").upper().strip()
    if rec_upper not in ("INVEST", "PASS", "CONDITIONAL"):
        rec_upper = "CONDITIONAL"

    # ── Extract missing documents from evidence pack ──────────────
    missing_docs = evidence_pack.get("missing_documents", [])
    if not isinstance(missing_docs, list):
        missing_docs = []

    # ── Extract critic findings ───────────────────────────────────
    critic_findings = {
        "fatal_flaws": critic_dict.get("fatal_flaws", []),
        "material_gaps": critic_dict.get("material_gaps", []),
        "confidence_score": critic_dict.get("confidence_score"),
        "rewrite_required": critic_dict.get("rewrite_required", False),
    }

    # ── Extract policy breaches ───────────────────────────────────
    policy_breaches = {
        "compliance_status": policy_dict.get("compliance_status")
            or policy_dict.get("overall_status", "NOT_ASSESSED"),
        "hard_limit_breaches": policy_dict.get("hard_limit_breaches", []),
        "violations": policy_dict.get("violations", []),
        "requires_board_override": policy_dict.get("requires_board_override", False),
    }

    # ── Compute version number ────────────────────────────────────
    existing_count = db.execute(
        select(func.count())
        .select_from(DealUnderwritingArtifact)
        .where(
            DealUnderwritingArtifact.fund_id == fund_id,
            DealUnderwritingArtifact.deal_id == deal_id,
        )
    ).scalar_one()
    next_version = existing_count + 1

    # ── Deactivate all prior artifacts for this deal ──────────────
    db.execute(
        update(DealUnderwritingArtifact)
        .where(
            DealUnderwritingArtifact.fund_id == fund_id,
            DealUnderwritingArtifact.deal_id == deal_id,
            DealUnderwritingArtifact.is_active == True,  # noqa: E712
        )
        .values(is_active=False)
    )

    # ── Create new active artifact ────────────────────────────────
    artifact = DealUnderwritingArtifact(
        fund_id=fund_id,
        deal_id=deal_id,
        evidence_pack_hash=pack_hash,
        recommendation=rec_upper,
        confidence_level=_confidence_level,
        risk_band=risk_band,
        missing_documents=missing_docs,
        critic_findings={
            **critic_findings,
            "confidence_score_deterministic": confidence_score,
            "confidence_level_deterministic": confidence_level or _confidence_level,
            "confidence_breakdown": confidence_breakdown or {},
            "confidence_caps_applied": confidence_caps or [],
            "critical_gaps": critical_gaps or [],
        },
        policy_breaches=policy_breaches,
        chapters_completed=chapters_completed,
        model_version=model_version,
        generated_at=generated_at,
        version_number=next_version,
        is_active=True,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(artifact)
    db.flush()

    logger.info(
        "UNDERWRITING_ARTIFACT_CREATED deal_id=%s version=%d recommendation=%s "
        "risk_band=%s confidence=%s confidence_score=%s pack_hash=%.16s",
        deal_id, next_version, rec_upper, risk_band, _confidence_level,
        confidence_score, pack_hash,
    )

    return artifact


# ── Query helpers ─────────────────────────────────────────────────────


def get_active_artifact(
    db: Session,
    *,
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
) -> DealUnderwritingArtifact | None:
    """Return the active underwriting artifact for a deal, or None."""
    return db.execute(
        select(DealUnderwritingArtifact).where(
            DealUnderwritingArtifact.fund_id == fund_id,
            DealUnderwritingArtifact.deal_id == deal_id,
            DealUnderwritingArtifact.is_active == True,  # noqa: E712
        )
    ).scalar_one_or_none()


def get_artifact_history(
    db: Session,
    *,
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
) -> list[DealUnderwritingArtifact]:
    """Return all artifacts for a deal, ordered by version descending."""
    return list(
        db.execute(
            select(DealUnderwritingArtifact)
            .where(
                DealUnderwritingArtifact.fund_id == fund_id,
                DealUnderwritingArtifact.deal_id == deal_id,
            )
            .order_by(DealUnderwritingArtifact.version_number.desc())
        ).scalars().all()
    )
