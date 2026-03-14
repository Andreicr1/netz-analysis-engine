"""Deep Review Comparator — institutional delta logic for V3 vs V4.

Computes five structured delta dimensions from the raw V3 and V4
outputs and their persisted artifacts.  All comparisons are deterministic.

Does NOT modify any artifacts.  Read-only.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from ai_engine.validation.validation_schema import (
    DeepReviewDeltaReport,
    EvidenceDensity,
    InternalConsistency,
    RecommendationDivergence,
    RiskFlagCoverageDelta,
    SponsorImpact,
)

logger = logging.getLogger(__name__)

# ── Canonical recommendation labels (normalised for comparison) ──
_REC_LABELS = {"APPROVE", "CONDITIONAL", "REJECT", "DECLINE", "HOLD"}

_SEVERITY_WEIGHTS = {
    "CRITICAL": 1.0,
    "HIGH": 0.8,
    "MEDIUM": 0.5,
    "LOW": 0.2,
}


def _normalise_rec(raw: str | None) -> str:
    """Map a raw recommendation string to a canonical label."""
    if not raw:
        return "UNKNOWN"
    upper = raw.strip().upper()

    # Direct match
    for label in _REC_LABELS:
        if label in upper:
            return label

    # Fuzzy mapping
    if any(w in upper for w in ("PROCEED", "POSITIVE", "SUPPORT")):
        return "APPROVE"
    if any(w in upper for w in ("CONDITIONAL", "SUBJECT TO", "WITH CONDITIONS")):
        return "CONDITIONAL"
    if any(w in upper for w in ("REJECT", "DECLINE", "DO NOT", "NEGATIVE")):
        return "REJECT"
    if any(w in upper for w in ("HOLD", "DEFER", "POSTPONE")):
        return "HOLD"

    return "UNKNOWN"


def _extract_risk_labels(flags: list[dict[str, Any]] | None) -> list[str]:
    """Extract short risk labels from a list of risk flag dicts."""
    if not flags:
        return []
    labels: list[str] = []
    for f in flags:
        label = (
            f.get("risk_type")
            or f.get("riskType")
            or f.get("flag")
            or f.get("reasoning", "")[:60]
        )
        if label:
            labels.append(str(label).strip())
    return labels


def _weighted_severity(flags: list[dict[str, Any]] | None) -> float:
    """Compute a weighted severity score from risk flags."""
    if not flags:
        return 0.0
    total = 0.0
    for f in flags:
        sev = str(f.get("severity", "MEDIUM")).upper()
        total += _SEVERITY_WEIGHTS.get(sev, 0.3)
    return round(total, 2)


# ═══════════════════════════════════════════════════════════════════
#  Main Comparator
# ═══════════════════════════════════════════════════════════════════

def compare_v3_vs_v4(
    v3: dict[str, Any],
    v4: dict[str, Any],
    *,
    v3_risk_flags: list[dict[str, Any]] | None = None,
    v3_im_draft: dict[str, Any] | None = None,
    v4_evidence_pack: dict[str, Any] | None = None,
    v4_chapters: list[dict[str, Any]] | None = None,
) -> DeepReviewDeltaReport:
    """Compute the institutional delta between V3 and V4 outputs.

    Parameters
    ----------
    v3 : dict
        Return dict from ``run_deal_deep_review`` (V3).
    v4 : dict
        Return dict from ``run_deal_deep_review_v4`` (V4).
    v3_risk_flags : list[dict], optional
        Raw DealRiskFlag rows for the deal (V3 run).
    v3_im_draft : dict, optional
        Current InvestmentMemorandumDraft fields (V3).
    v4_evidence_pack : dict, optional
        Frozen evidence pack JSON from MemoEvidencePack row.
    v4_chapters : list[dict], optional
        Chapter rows from MemoChapter (V4).

    Returns
    -------
    DeepReviewDeltaReport

    """
    deal_id = v4.get("dealId") or v3.get("dealId") or ""
    deal_name = v4.get("dealName") or v3.get("dealName")

    return DeepReviewDeltaReport(
        deal_id=str(deal_id),
        deal_name=deal_name,
        recommendation=_compare_recommendation(v3, v4, v3_im_draft, v4_chapters),
        risk_flags=_compare_risk_flags(v3, v4, v3_risk_flags),
        sponsor=_compare_sponsor(v4, v4_evidence_pack),
        evidence=_compare_evidence(v4, v4_evidence_pack, v4_chapters),
        consistency=_compare_consistency(v4, v4_chapters, v4_evidence_pack),
    )


# ═══════════════════════════════════════════════════════════════════
#  A)  Recommendation Divergence
# ═══════════════════════════════════════════════════════════════════

def _compare_recommendation(
    v3: dict[str, Any],
    v4: dict[str, Any],
    v3_im_draft: dict[str, Any] | None,
    v4_chapters: list[dict[str, Any]] | None,
) -> RecommendationDivergence:
    # V3 recommendation from IM draft
    v3_rec_raw = ""
    if v3_im_draft:
        v3_rec_raw = v3_im_draft.get("recommendation", "")
    if not v3_rec_raw:
        v3_rec_raw = v3.get("recommendation", "")

    # V4 recommendation from chapter 13
    v4_rec_raw = ""
    if v4_chapters:
        for ch in v4_chapters:
            if ch.get("chapter_tag") == "ch13_recommendation" or ch.get("chapter_number") == 13:
                content = ch.get("content_md", "")
                # Extract recommendation from content: look for APPROVE/CONDITIONAL/REJECT
                v4_rec_raw = _extract_recommendation_from_chapter(content)
                break

    v3_norm = _normalise_rec(v3_rec_raw)
    v4_norm = _normalise_rec(v4_rec_raw)

    material = v3_norm != v4_norm and v3_norm != "UNKNOWN" and v4_norm != "UNKNOWN"
    direction = f"{v3_norm}→{v4_norm}" if material else None

    return RecommendationDivergence(
        v3_recommendation=v3_norm,
        v4_recommendation=v4_norm,
        material_divergence=material,
        divergence_direction=direction,
    )


def _extract_recommendation_from_chapter(content: str) -> str:
    """Extract a recommendation label from chapter 13 markdown content."""
    if not content:
        return ""
    upper = content.upper()

    # Look for explicit recommendation patterns
    patterns = [
        r"RECOMMEND(?:ATION)?[:\s]+(\w+)",
        r"OVERALL\s+(?:RECOMMENDATION|VERDICT)[:\s]+(\w+)",
        r"IC\s+(?:RECOMMENDATION|VERDICT)[:\s]+(\w+)",
    ]
    for pat in patterns:
        m = re.search(pat, upper)
        if m:
            word = m.group(1)
            normalised = _normalise_rec(word)
            if normalised != "UNKNOWN":
                return word

    # Fallback: look for bare keywords in first 500 chars
    head = upper[:500]
    for label in ["APPROVE", "CONDITIONAL", "REJECT", "DECLINE"]:
        if label in head:
            return label

    return ""


# ═══════════════════════════════════════════════════════════════════
#  B)  Risk Flag Coverage Delta
# ═══════════════════════════════════════════════════════════════════

def _compare_risk_flags(
    v3: dict[str, Any],
    v4: dict[str, Any],
    v3_risk_flags: list[dict[str, Any]] | None,
) -> RiskFlagCoverageDelta:
    # V3 risk flags
    v3_labels = _extract_risk_labels(v3_risk_flags)
    v3_count = len(v3_labels) if v3_labels else v3.get("riskFlagsCount", 0)

    # V4 risk flags — from critic output or analysis
    v4_critic_flaws = v4.get("criticFatalFlaws", 0)
    v4_count = v4_critic_flaws

    # If we have risk labels from V3, compute set difference
    v3_set = set(v3_labels)
    v4_set: set[str] = set()

    # V4 may have risk information from chapters or evidence pack
    # For now, we use critic fatal flaws count as the V4 risk metric

    new_flags = sorted(v4_set - v3_set)
    lost_flags = sorted(v3_set - v4_set)

    # Severity delta
    v3_severity = _weighted_severity(v3_risk_flags)
    v4_severity = v4_critic_flaws * 0.8  # Each critic fatal flaw ≈ HIGH severity
    severity_delta = round(v4_severity - v3_severity, 2)

    return RiskFlagCoverageDelta(
        risk_flags_v3=v3_count,
        risk_flags_v4=v4_count,
        new_flags_detected=new_flags,
        lost_flags=lost_flags,
        severity_delta=severity_delta,
    )


# ═══════════════════════════════════════════════════════════════════
#  C)  Sponsor & Key Person Impact
# ═══════════════════════════════════════════════════════════════════

def _compare_sponsor(
    v4: dict[str, Any],
    v4_evidence_pack: dict[str, Any] | None,
) -> SponsorImpact:
    sponsor_flags = v4.get("sponsorFlags", 0)
    sponsor_present = sponsor_flags > 0 or (
        v4_evidence_pack is not None
        and bool(v4_evidence_pack.get("sponsor_output"))
    )

    # Determine impact
    if not sponsor_present:
        impact = "none"
    elif sponsor_flags >= 3:
        impact = "disqualifying"
    elif sponsor_flags >= 1:
        impact = "material"
    else:
        # Sponsor engine ran but found nothing negative
        sp_out = (v4_evidence_pack or {}).get("sponsor_output", {})
        if sp_out and sp_out.get("key_persons"):
            impact = "minor"
        else:
            impact = "none"

    return SponsorImpact(
        sponsor_present=sponsor_present,
        sponsor_red_flags=sponsor_flags,
        impact_on_final=impact,
    )


# ═══════════════════════════════════════════════════════════════════
#  D)  Evidence Density & Citation Quality
# ═══════════════════════════════════════════════════════════════════

_CHARS_PER_TOKEN = 4


def _compare_evidence(
    v4: dict[str, Any],
    v4_evidence_pack: dict[str, Any] | None,
    v4_chapters: list[dict[str, Any]] | None,
) -> EvidenceDensity:
    # Evidence surface tokens
    pack_tokens = v4.get("evidencePackTokens", 0)
    if not pack_tokens and v4_evidence_pack:
        pack_json_str = str(v4_evidence_pack)
        pack_tokens = len(pack_json_str) // _CHARS_PER_TOKEN

    # Count citations from evidence map
    citations = 0
    if v4_evidence_pack:
        emap = v4_evidence_pack.get("evidence_map", [])
        citations = len(emap) if isinstance(emap, list) else 0

    # Check for unsupported claims — look for chapters mentioning data
    # without corresponding evidence map entries
    unsupported = False
    if v4_chapters and citations == 0 and len(v4_chapters) > 0:
        # Chapters exist but no citations → potential hallucination risk
        total_content = sum(len(ch.get("content_md", "")) for ch in v4_chapters)
        if total_content > 1000:
            unsupported = True

    return EvidenceDensity(
        evidence_surface_tokens=pack_tokens,
        citations_used=citations,
        unsupported_claims_detected=unsupported,
    )


# ═══════════════════════════════════════════════════════════════════
#  E)  Internal Consistency Score
# ═══════════════════════════════════════════════════════════════════

# Contradiction detection pairs (chapter_tag_a, chapter_tag_b, pattern)
_CONTRADICTION_PAIRS = [
    ("ch04_macro", "ch05_return", "macro_return"),
    ("ch06_quant", "ch08_downside", "quant_downside"),
    ("ch09_risk", "ch13_recommendation", "risk_recommendation"),
]

# Sentiment keywords for simple polarity detection
_POSITIVE_KEYWORDS = frozenset({
    "strong", "robust", "favorable", "positive", "improving",
    "stable", "healthy", "resilient", "sound", "solid",
})
_NEGATIVE_KEYWORDS = frozenset({
    "weak", "deteriorating", "adverse", "negative", "declining",
    "fragile", "stressed", "elevated", "concerning", "problematic",
})


def _polarity_score(text: str) -> float:
    """Compute naive polarity from keyword counts. Range: [-1, +1]."""
    if not text:
        return 0.0
    words = set(text.lower().split())
    pos = len(words & _POSITIVE_KEYWORDS)
    neg = len(words & _NEGATIVE_KEYWORDS)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


def _compare_consistency(
    v4: dict[str, Any],
    v4_chapters: list[dict[str, Any]] | None,
    v4_evidence_pack: dict[str, Any] | None,
) -> InternalConsistency:
    if not v4_chapters:
        return InternalConsistency(consistency_score=1.0, contradictions=[])

    # Build chapter content map
    ch_map: dict[str, str] = {}
    for ch in v4_chapters:
        tag = ch.get("chapter_tag", "")
        content = ch.get("content_md", "")
        if tag and content:
            ch_map[tag] = content

    contradictions: list[str] = []
    penalty = 0.0

    for tag_a, tag_b, pair_name in _CONTRADICTION_PAIRS:
        text_a = ch_map.get(tag_a, "")
        text_b = ch_map.get(tag_b, "")
        if not text_a or not text_b:
            continue

        pol_a = _polarity_score(text_a)
        pol_b = _polarity_score(text_b)

        # Strong divergence: one positive, one negative
        if pol_a * pol_b < 0 and abs(pol_a - pol_b) > 0.6:
            contradictions.append(
                f"{pair_name}: {tag_a}(pol={pol_a:.2f}) vs {tag_b}(pol={pol_b:.2f})",
            )
            penalty += 0.15

    # Check recommendation vs risk flags
    rec_chapter = ch_map.get("ch13_recommendation", "")
    risk_chapter = ch_map.get("ch09_risk", "")
    if rec_chapter and risk_chapter:
        rec_pol = _polarity_score(rec_chapter)
        risk_pol = _polarity_score(risk_chapter)
        # If recommendation is very positive but risk is very negative
        if rec_pol > 0.3 and risk_pol < -0.3:
            contradictions.append(
                f"recommendation_risk: ch13(pol={rec_pol:.2f}) vs ch09(pol={risk_pol:.2f})",
            )
            penalty += 0.2

    # Check quant vs concentration
    quant_status = v4.get("quantStatus", "")
    conc_breached = v4.get("concentrationBreached", False)
    if conc_breached and quant_status == "COMPLETE":
        # Not necessarily a contradiction — just note it
        pass

    score = max(0.0, 1.0 - penalty)
    return InternalConsistency(
        consistency_score=round(score, 4),
        contradictions=contradictions,
    )
