"""Shared block-bounds resolution for construction modes.

Single source of truth consumed by both the optimizer constraint builder
(``_build_propose_block_constraints``) and the validation gate context loader
(``build_validation_db_context``).

PR-Q116 hotfix — Codex P1: align fallback bounds with propose-mode.
PR-Q116 hotfix #2 — Codex P1: realize-mode bounds parity (mode-aware).
"""

from __future__ import annotations

from typing import Literal

ModeType = Literal["propose", "realize"]


def resolve_block_bounds(
    *,
    override_min: float | None,
    override_max: float | None,
    excluded_from_portfolio: bool = False,
    drift_min: float | None = None,
    drift_max: float | None = None,
    mode: ModeType = "propose",
) -> tuple[float, float]:
    """Resolve effective bounds for a single allocation block.

    Modes:
    - ``"propose"``: optimizer uses ``[0, 1]`` when overrides NULL
      (no drift dependency).
      Hierarchy: excluded → (0,0) | override present → use them | else (0, 1)
    - ``"realize"``: optimizer uses drift bands when overrides NULL
      (``resolve_effective_bands``).
      Hierarchy: excluded → (0,0) | override present → use them
                | drift present → use them | else (0, 1)

    Validation MUST call this with the SAME mode as the optimizer used,
    or risk false pass/fail (Codex Wave 6 S10 P1 lesson).

    Returns
    -------
    tuple[float, float]
        ``(min_weight, max_weight)``
    """
    if excluded_from_portfolio:
        return (0.0, 0.0)

    if override_min is not None and override_max is not None:
        return (float(override_min), float(override_max))

    # Partial overrides: fill the missing side with its default
    if override_min is not None or override_max is not None:
        return (
            float(override_min) if override_min is not None else 0.0,
            float(override_max) if override_max is not None else 1.0,
        )

    if mode == "realize" and drift_min is not None and drift_max is not None:
        return (float(drift_min), float(drift_max))

    return (0.0, 1.0)
