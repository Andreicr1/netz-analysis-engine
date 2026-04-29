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
    - ``"propose"``: optimizer uses overrides when present, else ``[0, 1]``;
      drift bands are not consulted.
      Hierarchy: excluded → (0,0) | override present → use them | else (0, 1)
    - ``"realize"``: optimizer (``resolve_effective_bands``) builds constraints
      from drift bands only — overrides are NOT applied. The resolver mirrors
      that exactly: overrides are ignored.
      Hierarchy: excluded → (0,0) | drift present → use them | else (0, 1)

    Validation MUST call this with the SAME mode as the optimizer used,
    or risk false pass/fail (Codex Wave 6 S10 P1 lesson).

    Returns
    -------
    tuple[float, float]
        ``(min_weight, max_weight)``
    """
    if excluded_from_portfolio:
        return (0.0, 0.0)

    if mode == "realize":
        # Realize optimizer uses drift bands only; overrides are not applied
        # by ``_run_construction_async`` (see ``alloc_dicts`` build there,
        # which fills each side independently:
        # ``min_weight = drift_min if not None else 0.0``,
        # ``max_weight = drift_max if not None else 1.0``).
        # Validation must mirror that side-by-side fill or it enforces
        # different limits than the optimizer (Codex P1 — false block
        # failures/passes when only one drift side is populated).
        return (
            float(drift_min) if drift_min is not None else 0.0,
            float(drift_max) if drift_max is not None else 1.0,
        )

    if override_min is not None and override_max is not None:
        return (float(override_min), float(override_max))

    # Partial overrides: fill the missing side with its default
    if override_min is not None or override_max is not None:
        return (
            float(override_min) if override_min is not None else 0.0,
            float(override_max) if override_max is not None else 1.0,
        )

    return (0.0, 1.0)
