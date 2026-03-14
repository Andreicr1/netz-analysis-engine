"""
Model Configuration — Netz Private Credit OS
============================================

Centralises every model string used across the pipeline.
Single source of truth: change the model for any stage/chapter here,
no need to touch deep_review.py, memo_book_generator.py, or tone_normalizer.py.

Priority for resolution:
  1. NETZ_MODEL_{STAGE} environment variable  (uppercase, hyphens→underscores)
  2. MODELS dict below
  3. Fallback: gpt-4.1  (safe default for unknown stages)

A/B testing:
  Set environment variables to override per-stage without touching code:
    NETZ_MODEL_CH05=gpt-5.1
    NETZ_MODEL_CH06=gpt-5.1
    NETZ_MODEL_CRITIC=o4-mini

Cost governance:
  gpt-5.1 is the IC-grade narrative model.  Input token cost is managed
  via evidence pack filtering + per-chapter chunk budgets + prompt caching.
  Batch API (50% discount) available for non-interactive runs.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-4.1"  # safe fallback for unknown stages

# ---------------------------------------------------------------------------
# Model routing table
# ---------------------------------------------------------------------------
MODELS: dict[str, str] = {
    # ── Chapter generation (ch01–ch14) ───────────────────────────────────
    # All chapters → gpt-5.1 (IC-grade reasoning model, institutional quality)
    # Input cost managed via evidence pack filtering + chunk budgets + caching.
    "ch01_exec": "gpt-5.1",  # Executive summary — synthesis, dense
    "ch02_macro": "gpt-5.1",  # Macro & market context — table + prose
    "ch03_exit": "gpt-5.1",  # Macro regime & exit — structured format
    "ch04_sponsor": "gpt-5.1",  # Sponsor profile — multi-source synthesis
    "ch05_legal": "gpt-5.1",  # Legal structure — surgical, not encyclopedic
    "ch06_terms": "gpt-5.1",  # Terms & covenants — dense financial structure
    "ch07_capital": "gpt-5.1",  # Capital structure — analytical
    "ch08_returns": "gpt-5.1",  # Return modeling — table + interpretation
    "ch09_downside": "gpt-5.1",  # Downside scenario — sensitivity matrix
    "ch10_covenants": "gpt-5.1",  # Covenant assessment — structured checklist
    "ch11_risks": "gpt-5.1",  # Key risks — structured matrix
    "ch12_peers": "gpt-5.1",  # Peer comparison — TABLE required
    "ch13_recommendation": "gpt-5.1",  # IC signal — pipeline scaffolding does reasoning
    "ch14_governance_stress": "gpt-5.1",  # Governance stress — largest chapter, 18k+ chars
    # ── Auxiliary pipeline agents ─────────────────────────────────────────
    "critic": "gpt-4.1",  # Fatal flaws, gaps, bias detection
    "critic_escalation": "o4-mini",  # Triggered on low-confidence → reasoning model
    "concentration": "gpt-4.1-mini",  # HHI / exposure limits — deterministic
    "xbrl_extractor": "gpt-4.1-mini",  # EDGAR structured extraction
    "evidence_pack": "gpt-4.1-mini",  # Evidence pack assembly
    # ── Pipeline stages ──────────────────────────────────────────────────
    "structured": "gpt-4.1",  # Stage 2 deal analysis JSON
    "policy": "gpt-4.1",  # Policy compliance check
    "sponsor": "gpt-4.1",  # Stage 9 sponsor deep-dive
    "quant": "gpt-4.1",  # Quantitative profile
    "monitoring": "gpt-4.1",  # Monitoring checklist
    "memo": "gpt-5.1",  # IC-grade memo narrative (fallback)
    "memo_mini": "gpt-4.1-mini",  # Mini memo fallback
    "pipeline_memo": "gpt-5.1",  # Simple-pipeline memo writer
    # ── Tone Normalizer passes ────────────────────────────────────────────
    "tone_pass1": "gpt-4.1-mini",  # Per-chapter, parallel — local normalisation
    "tone_pass2": "gpt-4.1-mini",  # Signal integrity check on excerpts — lightweight
    # ── Document Intelligence Layer ──────────────────────────────────────
    "classification": "gpt-4.1-mini",  # Doc-type classification — lightweight
    "extraction": "gpt-4.1",  # Structured field extraction
    "doc_summary": "gpt-4.1-mini",  # Document summarisation — lightweight
    # ── Compliance ───────────────────────────────────────────────────────
    "compliance_extraction": "gpt-4.1",  # Obligation extraction from fund docs
    # ── Document Review ────────────────────────────────────────────────
    "doc_review": "gpt-4.1",  # AI-assisted checklist verification
    "eval_judge": "gpt-4.1",  # Structured narrative quality judge for eval framework
}

# ---------------------------------------------------------------------------
# Chapter type classification (ANALYTICAL vs DESCRIPTIVE)
# Used by Tone Normalizer to decide character limits.
# ---------------------------------------------------------------------------
CHAPTER_TYPES: dict[str, str] = {
    "ch01_exec": "ANALYTICAL",
    "ch02_macro": "ANALYTICAL",
    "ch03_exit": "ANALYTICAL",
    "ch04_sponsor": "DESCRIPTIVE",
    "ch05_legal": "DESCRIPTIVE",
    "ch06_terms": "ANALYTICAL",
    "ch07_capital": "ANALYTICAL",
    "ch08_returns": "ANALYTICAL",
    "ch09_downside": "ANALYTICAL",
    "ch10_covenants": "DESCRIPTIVE",
    "ch11_risks": "DESCRIPTIVE",
    "ch12_peers": "ANALYTICAL",
    "ch13_recommendation": "ANALYTICAL",
    "ch14_governance_stress": "ANALYTICAL",
}

# Character limits for Tone Normalizer Passe 1
DESCRIPTIVE_MAX_CHARS: int = 10_000  # cap descriptive chapters at 10k chars
ANALYTICAL_MIN_CHARS: int = 6_000  # do not compress analytical chapters below 6k


# ---------------------------------------------------------------------------
# Resolution function
# ---------------------------------------------------------------------------
def get_model(stage: str) -> str:
    """Resolve the model string for any pipeline stage or chapter tag.

    Priority:
        1. ``NETZ_MODEL_{STAGE}`` environment variable
        2. ``MODELS`` dict (this file)
        3. Fallback: ``_DEFAULT_MODEL`` (gpt-4.1)

    Examples
    --------
    >>> get_model("ch05_legal")
    'gpt-5.1'
    >>> get_model("critic_escalation")
    'o4-mini'
    >>> get_model("tone_pass1")
    'gpt-4.1-mini'
    """
    # Normalise: hyphens to underscores for env var lookup
    env_key = "NETZ_MODEL_" + stage.upper().replace("-", "_")
    env_override = os.getenv(env_key)
    if env_override:
        logger.debug("MODEL_ENV_OVERRIDE stage=%s model=%s", stage, env_override)
        return env_override

    if stage in MODELS:
        model = MODELS[stage]
        logger.debug("MODEL_CONFIG stage=%s model=%s", stage, model)
        return model

    logger.warning(
        "MODEL_FALLBACK stage=%s → %s (not in MODELS dict)", stage, _DEFAULT_MODEL
    )
    return _DEFAULT_MODEL


def get_chapter_type(chapter_tag: str) -> str:
    """Return 'ANALYTICAL' or 'DESCRIPTIVE' for a chapter tag."""
    return CHAPTER_TYPES.get(chapter_tag, "ANALYTICAL")
