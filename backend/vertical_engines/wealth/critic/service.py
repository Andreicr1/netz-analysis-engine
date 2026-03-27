"""Critic service — adversarial review orchestrator for DD Reports.

Never-raises contract: returns CriticReport with safe defaults on failure.
Circuit breaker: aborts at 3-minute wall-clock, escalates remaining chapters.

No dd_report/ imports — uses CallOpenAiFn from shared_protocols.py.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from vertical_engines.wealth.critic.models import CriticReport, CriticVerdict
from vertical_engines.wealth.critic.parser import parse_critic_response
from vertical_engines.wealth.critic.prompt_builder import build_critic_prompt
from vertical_engines.wealth.shared_protocols import CallOpenAiFn

logger = structlog.get_logger()

# Default limits
_DEFAULT_MAX_ITERATIONS = 3
_DEFAULT_CIRCUIT_BREAKER_SECONDS = 180  # 3 minutes


def critique_dd_report(
    call_openai_fn: CallOpenAiFn,
    *,
    chapters: list[dict[str, Any]],
    evidence_context: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> CriticReport:
    """Critique all chapters of a DD Report.

    Never raises — returns CriticReport with status='NOT_ASSESSED' on failure.

    Parameters
    ----------
    call_openai_fn : CallOpenAiFn
        Injected LLM call function.
    chapters : list[dict]
        List of chapter dicts with 'tag', 'title', 'content_md' keys.
    evidence_context : dict
        Evidence pack context for verification.
    config : dict
        Critic configuration (max_iterations, circuit_breaker_seconds).

    Returns
    -------
    CriticReport
        Aggregate critic results (frozen dataclass).

    """
    cfg = config or {}
    max_iterations = cfg.get("max_iterations", _DEFAULT_MAX_ITERATIONS)
    circuit_breaker = cfg.get("circuit_breaker_seconds", _DEFAULT_CIRCUIT_BREAKER_SECONDS)

    start_time = time.monotonic()
    verdicts: list[CriticVerdict] = []
    escalated: list[str] = []
    breaker_triggered = False

    for chapter in chapters:
        tag = chapter.get("tag", "")
        content = chapter.get("content_md", "")
        title = chapter.get("title", tag)

        if not content:
            # Skip chapters with no content
            verdicts.append(CriticVerdict(
                chapter_tag=tag,
                taxonomy="ESCALATE",
                overall_assessment="No content to critique",
            ))
            escalated.append(tag)
            continue

        # Check circuit breaker
        elapsed = time.monotonic() - start_time
        if elapsed >= circuit_breaker:
            logger.warning(
                "critic_circuit_breaker_triggered",
                elapsed=elapsed,
                remaining_chapters=[c.get("tag") for c in chapters if c.get("tag") not in [v.chapter_tag for v in verdicts]],
            )
            breaker_triggered = True
            # Escalate remaining chapters
            verdicts.append(CriticVerdict(
                chapter_tag=tag,
                taxonomy="ESCALATE",
                overall_assessment=f"Circuit breaker triggered at {elapsed:.0f}s",
            ))
            escalated.append(tag)
            continue

        # Critique this chapter (with iterations)
        verdict = _critique_chapter(
            call_openai_fn,
            chapter_tag=tag,
            chapter_title=title,
            chapter_content=content,
            evidence_context=evidence_context,
            max_iterations=max_iterations,
            remaining_seconds=circuit_breaker - elapsed,
        )
        verdicts.append(verdict)
        if verdict.escalation_required:
            escalated.append(tag)

    wall_clock = time.monotonic() - start_time

    logger.info(
        "critic_report_completed",
        total_chapters=len(chapters),
        total_verdicts=len(verdicts),
        escalated=escalated,
        wall_clock=round(wall_clock, 1),
        circuit_breaker=breaker_triggered,
    )

    return CriticReport(
        verdicts=verdicts,
        wall_clock_seconds=round(wall_clock, 2),
        circuit_breaker_triggered=breaker_triggered,
        chapters_escalated=escalated,
    )


def _critique_chapter(
    call_openai_fn: CallOpenAiFn,
    *,
    chapter_tag: str,
    chapter_title: str,
    chapter_content: str,
    evidence_context: dict[str, Any],
    max_iterations: int,
    remaining_seconds: float,
) -> CriticVerdict:
    """Critique a single chapter with up to max_iterations.

    Never raises.
    """
    try:
        for iteration in range(1, max_iterations + 1):
            # Per-chapter time budget
            per_chapter_budget = remaining_seconds / max(1, max_iterations - iteration + 1)
            if per_chapter_budget < 5:
                # Not enough time for another iteration
                return CriticVerdict(
                    chapter_tag=chapter_tag,
                    taxonomy="ESCALATE",
                    overall_assessment=f"Time budget exhausted after {iteration - 1} iterations",
                )

            system_prompt, user_content = build_critic_prompt(
                chapter_tag=chapter_tag,
                chapter_content=chapter_content,
                evidence_context=evidence_context,
                chapter_title=chapter_title,
            )

            response = call_openai_fn(
                system_prompt,
                user_content,
                max_tokens=2000,
            )

            raw = response.get("content") or response.get("text") or ""
            verdict = parse_critic_response(raw, chapter_tag=chapter_tag)

            logger.info(
                "critic_iteration_completed",
                chapter_tag=chapter_tag,
                iteration=iteration,
                taxonomy=verdict.taxonomy,
                issues=verdict.total_issues,
            )

            # If ACCEPT or ESCALATE, we're done
            if verdict.taxonomy != "REVISE":
                return verdict

            # If REVISE and this is the last iteration, escalate
            if iteration == max_iterations:
                return CriticVerdict(
                    chapter_tag=chapter_tag,
                    taxonomy="ESCALATE",
                    fatal_flaws=verdict.fatal_flaws,
                    material_gaps=verdict.material_gaps,
                    optimism_bias=verdict.optimism_bias,
                    data_quality_flags=verdict.data_quality_flags,
                    overall_assessment=f"Max iterations ({max_iterations}) reached, escalating",
                    feedback=verdict.feedback,
                )

        # Should not reach here, but just in case
        return CriticVerdict(
            chapter_tag=chapter_tag,
            taxonomy="ACCEPT",
            overall_assessment="Default accept",
        )

    except Exception:
        logger.exception("critic_chapter_failed", chapter_tag=chapter_tag)
        return CriticVerdict(
            chapter_tag=chapter_tag,
            taxonomy="ESCALATE",
            overall_assessment="NOT_ASSESSED — critic failed with exception",
        )
