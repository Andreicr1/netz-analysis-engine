"""Critic prompt builder — compress evidence for critic consumption.

Builds the system prompt and user content for the adversarial critic.
Compresses the chapter content and evidence to fit within token limits.
"""

from __future__ import annotations

from typing import Any

import structlog

from ai_engine.prompts.registry import get_prompt_registry

logger = structlog.get_logger()

_CRITIC_TEMPLATE = "critic/critic_prompt.j2"
_MACRO_TEMPLATE = "critic/macro_consistency.j2"


def build_critic_prompt(
    *,
    chapter_tag: str,
    chapter_content: str,
    evidence_context: dict[str, Any],
    chapter_title: str = "",
) -> tuple[str, str]:
    """Build system and user prompts for the critic.

    Parameters
    ----------
    chapter_tag : str
        Chapter being critiqued.
    chapter_content : str
        Generated chapter markdown content.
    evidence_context : dict
        Evidence pack context for verification.
    chapter_title : str
        Human-readable chapter title.

    Returns
    -------
    tuple[str, str]
        (system_prompt, user_content)
    """
    registry = get_prompt_registry()

    # System prompt from template (with fallback)
    if registry.has_template(_CRITIC_TEMPLATE):
        system_prompt = registry.render(
            _CRITIC_TEMPLATE,
            chapter_tag=chapter_tag,
            chapter_title=chapter_title,
        )
    else:
        system_prompt = _fallback_system_prompt(chapter_tag, chapter_title)

    # User content: compressed chapter + evidence
    user_content = _build_critic_packet(
        chapter_content=chapter_content,
        evidence_context=evidence_context,
    )

    return system_prompt, user_content


def build_macro_consistency_prompt(
    *,
    chapter_content: str,
    macro_snapshot: dict[str, Any],
) -> tuple[str, str]:
    """Build prompts for macro consistency check."""
    registry = get_prompt_registry()

    if registry.has_template(_MACRO_TEMPLATE):
        system_prompt = registry.render(_MACRO_TEMPLATE)
    else:
        system_prompt = (
            "You are a macro-economic consistency checker. Verify that the "
            "analysis is consistent with current macro conditions."
        )

    user_content = (
        f"## Chapter Content\n{chapter_content[:3000]}\n\n"
        f"## Macro Snapshot\n{_format_dict(macro_snapshot)}"
    )

    return system_prompt, user_content


def _fallback_system_prompt(chapter_tag: str, chapter_title: str) -> str:
    """Fallback critic prompt when template is not registered."""
    return (
        "You are an adversarial critic reviewing a chapter of a fund due diligence report.\n\n"
        f"## Chapter: {chapter_title} ({chapter_tag})\n\n"
        "Your role is to identify:\n"
        "1. **Fatal Flaws** — factual errors, logical contradictions, missing critical analysis\n"
        "2. **Material Gaps** — important topics not covered, insufficient depth\n"
        "3. **Optimism Bias** — unsubstantiated positive claims, cherry-picked data\n"
        "4. **Data Quality** — outdated metrics, inconsistent figures, unsupported claims\n\n"
        "Respond with a JSON object:\n"
        "```json\n"
        '{"taxonomy": "ACCEPT|REVISE|ESCALATE", "fatal_flaws": [...], '
        '"material_gaps": [...], "optimism_bias": [...], "data_quality_flags": [...], '
        '"confidence_delta": 0.0, "overall_assessment": "...", "feedback": "..."}\n'
        "```\n\n"
        "Use ACCEPT if the chapter meets quality standards.\n"
        "Use REVISE if specific improvements are needed (provide feedback).\n"
        "Use ESCALATE only for fatal flaws requiring human review."
    )


def _build_critic_packet(
    *,
    chapter_content: str,
    evidence_context: dict[str, Any],
) -> str:
    """Compress chapter + evidence into a critic review packet."""
    parts: list[str] = []

    # Chapter content (truncate for critic consumption)
    parts.append(f"## Chapter Content\n{chapter_content[:5000]}")

    # Fund identity
    fund_name = evidence_context.get("fund_name", "Unknown")
    parts.append(f"\n## Fund: {fund_name}")

    # Key quant metrics for verification
    quant = evidence_context.get("quant_profile", {})
    if quant:
        parts.append("\n## Quant Metrics (for verification)")
        for key in ["sharpe_1y", "return_1y", "cvar_95_3m", "manager_score", "volatility_1y"]:
            val = quant.get(key)
            if val is not None:
                parts.append(f"- {key}: {val}")

    return "\n".join(parts)


def _format_dict(d: dict[str, Any], indent: int = 0) -> str:
    """Format a dict as readable text."""
    lines: list[str] = []
    prefix = "  " * indent
    for k, v in d.items():
        if isinstance(v, dict):
            lines.append(f"{prefix}- {k}:")
            lines.append(_format_dict(v, indent + 1))
        else:
            lines.append(f"{prefix}- {k}: {v}")
    return "\n".join(lines)
