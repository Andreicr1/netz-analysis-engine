"""Knowledge Aggregator — anonymous market intelligence extraction.

Triggered async after every IC memo is generated and stored.
Extracts anonymous signals and writes to ``gold/_global/analysis_patterns/``
via StorageClient.

PRIVACY INVARIANTS (enforced by tests):
  - NEVER extracts: organization_id, deal_id, fund_id, document names,
    company names, manager names, geography, exact numeric values.
  - Only bucketed ranges (LTV, tenor, VIX) and categorical signals.
  - anonymous_hash is SHA256 of (org_id + deal_id + memo_id) — one-way,
    cannot reverse to identify deal or client.

The global knowledge dataset is the competitive moat:
  More clients → more analyses → richer patterns → better calibration.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


# ── Bucketing functions ──────────────────────────────────────────────────────


def _ltv_bucket(ltv: float | None) -> str:
    if ltv is None:
        return "unknown"
    if ltv <= 0.40:
        return "0-40%"
    if ltv <= 0.60:
        return "40-60%"
    if ltv <= 0.70:
        return "60-70%"
    return "70%+"


def _tenor_bucket(tenor_months: float | None) -> str:
    if tenor_months is None:
        return "unknown"
    if tenor_months <= 12:
        return "0-1y"
    if tenor_months <= 36:
        return "1-3y"
    if tenor_months <= 60:
        return "3-5y"
    return "5y+"


def _vix_bucket(vix: float | None) -> str:
    if vix is None:
        return "unknown"
    if vix <= 15:
        return "0-15"
    if vix <= 25:
        return "15-25"
    if vix <= 35:
        return "25-35"
    return "35+"


def _months_to_conversion_bucket(months: float | None) -> str:
    if months is None:
        return "unknown"
    if months <= 3:
        return "0-3"
    if months <= 6:
        return "3-6"
    if months <= 12:
        return "6-12"
    return "12+"


# ── Anonymous hash ───────────────────────────────────────────────────────────


def compute_anonymous_hash(org_id: UUID, deal_id: UUID, memo_id: UUID) -> str:
    """One-way SHA256 hash for outcome linking.  Cannot reverse."""
    raw = f"{org_id}:{deal_id}:{memo_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ── Signal extraction ────────────────────────────────────────────────────────

# Fields that are FORBIDDEN in output signals.
_FORBIDDEN_FIELDS = frozenset({
    "organization_id", "org_id", "deal_id", "fund_id",
    "document_name", "company_name", "manager_name",
    "borrower_name", "sponsor_name", "geography", "address",
})

# Positive allowlist — only these fields may appear in a signal.
_ALLOWED_SIGNAL_FIELDS = frozenset({
    "anonymous_hash", "timestamp", "profile", "recommendation",
    "confidence_score", "chapter_scores", "risk_flags_count",
    "critic_fatal_flaws", "ltv_bucket", "tenor_bucket",
    "structure_type", "regime", "vix_bucket",
})


def extract_anonymous_signal(
    *,
    org_id: UUID,
    deal_id: UUID,
    memo_id: UUID,
    profile: str,
    memo_result: dict[str, Any],
    macro_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract anonymous signal from a completed IC memo.

    Parameters
    ----------
    org_id, deal_id, memo_id
        Identifiers used ONLY for the anonymous hash.  Not stored.
    profile
        Vertical profile name (e.g. "private_credit").
    memo_result
        The complete memo result dict (chapters, scores, recommendation).
    macro_snapshot
        Optional macro data at time of analysis (regime, VIX, etc.).

    Returns
    -------
    dict
        Anonymous signal ready for storage.  Contains NO identifiable data.
    """
    # Extract recommendation
    recommendation = memo_result.get("recommendation", "UNKNOWN")
    if isinstance(recommendation, dict):
        recommendation = recommendation.get("decision", "UNKNOWN")

    # Extract confidence
    confidence_score = memo_result.get("confidence_score")
    if confidence_score is None:
        confidence_score = memo_result.get("underwriting_confidence", {}).get("score")

    # Extract chapter scores
    chapters = memo_result.get("chapters", [])
    chapter_scores = {}
    for ch in chapters:
        if isinstance(ch, dict) and "chapter_tag" in ch:
            score = ch.get("quality_score") or ch.get("score")
            if score is not None:
                chapter_scores[ch["chapter_tag"]] = float(score)

    # Extract risk metrics
    risk_flags_count = len(memo_result.get("risk_flags", []))
    critic = memo_result.get("critic_result", {}) or {}
    critic_fatal_flaws = critic.get("fatal_flaw_count", 0)

    # Extract structure signals (bucketed)
    quant = memo_result.get("quant_profile", {}) or {}
    ltv = quant.get("ltv") or quant.get("loan_to_value")
    tenor = quant.get("tenor_months") or quant.get("maturity_months")
    structure_type = quant.get("structure_type", "unknown")

    # Macro context
    macro = macro_snapshot or {}
    regime = macro.get("regime", "unknown")
    vix = macro.get("vix") or macro.get("vix_close")

    signal = {
        "anonymous_hash": compute_anonymous_hash(org_id, deal_id, memo_id),
        "timestamp": datetime.now(UTC).isoformat(),
        "profile": profile,
        "recommendation": str(recommendation).upper(),
        "confidence_score": float(confidence_score) if confidence_score is not None else None,
        "chapter_scores": chapter_scores,
        "risk_flags_count": risk_flags_count,
        "critic_fatal_flaws": critic_fatal_flaws,
        "ltv_bucket": _ltv_bucket(float(ltv) if ltv is not None else None),
        "tenor_bucket": _tenor_bucket(float(tenor) if tenor is not None else None),
        "structure_type": str(structure_type).lower(),
        "regime": str(regime).upper(),
        "vix_bucket": _vix_bucket(float(vix) if vix is not None else None),
    }

    # Safety: verify no forbidden fields leaked (defense-in-depth)
    for key in _FORBIDDEN_FIELDS:
        if key in signal:
            raise RuntimeError(f"PRIVACY VIOLATION: forbidden field {key!r} in signal")

    # Safety: positive allowlist — reject any unexpected fields
    unexpected = signal.keys() - _ALLOWED_SIGNAL_FIELDS
    if unexpected:
        raise RuntimeError(f"PRIVACY VIOLATION: unexpected fields in signal: {unexpected}")

    return signal


async def aggregate_memo_signal(
    *,
    org_id: UUID,
    deal_id: UUID,
    memo_id: UUID,
    profile: str,
    memo_result: dict[str, Any],
    macro_snapshot: dict[str, Any] | None = None,
) -> str:
    """Extract anonymous signal and write to storage.

    Returns the storage path written.
    """
    from app.services.storage_client import get_storage_client

    signal = extract_anonymous_signal(
        org_id=org_id,
        deal_id=deal_id,
        memo_id=memo_id,
        profile=profile,
        memo_result=memo_result,
        macro_snapshot=macro_snapshot,
    )

    storage = get_storage_client()
    anon_hash = signal["anonymous_hash"]
    path = f"gold/_global/analysis_patterns/{profile}/{anon_hash[:8]}/{anon_hash}.json"

    await storage.write(
        path,
        json.dumps(signal, separators=(",", ":")).encode("utf-8"),
        content_type="application/json",
    )

    logger.info("Aggregated anonymous signal for profile=%s hash=%s…", profile, anon_hash[:12])
    return path
