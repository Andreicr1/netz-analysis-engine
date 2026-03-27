"""Delta Metrics — Tier-1 deterministic engine quality scoring.

Computes a weighted composite score from DeepReviewDeltaReport fields.
No subjective language.  Pure numeric formula.

Weights (institutional policy):
  Risk completeness:       30%
  Sponsor coverage:        20%
  Recommendation coherence: 20%
  Evidence grounding:      20%
  Internal consistency:    10%
"""
from __future__ import annotations

import logging

from ai_engine.validation.validation_schema import (
    DealValidationResult,
    DeepReviewDeltaReport,
    EngineScore,
)

logger = logging.getLogger(__name__)

# ── Weight table (must sum to 1.0) ────────────────────────────────
W_RISK = 0.30
W_SPONSOR = 0.20
W_RECOMMENDATION = 0.20
W_EVIDENCE = 0.20
W_CONSISTENCY = 0.10


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


# ═══════════════════════════════════════════════════════════════════
#  Per-deal engine quality score
# ═══════════════════════════════════════════════════════════════════

def compute_engine_quality_score(delta: DeepReviewDeltaReport) -> EngineScore:
    """Compute a deterministic V4-vs-V3 quality score from a delta report.

    Each dimension produces a score in [-1, +1]:
      -1  = V3 clearly better
       0  = tie
      +1  = V4 clearly better

    The weighted sum is then mapped to [0, 1] confidence and a winner.
    """
    scores: dict[str, float] = {}
    reasons: list[str] = []

    # ── 1. Risk completeness (30%) ───────────────────────────────
    rf = delta.risk_flags
    if rf.risk_flags_v3 == 0 and rf.risk_flags_v4 == 0:
        scores["risk"] = 0.0
    else:
        # More flags = better coverage (capped at +1)
        flag_diff = rf.risk_flags_v4 - rf.risk_flags_v3
        max_val = max(rf.risk_flags_v3, rf.risk_flags_v4, 1)
        scores["risk"] = _clamp(flag_diff / max_val, -1.0, 1.0)

    new_count = len(rf.new_flags_detected)
    lost_count = len(rf.lost_flags)
    if new_count > lost_count:
        reasons.append(f"+{new_count} new risk flags in V4")
    elif lost_count > new_count:
        reasons.append(f"-{lost_count} risk flags lost in V4")

    # ── 2. Sponsor coverage (20%) ────────────────────────────────
    sp = delta.sponsor
    if sp.sponsor_present:
        # V4 has sponsor engine; V3 does not → V4 advantage
        scores["sponsor"] = 0.6  # baseline advantage for having sponsor
        if sp.sponsor_red_flags > 0:
            scores["sponsor"] = 1.0  # material new information
            reasons.append(f"{sp.sponsor_red_flags} sponsor red flags detected")
        if sp.impact_on_final == "disqualifying":
            scores["sponsor"] = 1.0
            reasons.append("Sponsor analysis triggered disqualifying signal")
        elif sp.impact_on_final == "material":
            scores["sponsor"] = min(scores["sponsor"] + 0.2, 1.0)
            reasons.append("Sponsor analysis materially affected recommendation")
    else:
        scores["sponsor"] = 0.0  # neither engine has sponsor

    # ── 3. Recommendation coherence (20%) ────────────────────────
    rec = delta.recommendation
    if not rec.material_divergence:
        scores["recommendation"] = 0.0  # same recommendation = tie
    else:
        # Divergence exists. V4 is considered better if it is more
        # conservative (downgrades), worse if it is more permissive.
        upgrade_directions = {
            "REJECT→CONDITIONAL", "REJECT→APPROVE",
            "CONDITIONAL→APPROVE",
        }
        downgrade_directions = {
            "APPROVE→CONDITIONAL", "APPROVE→REJECT",
            "CONDITIONAL→REJECT",
        }
        direction = rec.divergence_direction or ""
        if direction in downgrade_directions:
            # More conservative = better risk management
            scores["recommendation"] = 0.5
            reasons.append(f"V4 more conservative: {direction}")
        elif direction in upgrade_directions:
            # More permissive = potentially worse governance
            scores["recommendation"] = -0.5
            reasons.append(f"V4 more permissive: {direction}")
        else:
            scores["recommendation"] = 0.0

    # ── 4. Evidence grounding (20%) ──────────────────────────────
    ev = delta.evidence
    if ev.evidence_surface_tokens > 0:
        # V4 has a quantified evidence surface; V3 does not expose this
        scores["evidence"] = 0.5
        if ev.citations_used >= 10:
            scores["evidence"] = 0.8
        if ev.citations_used >= 20:
            scores["evidence"] = 1.0
        if ev.unsupported_claims_detected:
            scores["evidence"] = max(scores["evidence"] - 0.5, -1.0)
            reasons.append("Unsupported claims detected in V4 output")
        else:
            reasons.append(f"{ev.citations_used} citations grounded in V4")
    else:
        scores["evidence"] = 0.0

    # ── 5. Internal consistency (10%) ────────────────────────────
    con = delta.consistency
    if con.consistency_score >= 0.9:
        scores["consistency"] = 0.8
    elif con.consistency_score >= 0.7:
        scores["consistency"] = 0.3
    else:
        scores["consistency"] = -0.5
        reasons.append(
            f"Low consistency ({con.consistency_score:.2f}): "
            + "; ".join(con.contradictions[:3]),
        )

    # ── Weighted composite ───────────────────────────────────────
    composite = (
        scores["risk"] * W_RISK
        + scores["sponsor"] * W_SPONSOR
        + scores["recommendation"] * W_RECOMMENDATION
        + scores["evidence"] * W_EVIDENCE
        + scores["consistency"] * W_CONSISTENCY
    )

    # Map [-1, +1] composite → winner + confidence
    if composite > 0.05:
        winner = "V4"
        confidence = _clamp(0.5 + composite * 0.5, 0.5, 1.0)
    elif composite < -0.05:
        winner = "V3"
        confidence = _clamp(0.5 + abs(composite) * 0.5, 0.5, 1.0)
    else:
        winner = "TIE"
        confidence = 0.5

    reason_str = "; ".join(reasons) if reasons else "No material divergence detected"

    logger.info(
        "ENGINE_QUALITY_SCORE deal=%s composite=%.3f winner=%s conf=%.2f",
        delta.deal_id, composite, winner, confidence,
    )

    return EngineScore(
        engine_winner=winner,
        confidence=round(confidence, 4),
        reason=reason_str,
    )


# ═══════════════════════════════════════════════════════════════════
#  Aggregate score across multiple deals
# ═══════════════════════════════════════════════════════════════════

def compute_aggregate_score(
    deal_results: list[DealValidationResult],
) -> EngineScore:
    """Aggregate per-deal scores into a single institutional verdict.

    Simple majority + average confidence.  TIE breaks to V4 (newer engine
    should win ties given additive sponsor analysis).
    """
    v3_wins = 0
    v4_wins = 0
    ties = 0
    total_conf = 0.0
    all_reasons: list[str] = []
    scored = 0

    for dr in deal_results:
        if dr.engine_score is None:
            continue
        scored += 1
        total_conf += dr.engine_score.confidence
        if dr.engine_score.engine_winner == "V4":
            v4_wins += 1
        elif dr.engine_score.engine_winner == "V3":
            v3_wins += 1
        else:
            ties += 1
        if dr.engine_score.reason:
            deal_label = (dr.deal_name or dr.deal_id)[:30]
            all_reasons.append(f"[{deal_label}] {dr.engine_score.reason}")

    if scored == 0:
        return EngineScore(engine_winner="TIE", confidence=0.0, reason="No deals scored")

    avg_conf = total_conf / scored

    if v4_wins > v3_wins:
        winner = "V4"
    elif v3_wins > v4_wins:
        winner = "V3"
    else:
        winner = "V4"  # TIE breaks to V4 (newer, additive capabilities)

    reason = f"{v4_wins}V4/{v3_wins}V3/{ties}TIE across {scored} deals. " + "; ".join(all_reasons[:5])

    return EngineScore(
        engine_winner=winner,
        confidence=round(_clamp(avg_conf), 4),
        reason=reason[:500],
    )


def compute_institutional_decision(score: EngineScore) -> str:
    """Map an aggregate EngineScore to a one-line institutional decision."""
    if score.engine_winner == "V4" and score.confidence >= 0.7:
        return "V4 recommended for institutional adoption. Superior risk coverage, sponsor analysis, and evidence grounding."
    if score.engine_winner == "V4" and score.confidence >= 0.5:
        return "V4 shows marginal improvement. Consider expanded benchmark before full adoption."
    if score.engine_winner == "V3":
        return "V3 retains advantage. V4 requires further calibration before deployment."
    return "Inconclusive. Expand sample size or review individual deal deltas."
