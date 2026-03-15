"""Critic LLM response parsing.

Imports only from models.py (leaf dependency).
"""
from __future__ import annotations

from typing import Any

from vertical_engines.credit.critic.models import CriticVerdict


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp a numeric value to [min_val, max_val]."""
    return max(min_val, min(max_val, value))


def parse_critic_response(data: dict[str, Any]) -> CriticVerdict:
    """Parse LLM JSON response into a CriticVerdict dataclass.

    Enforces consistency rules:
    - Fatal flaws → confidence ≤ 0.3
    - Rewrite required if fatal flaws or confidence < 0.4
    """
    fatal_flaws = data.get("fatal_flaws", [])
    confidence = clamp(float(data.get("confidence_score", 0.0)), 0.0, 1.0)

    # Enforce consistency: fatal flaws → confidence ≤ 0.3
    if fatal_flaws and confidence > 0.3:
        confidence = 0.3

    rewrite_required = len(fatal_flaws) > 0 or confidence < 0.4

    return CriticVerdict(
        fatal_flaws=fatal_flaws,
        material_gaps=data.get("material_gaps", []),
        optimism_bias=data.get("optimism_bias", []),
        portfolio_conflicts=data.get("portfolio_conflicts", []),
        citation_issues=data.get("citation_issues", []),
        confidence_score=confidence,
        overall_assessment=data.get("overall_assessment", ""),
        rewrite_required=rewrite_required,
    )
