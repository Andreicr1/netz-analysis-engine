"""Tone Normalizer Agent — Netz Private Credit OS
===============================================

Two-pass post-processing for IC memo quality:

  Passe 1 (parallel, gpt-4.1-mini):
      Chapter-local normalisation — hedging removal, tense normalisation,
      descriptive chapter length cap, voice consistency.

  Passe 2 (sequential, gpt-4.1):
      Full-memo holistic review — cross-chapter consistency, narrative
      contradiction detection, IC signal escalation if logical inconsistency
      is found.

Position in pipeline:
    Stage 12 Memo Book  →  Stage 4.5 Tone Normalizer  →  Stage 13c Artifact Persist

Signal escalation rules (Passe 2):
  - critic_fatal_flaws >= 3  AND  signal == CONDITIONAL  →  PASS
  - ch07 risk severity == SEVERE  AND  signal == INVEST    →  CONDITIONAL
  - 2+ unresolved narrative contradictions  →  escalate if material

NOTE: Tone Normalizer may ONLY escalate signals, never de-escalate.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pydantic import BaseModel

from ai_engine.model_config import (
    ANALYTICAL_MIN_CHARS,
    DESCRIPTIVE_MAX_CHARS,
    get_chapter_type,
    get_model,
)
from ai_engine.openai_client import create_completion
from ai_engine.prompts import prompt_registry

logger = logging.getLogger(__name__)

_LLM_SEMAPHORE: asyncio.Semaphore | None = None


def _get_llm_semaphore() -> asyncio.Semaphore:
    """Lazy semaphore creation — must not be created at module scope."""
    global _LLM_SEMAPHORE
    if _LLM_SEMAPHORE is None:
        _LLM_SEMAPHORE = asyncio.Semaphore(4)
    return _LLM_SEMAPHORE


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ToneReviewEntry(BaseModel):
    chapter: str
    change_type: str  # hedging_removed | tense_normalized | length_reduced | contradiction_flagged | signal_escalated
    original_fragment: str
    revised_fragment: str
    rationale: str


class ToneReviewResult(BaseModel):
    chapters: dict[str, str]        # ch_tag → revised chapter text
    signal_original: str            # INVEST | CONDITIONAL | PASS
    signal_final: str               # may differ if escalated
    signal_escalated: bool
    escalation_rationale: str | None  # required if escalated
    tone_review_log: list[ToneReviewEntry]
    pass1_changes: dict[str, int]   # {chapter_tag: chars_removed}
    pass2_changes: list[str]        # description of cross-chapter changes


# ---------------------------------------------------------------------------
# Passe 1 — per-chapter normalisation (parallel)
# ---------------------------------------------------------------------------

def _pass1_system(chapter_type: str, max_chars: int) -> str:
    return prompt_registry.render(
        "intelligence/tone_pass1.j2",
        chapter_type=chapter_type,
        max_chars=max_chars,
    )


def _run_pass1_chapter(chapter_tag: str, text: str) -> tuple[str, int]:
    """Synchronous Passe 1 for one chapter — called via asyncio.to_thread."""
    chapter_type = get_chapter_type(chapter_tag)
    # For DESCRIPTIVE: cap length; for ANALYTICAL: minimum length hint for template
    max_chars = DESCRIPTIVE_MAX_CHARS if chapter_type == "DESCRIPTIVE" else ANALYTICAL_MIN_CHARS
    model = get_model("tone_pass1")

    try:
        result = create_completion(
            system_prompt=_pass1_system(chapter_type, max_chars),
            user_prompt=text,
            model=model,
            temperature=0.1,
            max_tokens=4096,
            stage="tone_pass1",
        )
        revised = result.text.strip()
        chars_removed = len(text) - len(revised)
        logger.debug(
            "TONE_PASS1 chapter=%s original=%d revised=%d delta=%d",
            chapter_tag, len(text), len(revised), chars_removed,
        )
        return revised, chars_removed
    except Exception as exc:
        logger.warning("TONE_PASS1_FAILED chapter=%s error=%s — returning original", chapter_tag, exc)
        return text, 0


async def _pass1_async(chapters: dict[str, str]) -> tuple[dict[str, str], dict[str, int]]:
    """Passe 1: all chapters in parallel via asyncio.to_thread (max 4 concurrent)."""

    async def _guarded(ch_tag: str, text: str) -> tuple[str, int]:
        async with _get_llm_semaphore():
            return await asyncio.to_thread(_run_pass1_chapter, ch_tag, text)

    tasks = {
        ch_tag: _guarded(ch_tag, text)
        for ch_tag, text in chapters.items()
    }

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    revised_chapters: dict[str, str] = {}
    changes: dict[str, int] = {}

    for ch_tag, result in zip(tasks.keys(), results, strict=False):
        if isinstance(result, BaseException):
            logger.warning("TONE_PASS1_GATHER_FAIL chapter=%s error=%s", ch_tag, result)
            revised_chapters[ch_tag] = chapters[ch_tag]
            changes[ch_tag] = 0
        else:
            revised_text, delta = result
            revised_chapters[ch_tag] = revised_text
            changes[ch_tag] = delta

    return revised_chapters, changes


# ---------------------------------------------------------------------------
# Passe 2 — full memo holistic review (sequential)
# ---------------------------------------------------------------------------

# Pass 2 is a lightweight signal-integrity check only.
# It receives chapter EXCERPTS (first 1500 chars each) — NOT full chapters.
# It returns ONLY signal decision + log.  Chapter text is NOT rewritten here;
# the final chapters = pass1 output (already normalised per-chapter).

# Excerpt limit per chapter for Pass 2 input — keeps total prompt < 8k tokens
_PASS2_EXCERPT_CHARS: int = 1_500


def _run_pass2(
    chapters: dict[str, str],
    critic_output: dict,
    current_signal: str,
) -> dict[str, Any]:
    """Passe 2: lightweight signal-integrity check on chapter excerpts.

    chapters are NOT rewritten here; the caller merges pass1 chapters into
    the final result.  This function only returns signal + log.
    """
    model = get_model("tone_pass2")
    fatal_flaws_count = len(critic_output.get("fatal_flaws", []))

    # Send only the first _PASS2_EXCERPT_CHARS chars of each chapter
    # (~1500 × 14 ≈ 21k chars ≈ 5-6k tokens — vs 80-120k chars when sending full chapters)
    excerpt_sections = "\n\n".join(
        f"=== {ch_tag.upper()} (excerpt) ===\n{text[:_PASS2_EXCERPT_CHARS]}"
        + ("…[truncated]" if len(text) > _PASS2_EXCERPT_CHARS else "")
        for ch_tag, text in chapters.items()
    )

    user = (
        f"CURRENT SIGNAL: {current_signal}\n"
        f"CRITIC FATAL FLAWS: {fatal_flaws_count}\n"
        f"CRITIC OUTPUT SUMMARY: {json.dumps(critic_output, default=str)[:2000]}\n\n"
        f"CHAPTER EXCERPTS:\n{excerpt_sections}"
    )

    try:
        system_prompt = prompt_registry.render("intelligence/tone_pass2.j2")
        result = create_completion(
            system_prompt=system_prompt,
            user_prompt=user,
            model=model,
            temperature=0.1,
            max_tokens=512,
            response_format={"type": "json_object"},
            stage="tone_pass2",
        )
        parsed = json.loads(result.text)

        # Ensure mandatory fields
        parsed.setdefault("signal_original", current_signal)
        parsed.setdefault("signal_final", current_signal)
        parsed.setdefault("signal_escalated", False)
        parsed.setdefault("escalation_rationale", None)
        parsed.setdefault("tone_review_log", [])
        parsed.setdefault("pass1_changes", {})
        parsed.setdefault("pass2_changes", ["No issues detected."])

        # Safety guardrail: signal may only escalate, never de-escalate
        _SIGNAL_RANK = {"INVEST": 0, "CONDITIONAL": 1, "PASS": 2}
        orig_rank = _SIGNAL_RANK.get(current_signal, 0)
        final_rank = _SIGNAL_RANK.get(parsed["signal_final"], 0)
        if final_rank < orig_rank:
            logger.warning(
                "TONE_PASS2_DEESCALATION_BLOCKED original=%s proposed=%s — reverting",
                current_signal, parsed["signal_final"],
            )
            parsed["signal_final"] = current_signal
            parsed["signal_escalated"] = False
            parsed["escalation_rationale"] = None

        # NOTE: 'chapters' key is intentionally absent — caller merges pass1 chapters
        return parsed

    except Exception as exc:
        logger.warning("TONE_PASS2_FAILED error=%s — using pass1 chapters unchanged", exc)
        return {
            "signal_original": current_signal,
            "signal_final": current_signal,
            "signal_escalated": False,
            "escalation_rationale": None,
            "tone_review_log": [],
            "pass1_changes": {},
            "pass2_changes": [f"Pass 2 failed: {exc}"],
        }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run_tone_normalizer(
    chapter_texts: dict[str, str],
    critic_output: dict,
    current_signal: str,
) -> dict[str, Any]:
    """Run Tone Normalizer (Passe 1 parallel + Passe 2 holistic).

    Parameters
    ----------
    chapter_texts : dict[str, str]
        Mapping of chapter_tag → raw chapter content.
        Example: {"ch01_exec": "...", "ch14_governance_stress": "..."}
    critic_output : dict
        Critic engine output dict (used for fatal_flaws count in Passe 2).
    current_signal : str
        Current IC recommendation signal: "INVEST" | "CONDITIONAL" | "PASS".

    Returns
    -------
    dict matching ToneReviewResult schema.

    """
    if not chapter_texts:
        logger.warning("TONE_NORMALIZER: no chapter_texts provided — skipping")
        return {
            "chapters": {},
            "signal_original": current_signal,
            "signal_final": current_signal,
            "signal_escalated": False,
            "escalation_rationale": None,
            "tone_review_log": [],
            "pass1_changes": {},
            "pass2_changes": ["Skipped: no chapter_texts provided."],
        }

    total_chars_in = sum(len(t) for t in chapter_texts.values())
    logger.info(
        "TONE_NORMALIZER_START chapters=%d total_chars=%d signal=%s",
        len(chapter_texts), total_chars_in, current_signal,
    )

    # Passe 1 — parallel per-chapter normalisation
    revised_chapters, pass1_changes = await _pass1_async(chapter_texts)

    total_delta = sum(pass1_changes.values())
    logger.info(
        "TONE_PASS1_COMPLETE chapters=%d chars_removed=%d",
        len(revised_chapters), total_delta,
    )

    # Passe 2 — lightweight signal-integrity check (excerpts only, no chapter rewrites)
    pass2_result = await asyncio.to_thread(
        _run_pass2, revised_chapters, critic_output, current_signal,
    )

    # Merge: final chapters = pass1 output (pass2 only checks signal, does not rewrite)
    pass2_result["chapters"] = revised_chapters
    pass2_result["pass1_changes"] = pass1_changes

    if pass2_result.get("signal_escalated"):
        logger.warning(
            "TONE_SIGNAL_ESCALATED %s → %s | rationale: %s",
            pass2_result["signal_original"],
            pass2_result["signal_final"],
            pass2_result.get("escalation_rationale", ""),
        )
    else:
        logger.info("TONE_PASS2_COMPLETE signal=%s (unchanged)", current_signal)

    return pass2_result
