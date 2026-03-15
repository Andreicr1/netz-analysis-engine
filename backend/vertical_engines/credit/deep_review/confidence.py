"""Underwriting Reliability Score — deterministic confidence for Deep Review V4.

Confidence measures ROBUSTNESS OF THE UNDERWRITING PROCESS (quality of
evidence and analytical integrity), NOT "quality of the deal" or "tone of
the memo".  It is computed BEFORE the Tone Normalizer so that narrative
adjustments cannot inflate the score.

Architecture
------------
Score = sum of 6 weighted blocks (max 100), subject to hard caps.

    Block 1 — Evidence Coverage      (0–25)
    Block 2 — Evidence Quality       (0–15)
    Block 3 — Decision Integrity     (0–20)
    Block 4 — Diligence Gap Load     (0–15)
    Block 5 — Critic Outcome         (0–15)
    Block 6 — Data Integrity         (0–10)
                                     ──────
                              Total   100

Hard caps (applied AFTER summation — first matching cap wins):

    has_hard_breaches                  → cap 30  (always LOW)
    critic fatal_flaws ≥ 3            → cap 40
    concentration requires_board_override → cap 65
    metrics_status PARTIAL + pending non-USD → cap 55
    fallback/legacy corpus or low evidence diversity → cap 55

Post-Tone-Normalizer adjustment:
    • Signal escalation updates ``signal_final`` only.
    • Score NEVER increases after tone normalisation.
    • If pass2_changes contain ≥ 2 material contradiction entries,
      score is reduced by 5 (min 0).

See ``docs/development/CONFIDENCE_SCORING.md`` for the full weight/cap table.
"""
from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()

# ── Block weight ceilings ────────────────────────────────────────────
_MAX_EVIDENCE_COVERAGE  = 25
_MAX_EVIDENCE_QUALITY   = 15
_MAX_DECISION_INTEGRITY = 20
_MAX_DILIGENCE_GAPS     = 15
_MAX_CRITIC_OUTCOME     = 15
_MAX_DATA_INTEGRITY     = 10

# ── Critical chapter keys for quality assessment ─────────────────────
_CRITICAL_CHAPTERS = frozenset({
    "ch05_legal", "ch06_terms", "ch07_capital",
    "ch08_returns", "ch10_covenants", "ch04_sponsor",
})

# ── Diligence gap proxies (fields that matter for underwriting) ──────
_CRITICAL_TERMS = frozenset({
    "interestRate", "maturityDate", "collateral",
    "covenants", "principalAmount",
})

# ── Confidence level thresholds ──────────────────────────────────────
_HIGH_THRESHOLD  = 70
_LOW_THRESHOLD   = 40

# ── Tone contradiction penalty ───────────────────────────────────────
_TONE_CONTRADICTION_PENALTY = 5


# ── Public API ───────────────────────────────────────────────────────

def compute_underwriting_confidence(
    *,
    retrieval_audit: dict[str, Any],
    saturation_report: dict[str, Any],
    hard_check_results: dict[str, Any] | None = None,
    concentration_profile: dict[str, Any] | None = None,
    critic_output: dict[str, Any] | None = None,
    quant_profile: dict[str, Any] | None = None,
    evidence_pack_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute a deterministic Underwriting Reliability Score (0–100).

    All inputs are structured dicts produced by earlier deterministic or
    LLM stages.  This function uses NO LLM calls — it is pure arithmetic.

    Returns
    -------
    dict with keys:
        confidence_score    : int (0–100)
        confidence_level    : str ("HIGH" | "MEDIUM" | "LOW")
        caps_applied        : list[str]   — human-readable cap reasons
        breakdown           : dict        — per-block scores
        rationale_bullets   : list[str]   — max 8 deterministic bullets

    """
    _hard   = hard_check_results or {}
    _conc   = concentration_profile or {}
    _critic = critic_output or {}
    _quant  = quant_profile or {}
    _sat    = saturation_report or {}
    _audit  = retrieval_audit or {}
    _epm    = evidence_pack_meta or {}

    bullets: list[str] = []

    # ── Block 1: Evidence Coverage (0–25) ────────────────────────
    b1 = _block_evidence_coverage(_sat, _audit, bullets)

    # ── Block 2: Evidence Quality (0–15) ─────────────────────────
    b2 = _block_evidence_quality(_audit, _epm, bullets)

    # ── Block 3: Decision Integrity (0–20) ───────────────────────
    b3 = _block_decision_integrity(_hard, _conc, bullets)

    # ── Block 4: Diligence Gap Load (0–15) ───────────────────────
    b4 = _block_diligence_gaps(_critic, _epm, bullets)

    # ── Block 5: Critic Outcome (0–15) ───────────────────────────
    b5 = _block_critic_outcome(_critic, bullets)

    # ── Block 6: Data Integrity (0–10) ───────────────────────────
    b6 = _block_data_integrity(_quant, _conc, _audit, bullets)

    raw_score = b1 + b2 + b3 + b4 + b5 + b6

    # ── Apply hard caps ──────────────────────────────────────────
    caps_applied: list[str] = []
    capped_score = _apply_caps(
        raw_score, _hard, _conc, _critic, _quant, _audit, caps_applied,
    )

    level = _score_to_level(capped_score)

    # ── Governance: hard breach → always LOW ─────────────────────
    if _hard.get("has_hard_breaches"):
        if level != "LOW":
            level = "LOW"
            if "Hard policy breach → cap 30" not in caps_applied:
                caps_applied.append("Hard policy breach forces LOW confidence")

    breakdown = {
        "evidence_coverage":  b1,
        "evidence_quality":   b2,
        "decision_integrity": b3,
        "diligence_gaps":     b4,
        "critic_outcome":     b5,
        "data_integrity":     b6,
    }

    return {
        "confidence_score":   capped_score,
        "confidence_level":   level,
        "caps_applied":       caps_applied,
        "breakdown":          breakdown,
        "rationale_bullets":  bullets[:8],
    }


def apply_tone_normalizer_adjustment(
    confidence_result: dict[str, Any],
    *,
    tone_signal_escalated: bool,
    tone_pass2_changes: list[str | dict] | None = None,
) -> dict[str, Any]:
    """Post-ToneNormalizer adjustment — may only *reduce* score, never increase.

    Parameters
    ----------
    confidence_result : dict
        Output from ``compute_underwriting_confidence``.
    tone_signal_escalated : bool
        Whether the Tone Normalizer escalated the IC signal.
    tone_pass2_changes : list
        Pass-2 change log entries from the Tone Normalizer.

    Returns
    -------
    Updated ``confidence_result`` dict (mutated in place and returned).

    """
    if not tone_signal_escalated:
        return confidence_result

    changes = tone_pass2_changes or []

    # Count material contradiction entries in pass2_changes
    contradiction_count = 0
    for entry in changes:
        text = entry if isinstance(entry, str) else str(entry)
        lower = text.lower()
        if "contradiction" in lower or "inconsisten" in lower:
            contradiction_count += 1

    if contradiction_count >= 2:
        old_score = confidence_result["confidence_score"]
        new_score = max(0, old_score - _TONE_CONTRADICTION_PENALTY)
        confidence_result["confidence_score"] = new_score
        confidence_result["confidence_level"] = _score_to_level(new_score)
        cap_msg = (
            f"Tone pass2 detected {contradiction_count} contradictions "
            f"→ confidence reduced by {_TONE_CONTRADICTION_PENALTY} "
            f"({old_score} → {new_score})"
        )
        confidence_result["caps_applied"].append(cap_msg)
        confidence_result["rationale_bullets"].append(cap_msg)
        logger.info("confidence_tone_penalty",
                     old_score=old_score, new_score=new_score,
                     contradictions=contradiction_count)

    return confidence_result


# ── Block computation functions ──────────────────────────────────────

def _block_evidence_coverage(
    sat: dict[str, Any],
    audit: dict[str, Any],
    bullets: list[str],
) -> int:
    """Block 1 — Evidence Coverage (0–25).

    all_saturated → 25.
    Otherwise: 25 − 5×(major_gaps) − 2×(minor_gaps).
    Major gap = MISSING chapter; minor gap = PARTIAL chapter.
    """
    if sat.get("all_saturated"):
        bullets.append("All evidence chapters saturated (25/25)")
        return _MAX_EVIDENCE_COVERAGE

    gaps = sat.get("gaps", [])
    major = sum(1 for g in gaps if g.get("status") == "MISSING")
    minor = sum(1 for g in gaps if g.get("status") == "PARTIAL")

    score = _MAX_EVIDENCE_COVERAGE - (5 * major) - (2 * minor)
    score = max(0, score)

    if major or minor:
        bullets.append(
            f"Evidence gaps: {major} major (MISSING), {minor} minor (PARTIAL) "
            f"→ coverage {score}/{_MAX_EVIDENCE_COVERAGE}",
        )
    return score


def _block_evidence_quality(
    audit: dict[str, Any],
    epm: dict[str, Any],
    bullets: list[str],
) -> int:
    """Block 2 — Evidence Quality (0–15).

    If per-chapter metadata is available (evidence_pack_meta with chapter
    counts): penalise critical chapters below minimum thresholds.
    Otherwise: use retrieval_audit aggregate evidence_confidence.
    """
    score = _MAX_EVIDENCE_QUALITY

    # Try per-chapter metadata from evidence_pack_meta
    chapter_counts = epm.get("chapter_counts", {})
    if chapter_counts:
        penalty = 0
        for ch_key in _CRITICAL_CHAPTERS:
            ch = chapter_counts.get(ch_key, {})
            docs = ch.get("unique_docs", 0)
            chunks = ch.get("chunk_count", 0)
            if docs < 3:
                penalty += 3
            if chunks < 6:
                penalty += 2
        score = max(0, score - penalty)
        if penalty:
            bullets.append(
                f"Critical chapters below doc/chunk minimums → quality "
                f"{score}/{_MAX_EVIDENCE_QUALITY}",
            )
        return score

    # Fallback: aggregate from retrieval_audit
    global_stats = audit.get("global_stats", {})
    ev_conf = global_stats.get("evidence_confidence", "LOW")
    _conf_map = {"VERY_HIGH": 0, "HIGH": 2, "MEDIUM": 5, "LOW": 10}
    penalty = _conf_map.get(ev_conf, 10)
    score = max(0, score - penalty)
    if penalty:
        bullets.append(
            f"Retrieval evidence confidence={ev_conf} → quality "
            f"{score}/{_MAX_EVIDENCE_QUALITY}",
        )
    return score


def _block_decision_integrity(
    hard: dict[str, Any],
    conc: dict[str, Any],
    bullets: list[str],
) -> int:
    """Block 3 — Decision Integrity (0–20).

    Hard breaches → 0–5 (severe penalty).
    Otherwise: 20 − 3×(limit_breaches) − 2×(soft_flags).
    """
    if hard.get("has_hard_breaches"):
        breaches = hard.get("hard_limit_breaches", [])
        score = max(0, 5 - len(breaches))
        bullets.append(
            f"Hard policy breaches ({len(breaches)}) → integrity "
            f"{score}/{_MAX_DECISION_INTEGRITY}",
        )
        return score

    # Count concentration limit breaches (soft)
    limit_breaches = 0
    conc_breaches = conc.get("limit_breaches", [])
    if isinstance(conc_breaches, list):
        limit_breaches = len(conc_breaches)
    elif conc.get("any_limit_breached"):
        limit_breaches = 1

    # Soft flags from concentration
    soft_flags = 0
    if conc.get("requires_board_override"):
        soft_flags += 2
    if conc.get("metrics_status") == "PARTIAL":
        soft_flags += 1

    score = _MAX_DECISION_INTEGRITY - (3 * limit_breaches) - (2 * soft_flags)
    score = max(0, score)

    if limit_breaches or soft_flags:
        bullets.append(
            f"Concentration: {limit_breaches} limit breach(es), "
            f"{soft_flags} soft flag(s) → integrity "
            f"{score}/{_MAX_DECISION_INTEGRITY}",
        )
    return score


def _block_diligence_gaps(
    critic: dict[str, Any],
    epm: dict[str, Any],
    bullets: list[str],
) -> int:
    """Block 4 — Diligence Gap Load (0–15).

    Penalise missing critical underwriting terms from the structured
    analysis (if available in evidence_pack_meta).
    Fallback: use critic unsupported claims as a lighter proxy.
    """
    score = _MAX_DILIGENCE_GAPS

    # Try structured terms from evidence_pack_meta
    terms = epm.get("investment_terms", {})
    if terms:
        missing_count = 0
        for field in _CRITICAL_TERMS:
            val = terms.get(field)
            if not val or (isinstance(val, str) and val.strip().lower() in (
                "", "pending diligence", "n/a", "not specified", "unknown",
            )):
                missing_count += 1
        penalty = missing_count * 3
        score = max(0, score - penalty)
        if missing_count:
            bullets.append(
                f"Missing critical terms ({missing_count}) → diligence "
                f"{score}/{_MAX_DILIGENCE_GAPS}",
            )
        return score

    # Fallback: count material_gaps from critic
    material_gaps = critic.get("material_gaps", [])
    gap_count = len(material_gaps) if isinstance(material_gaps, list) else 0
    penalty = min(gap_count * 2, _MAX_DILIGENCE_GAPS)
    score = max(0, score - penalty)
    if gap_count:
        bullets.append(
            f"Critic identified {gap_count} material gap(s) → diligence "
            f"{score}/{_MAX_DILIGENCE_GAPS}",
        )
    return score


def _block_critic_outcome(
    critic: dict[str, Any],
    bullets: list[str],
) -> int:
    """Block 5 — Critic Outcome (0–15).

    fatal_flaws: 0 → 15, 1 → 10, 2 → 6, ≥3 → 2.
    """
    fatal_count = len(critic.get("fatal_flaws", []))
    _score_map = {0: 15, 1: 10, 2: 6}
    score = _score_map.get(fatal_count, 2)

    if fatal_count:
        bullets.append(
            f"Critic fatal flaws: {fatal_count} → outcome "
            f"{score}/{_MAX_CRITIC_OUTCOME}",
        )
    return score


def _block_data_integrity(
    quant: dict[str, Any],
    conc: dict[str, Any],
    audit: dict[str, Any],
    bullets: list[str],
) -> int:
    """Block 6 — Data Integrity (0–10).

    Penalties:
      metrics_status PARTIAL       → −4
      FX missing on non-USD pending → −3
      any JSON retries / fallback   → −2
    """
    score = _MAX_DATA_INTEGRITY
    reasons: list[str] = []

    metrics_status = quant.get("metrics_status", "INSUFFICIENT_DATA")
    if metrics_status == "PARTIAL":
        score -= 4
        reasons.append("metrics_status=PARTIAL (−4)")
    elif metrics_status == "INSUFFICIENT_DATA":
        score -= 4
        reasons.append("metrics_status=INSUFFICIENT_DATA (−4)")

    # FX conversion gap
    currency = quant.get("currency") or conc.get("currency") or "USD"
    fx_status = quant.get("fx_conversion_status", "")
    if currency.upper() != "USD" and fx_status in ("missing", "unavailable", ""):
        score -= 3
        reasons.append(f"FX missing for {currency} (−3)")

    # Fallback corpus indicator
    global_stats = audit.get("global_stats", {})
    evidence_conf = global_stats.get("evidence_confidence", "")
    if evidence_conf == "LOW":
        score -= 2
        reasons.append("Low evidence diversity / fallback corpus (−2)")

    score = max(0, score)
    if reasons:
        bullets.append(
            f"Data integrity: {', '.join(reasons)} → {score}/{_MAX_DATA_INTEGRITY}",
        )
    return score


# ── Hard caps ────────────────────────────────────────────────────────

def _apply_caps(
    raw_score: int,
    hard: dict[str, Any],
    conc: dict[str, Any],
    critic: dict[str, Any],
    quant: dict[str, Any],
    audit: dict[str, Any],
    caps_applied: list[str],
) -> int:
    """Apply hard caps to the raw score. Caps are ordered by severity."""
    score = raw_score

    # Cap 1: Hard policy breach → max 30
    if hard.get("has_hard_breaches") and score > 30:
        caps_applied.append(
            f"Hard policy breach → cap 30 (was {score})",
        )
        score = 30

    # Cap 2: Critic fatal flaws ≥ 3 → max 40
    fatal_count = len(critic.get("fatal_flaws", []))
    if fatal_count >= 3 and score > 40:
        caps_applied.append(
            f"Critic fatal flaws ({fatal_count}) ≥ 3 → cap 40 (was {score})",
        )
        score = 40

    # Cap 3: Concentration requires board override → max 65
    if conc.get("requires_board_override") and score > 65:
        caps_applied.append(
            f"Concentration requires board override → cap 65 (was {score})",
        )
        score = 65

    # Cap 4: Metrics PARTIAL + non-USD pending → max 55
    metrics_status = quant.get("metrics_status", "")
    currency = quant.get("currency") or conc.get("currency") or "USD"
    if (metrics_status == "PARTIAL"
            and currency.upper() != "USD"
            and score > 55):
        caps_applied.append(
            f"metrics_status=PARTIAL + non-USD ({currency}) → cap 55 (was {score})",
        )
        score = 55

    # Cap 5: Low evidence diversity / fallback corpus → max 55
    global_stats = audit.get("global_stats", {})
    evidence_conf = global_stats.get("evidence_confidence", "")
    if evidence_conf == "LOW" and score > 55:
        caps_applied.append(
            f"Low evidence diversity (evidence_confidence=LOW) → cap 55 (was {score})",
        )
        score = 55

    return max(0, score)


# ── Level mapping ────────────────────────────────────────────────────

def _score_to_level(score: int) -> str:
    """Map 0–100 int score to HIGH / MEDIUM / LOW."""
    if score >= _HIGH_THRESHOLD:
        return "HIGH"
    if score >= _LOW_THRESHOLD:
        return "MEDIUM"
    return "LOW"


__all__ = ["compute_underwriting_confidence", "apply_tone_normalizer_adjustment"]
