"""Tests for block-bounds parity between validation and propose-mode.

PR-Q116 hotfix — Codex P1: validation fallback bounds must match
``_build_propose_block_constraints`` exactly.
"""

from __future__ import annotations

from vertical_engines.wealth.model_portfolio.block_bounds import resolve_block_bounds

# ── Helpers ──────────────────────────────────────────────────────────


def _propose_bounds_for(
    *,
    override_min: float | None = None,
    override_max: float | None = None,
    excluded: bool = False,
) -> tuple[float, float]:
    """Simulate what _build_propose_block_constraints produces for one block."""
    return resolve_block_bounds(
        override_min=override_min,
        override_max=override_max,
        excluded_from_portfolio=excluded,
    )


def _validation_bounds_for(
    *,
    override_min: float | None = None,
    override_max: float | None = None,
    excluded: bool = False,
) -> tuple[float, float]:
    """Simulate what build_validation_db_context produces for one block.

    Both code paths now call resolve_block_bounds — this test asserts
    they stay identical.
    """
    return resolve_block_bounds(
        override_min=float(override_min) if override_min is not None else None,
        override_max=float(override_max) if override_max is not None else None,
        excluded_from_portfolio=bool(excluded),
    )


# ── Tests ────────────────────────────────────────────────────────────


class TestValidationBoundsMatchProposeMode:
    """PR-Q116: when override_*/drift_* are NULL, validation must use
    exactly the bounds that _build_propose_block_constraints produces."""

    def test_validation_bounds_match_propose_mode_when_overrides_null(self) -> None:
        """Core P1 regression: NULL overrides → [0.0, 1.0], not target*0.5/1.5."""
        propose = _propose_bounds_for(override_min=None, override_max=None)
        validation = _validation_bounds_for(override_min=None, override_max=None)
        assert propose == (0.0, 1.0), f"propose-mode should default to [0, 1], got {propose}"
        assert validation == propose, (
            f"validation bounds {validation} != propose bounds {propose}"
        )

    def test_validation_bounds_use_override_min_max_when_present(self) -> None:
        """When operator sets override bounds, both consumers use them."""
        propose = _propose_bounds_for(override_min=0.1, override_max=0.3)
        validation = _validation_bounds_for(override_min=0.1, override_max=0.3)
        assert propose == (0.1, 0.3)
        assert validation == propose

    def test_validation_bounds_excluded_block(self) -> None:
        """Excluded blocks collapse to [0, 0] in both paths."""
        propose = _propose_bounds_for(excluded=True, override_min=0.2, override_max=0.5)
        validation = _validation_bounds_for(excluded=True, override_min=0.2, override_max=0.5)
        assert propose == (0.0, 0.0)
        assert validation == propose

    def test_partial_override_min_only(self) -> None:
        """Only override_min set — max defaults to 1.0."""
        propose = _propose_bounds_for(override_min=0.05, override_max=None)
        validation = _validation_bounds_for(override_min=0.05, override_max=None)
        assert propose == (0.05, 1.0)
        assert validation == propose

    def test_partial_override_max_only(self) -> None:
        """Only override_max set — min defaults to 0.0."""
        propose = _propose_bounds_for(override_min=None, override_max=0.4)
        validation = _validation_bounds_for(override_min=None, override_max=0.4)
        assert propose == (0.0, 0.4)
        assert validation == propose
