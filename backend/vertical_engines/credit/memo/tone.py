"""Tone Normalizer Agent — two-pass post-processing for IC memo quality.

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

Imports models only.

Error contract: never-raises (orchestration engine).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

from ai_engine.model_config import (
    ANALYTICAL_MIN_CHARS,
    DESCRIPTIVE_MAX_CHARS,
    get_chapter_type,
    get_model,
)
from ai_engine.openai_client import create_completion
from ai_engine.prompts import prompt_registry

logger = structlog.get_logger()

_LLM_SEMAPHORE: asyncio.Semaphore | None = None
_LLM_SEMAPHORE_INIT_LOCK: asyncio.Lock | None = None

_GENERATION_FAILED_MARKERS = ("generation failed", "LLM returned empty")


async def _get_llm_semaphore() -> asyncio.Semaphore:
    """Lazy semaphore creation — must not be created at module scope.

    Uses an asyncio.Lock to prevent race conditions during initialization.
    The lock itself is lazily created, but its creation is atomic under the GIL
    and only guards the one-time semaphore construction.
    """
    global _LLM_SEMAPHORE, _LLM_SEMAPHORE_INIT_LOCK
    if _LLM_SEMAPHORE is not None:
        return _LLM_SEMAPHORE
    if _LLM_SEMAPHORE_INIT_LOCK is None:
        _LLM_SEMAPHORE_INIT_LOCK = asyncio.Lock()
    async with _LLM_SEMAPHORE_INIT_LOCK:
        if _LLM_SEMAPHORE is None:
            _LLM_SEMAPHORE = asyncio.Semaphore(4)
    return _LLM_SEMAPHORE


# ---------------------------------------------------------------------------
# Passe 1 — per-chapter normalisation (parallel)
# ---------------------------------------------------------------------------

def _pass1_system(chapter_type: str, max_chars: int) -> str:
    return prompt_registry.render(
        "tone_pass1.j2",
        chapter_type=chapter_type,
        max_chars=max_chars,
    )


def _run_pass1_chapter(chapter_tag: str, text: str, *, deal_id: str = "") -> tuple[str, int, bool]:
    """Synchronous Passe 1 for one chapter — called via asyncio.to_thread.

    Returns (revised_text, chars_removed, skipped).
    """
    # Guard: skip rewrite for failed chapters — propagate error as-is
    if text.startswith("*") and any(m in text for m in _GENERATION_FAILED_MARKERS):
        logger.info(
            "tone_normalizer.chapter_diff",
            deal_id=deal_id,
            chapter_id=chapter_tag,
            pass_num=1,
            input_len=len(text),
            output_len=len(text),
            skipped=True,
        )
        return text, 0, True

    chapter_type = get_chapter_type(chapter_tag)
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
        logger.info(
            "tone_normalizer.chapter_diff",
            deal_id=deal_id,
            chapter_id=chapter_tag,
            pass_num=1,
            input_len=len(text),
            output_len=len(revised),
            skipped=False,
        )
        return revised, chars_removed, False
    except Exception as exc:
        logger.warning("TONE_PASS1_FAILED", chapter=chapter_tag, error=str(exc))
        return text, 0, False


async def _pass1_async(chapters: dict[str, str], *, deal_id: str = "") -> tuple[dict[str, str], dict[str, int]]:
    """Passe 1: all chapters in parallel via asyncio.to_thread (max 4 concurrent)."""

    async def _guarded(ch_tag: str, text: str) -> tuple[str, int, bool]:
        async with await _get_llm_semaphore():
            return await asyncio.to_thread(_run_pass1_chapter, ch_tag, text, deal_id=deal_id)

    tasks = {
        ch_tag: _guarded(ch_tag, text)
        for ch_tag, text in chapters.items()
    }

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    revised_chapters: dict[str, str] = {}
    changes: dict[str, int] = {}

    for ch_tag, result in zip(tasks.keys(), results, strict=False):
        if isinstance(result, BaseException):
            logger.warning("TONE_PASS1_GATHER_FAIL", chapter=ch_tag, error=str(result))
            revised_chapters[ch_tag] = chapters[ch_tag]
            changes[ch_tag] = 0
        else:
            revised_text, delta, _skipped = result
            revised_chapters[ch_tag] = revised_text
            changes[ch_tag] = delta

    return revised_chapters, changes


# ---------------------------------------------------------------------------
# Passe 2 — full memo holistic review (sequential)
# ---------------------------------------------------------------------------

_PASS2_EXCERPT_CHARS: int = 1_500


def _run_pass2(
    chapters: dict[str, str],
    critic_output: dict,
    current_signal: str,
    *,
    deal_id: str = "",
) -> dict[str, Any]:
    """Passe 2: lightweight signal-integrity check on chapter excerpts."""
    model = get_model("tone_pass2")
    fatal_flaws_count = len(critic_output.get("fatal_flaws", []))

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
        system_prompt = prompt_registry.render("tone_pass2.j2")
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
                "TONE_PASS2_DEESCALATION_BLOCKED",
                original=current_signal,
                proposed=parsed["signal_final"],
            )
            parsed["signal_final"] = current_signal
            parsed["signal_escalated"] = False
            parsed["escalation_rationale"] = None

        # Paired logging for pass 2 excerpts
        for ch_tag, text in chapters.items():
            logger.info(
                "tone_normalizer.chapter_diff",
                deal_id=deal_id,
                chapter_id=ch_tag,
                pass_num=2,
                input_len=len(text),
                output_len=len(text),
                skipped=False,
            )

        return parsed

    except Exception as exc:
        logger.warning("TONE_PASS2_FAILED", error=str(exc))
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
    *,
    deal_id: str = "",
) -> dict[str, Any]:
    """Run Tone Normalizer (Passe 1 parallel + Passe 2 holistic).

    Parameters
    ----------
    chapter_texts : dict[str, str]
        Mapping of chapter_tag → raw chapter content.
    critic_output : dict
        Critic engine output dict (used for fatal_flaws count in Passe 2).
    current_signal : str
        Current IC recommendation signal: "INVEST" | "CONDITIONAL" | "PASS".
    deal_id : str
        Deal identifier for paired logging.

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
        "TONE_NORMALIZER_START",
        deal_id=deal_id,
        chapters=len(chapter_texts),
        total_chars=total_chars_in,
        signal=current_signal,
    )

    # Passe 1 — parallel per-chapter normalisation
    revised_chapters, pass1_changes = await _pass1_async(chapter_texts, deal_id=deal_id)

    total_delta = sum(pass1_changes.values())
    logger.info(
        "TONE_PASS1_COMPLETE",
        deal_id=deal_id,
        chapters=len(revised_chapters),
        chars_removed=total_delta,
    )

    # Passe 2 — lightweight signal-integrity check
    pass2_result = await asyncio.to_thread(
        _run_pass2, revised_chapters, critic_output, current_signal,
        deal_id=deal_id,
    )

    # Merge: final chapters = pass1 output
    pass2_result["chapters"] = revised_chapters
    pass2_result["pass1_changes"] = pass1_changes

    if pass2_result.get("signal_escalated"):
        logger.warning(
            "TONE_SIGNAL_ESCALATED",
            deal_id=deal_id,
            original=pass2_result["signal_original"],
            final=pass2_result["signal_final"],
            rationale=pass2_result.get("escalation_rationale", ""),
        )
    else:
        logger.info("TONE_PASS2_COMPLETE", deal_id=deal_id, signal=current_signal)

    return pass2_result
