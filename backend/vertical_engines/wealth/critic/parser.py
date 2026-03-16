"""Critic response parser — extract structured verdicts from LLM output.

Parses the critic's LLM response into a CriticVerdict. Handles
malformed responses gracefully (never-raises contract).
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from ai_engine.governance.output_safety import sanitize_llm_text
from vertical_engines.wealth.critic.models import CriticVerdict

logger = structlog.get_logger()


def parse_critic_response(
    raw_response: str,
    *,
    chapter_tag: str,
) -> CriticVerdict:
    """Parse a critic LLM response into a CriticVerdict.

    Attempts JSON parsing first, then falls back to text analysis.
    Never raises — returns a safe default verdict on parse failure.

    Parameters
    ----------
    raw_response : str
        Raw LLM output from the critic.
    chapter_tag : str
        Chapter being critiqued (for logging).

    Returns
    -------
    CriticVerdict
        Parsed verdict (frozen dataclass).
    """
    sanitized = sanitize_llm_text(raw_response) or ""

    # Try JSON parsing first
    verdict = _try_json_parse(sanitized, chapter_tag)
    if verdict:
        return verdict

    # Fallback: text analysis
    return _text_analysis_parse(sanitized, chapter_tag)


def _try_json_parse(text: str, chapter_tag: str) -> CriticVerdict | None:
    """Attempt to parse structured JSON from the critic response."""
    # Look for JSON block in response
    json_start = text.find("{")
    json_end = text.rfind("}") + 1

    if json_start < 0 or json_end <= json_start:
        return None

    try:
        data = json.loads(text[json_start:json_end])
    except json.JSONDecodeError:
        return None

    taxonomy = data.get("taxonomy", data.get("verdict", "ACCEPT")).upper()
    if taxonomy not in ("ACCEPT", "REVISE", "ESCALATE"):
        taxonomy = "ACCEPT"

    return CriticVerdict(
        chapter_tag=chapter_tag,
        taxonomy=taxonomy,
        fatal_flaws=_ensure_list(data.get("fatal_flaws", [])),
        material_gaps=_ensure_list(data.get("material_gaps", [])),
        optimism_bias=_ensure_list(data.get("optimism_bias", [])),
        data_quality_flags=_ensure_list(data.get("data_quality_flags", [])),
        confidence_delta=float(data.get("confidence_delta", 0.0)),
        overall_assessment=str(data.get("overall_assessment", "")),
        feedback=str(data.get("feedback", "")),
    )


def _text_analysis_parse(text: str, chapter_tag: str) -> CriticVerdict:
    """Fallback: derive verdict from text analysis."""
    upper = text.upper()

    # Determine taxonomy from keywords
    if "ESCALATE" in upper or "FATAL" in upper:
        taxonomy = "ESCALATE"
    elif "REVISE" in upper or "REWRITE" in upper or "IMPROVE" in upper:
        taxonomy = "REVISE"
    else:
        taxonomy = "ACCEPT"

    return CriticVerdict(
        chapter_tag=chapter_tag,
        taxonomy=taxonomy,
        overall_assessment=text[:500],
        feedback=text,
    )


def _ensure_list(val: Any) -> list[dict[str, str]]:
    """Ensure a value is a list of dicts."""
    if not isinstance(val, list):
        return []
    result = []
    for item in val:
        if isinstance(item, dict):
            result.append({str(k): str(v) for k, v in item.items()})
        elif isinstance(item, str):
            result.append({"description": item})
    return result
