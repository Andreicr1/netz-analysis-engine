"""Shared block-bounds resolution for propose-mode construction.

Single source of truth consumed by both the optimizer constraint builder
(``_build_propose_block_constraints``) and the validation gate context loader
(``build_validation_db_context``).

PR-Q116 hotfix — Codex P1: align fallback bounds with propose-mode.
"""

from __future__ import annotations


def resolve_block_bounds(
    *,
    override_min: float | None,
    override_max: float | None,
    excluded_from_portfolio: bool = False,
) -> tuple[float, float]:
    """Resolve effective bounds for a single allocation block.

    Priority:
    1. ``excluded_from_portfolio`` → ``(0.0, 0.0)``
    2. ``override_min`` / ``override_max`` when set by operator
    3. Default ``(0.0, 1.0)`` — full-range freedom in propose-mode

    Returns
    -------
    tuple[float, float]
        ``(min_weight, max_weight)``
    """
    if excluded_from_portfolio:
        return (0.0, 0.0)
    return (
        float(override_min) if override_min is not None else 0.0,
        float(override_max) if override_max is not None else 1.0,
    )
