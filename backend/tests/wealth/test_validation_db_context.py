"""Tests for block-bounds parity between validation and propose/realize modes.

PR-Q116 hotfix — Codex P1: validation fallback bounds must match
``_build_propose_block_constraints`` exactly.

PR-Q116 hotfix #2 — Codex P1: realize-mode bounds parity.  Mode-aware
resolver uses drift bands as fallback in realize mode.
"""

from __future__ import annotations

from typing import Any

from vertical_engines.wealth.model_portfolio.block_bounds import resolve_block_bounds
from vertical_engines.wealth.model_portfolio.validation_gate import (
    ValidationDbContext,
    validate_construction,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _propose_bounds_for(
    *,
    override_min: float | None = None,
    override_max: float | None = None,
    drift_min: float | None = None,
    drift_max: float | None = None,
    excluded: bool = False,
) -> tuple[float, float]:
    """Simulate what _build_propose_block_constraints produces for one block."""
    return resolve_block_bounds(
        override_min=override_min,
        override_max=override_max,
        drift_min=drift_min,
        drift_max=drift_max,
        excluded_from_portfolio=excluded,
        mode="propose",
    )


def _realize_bounds_for(
    *,
    override_min: float | None = None,
    override_max: float | None = None,
    drift_min: float | None = None,
    drift_max: float | None = None,
    excluded: bool = False,
) -> tuple[float, float]:
    """Simulate what build_validation_db_context produces in realize mode."""
    return resolve_block_bounds(
        override_min=float(override_min) if override_min is not None else None,
        override_max=float(override_max) if override_max is not None else None,
        drift_min=float(drift_min) if drift_min is not None else None,
        drift_max=float(drift_max) if drift_max is not None else None,
        excluded_from_portfolio=bool(excluded),
        mode="realize",
    )


_INSTRUMENT_IDS = [
    "11111111-1111-1111-1111-111111111111",
    "22222222-2222-2222-2222-222222222222",
    "33333333-3333-3333-3333-333333333333",
    "44444444-4444-4444-4444-444444444444",
    "55555555-5555-5555-5555-555555555555",
]


def _base_payload() -> dict[str, Any]:
    return {
        "as_of_date": "2026-04-08",
        "weights_proposed": {iid: 0.20 for iid in _INSTRUMENT_IDS},
        "calibration_snapshot": {
            "cvar_limit": 0.05,
            "max_single_fund_weight": 0.25,
            "turnover_cap": 0.30,
            "bl_enabled": False,
            "garch_enabled": False,
        },
        "ex_ante_metrics": {
            "cvar_95": -0.04,
            "expected_return": 0.08,
            "turnover": 0.10,
        },
        "funds": [
            {"instrument_id": iid, "block_id": "na_equity_large", "weight": 0.20}
            for iid in _INSTRUMENT_IDS
        ],
        "stress_results": [
            {"scenario": "gfc_2008", "nav_impact_pct": -0.15},
        ],
        "optimizer_trace": {},
        "statistical_inputs": {},
        "factor_exposure": {"average_r_squared": 0.65},
    }


# ── Tests: propose-mode (original hotfix #1 parity) ─────────────────


class TestValidationBoundsMatchProposeMode:
    """PR-Q116: when override_*/drift_* are NULL, validation must use
    exactly the bounds that _build_propose_block_constraints produces."""

    def test_validation_bounds_match_propose_mode_when_overrides_null(self) -> None:
        """Core P1 regression: NULL overrides → [0.0, 1.0], not target*0.5/1.5."""
        propose = _propose_bounds_for(override_min=None, override_max=None)
        assert propose == (0.0, 1.0), f"propose-mode should default to [0, 1], got {propose}"

    def test_validation_bounds_use_override_min_max_when_present(self) -> None:
        """When operator sets override bounds, both consumers use them."""
        propose = _propose_bounds_for(override_min=0.1, override_max=0.3)
        assert propose == (0.1, 0.3)

    def test_validation_bounds_excluded_block(self) -> None:
        """Excluded blocks collapse to [0, 0] in both paths."""
        propose = _propose_bounds_for(excluded=True, override_min=0.2, override_max=0.5)
        assert propose == (0.0, 0.0)

    def test_partial_override_min_only(self) -> None:
        """Only override_min set — max defaults to 1.0."""
        propose = _propose_bounds_for(override_min=0.05, override_max=None)
        assert propose == (0.05, 1.0)

    def test_partial_override_max_only(self) -> None:
        """Only override_max set — min defaults to 0.0."""
        propose = _propose_bounds_for(override_min=None, override_max=0.4)
        assert propose == (0.0, 0.4)

    def test_propose_mode_ignores_drift_bands(self) -> None:
        """Propose-mode ignores drift_min/drift_max even when set."""
        result = _propose_bounds_for(
            override_min=None, override_max=None,
            drift_min=0.10, drift_max=0.30,
        )
        assert result == (0.0, 1.0), (
            f"propose-mode should ignore drift bands, got {result}"
        )


# ── Tests: realize-mode (hotfix #2) ──────────────────────────────────


class TestRealizeModeBlockBounds:
    """PR-Q116 hotfix #2: realize-mode validation uses drift bands."""

    def test_realize_mode_uses_drift_bounds_when_overrides_null(self) -> None:
        """Core hotfix #2: drift_min=0.10, drift_max=0.30, overrides NULL →
        realize mode returns (0.10, 0.30)."""
        result = _realize_bounds_for(
            override_min=None, override_max=None,
            drift_min=0.10, drift_max=0.30,
        )
        assert result == (0.10, 0.30)

    def test_realize_mode_falls_back_to_zero_one_when_drift_null(self) -> None:
        """Overrides NULL, drift NULL, realize → (0, 1)."""
        result = _realize_bounds_for(
            override_min=None, override_max=None,
            drift_min=None, drift_max=None,
        )
        assert result == (0.0, 1.0)

    def test_override_wins_in_both_modes(self) -> None:
        """Overrides set + drift set → overrides take priority in both."""
        for mode_fn in (_propose_bounds_for, _realize_bounds_for):
            result = mode_fn(
                override_min=0.15, override_max=0.35,
                drift_min=0.10, drift_max=0.50,
            )
            assert result == (0.15, 0.35), f"{mode_fn.__name__} returned {result}"

    def test_excluded_wins_over_drift_in_realize(self) -> None:
        """Excluded blocks are (0, 0) even with drift bounds."""
        result = _realize_bounds_for(
            excluded=True,
            drift_min=0.10, drift_max=0.30,
        )
        assert result == (0.0, 0.0)

    def test_partial_drift_ignored(self) -> None:
        """Only one of drift_min/drift_max set → falls back to (0, 1)."""
        result1 = _realize_bounds_for(drift_min=0.10, drift_max=None)
        assert result1 == (0.0, 1.0)
        result2 = _realize_bounds_for(drift_min=None, drift_max=0.30)
        assert result2 == (0.0, 1.0)


# ── Integration: realize-mode validation catches drift violation ──────


class TestRealizeModeValidationIntegration:
    """End-to-end: realize-mode validation with drift bounds detects violations."""

    def test_realize_mode_validation_catches_drift_violation(self) -> None:
        """A portfolio at 100% in one block violates drift_max=0.30."""
        payload = _base_payload()
        ctx = ValidationDbContext(
            banned_instrument_ids=frozenset(),
            approved_instrument_ids=frozenset(_INSTRUMENT_IDS),
            strategic_targets={"na_equity_large": 0.20},
            block_constraints={"na_equity_large": (0.10, 0.30)},  # drift bounds
            nav_latest_date={iid: "2026-04-07" for iid in _INSTRUMENT_IDS},
            nav_staleness_threshold_days=10,
        )
        result = validate_construction(payload, ctx)
        check_8 = [c for c in result.checks
                    if c.id == "all_block_max_weights_satisfied"]
        assert len(check_8) == 1
        assert check_8[0].passed is False, (
            "Block at 100% should violate drift_max=0.30"
        )

    def test_realize_mode_passes_within_drift_bounds(self) -> None:
        """A portfolio within drift bounds passes."""
        payload = _base_payload()
        # All 5 funds at 20% = 100% in one block, drift allows [0, 1]
        ctx = ValidationDbContext(
            banned_instrument_ids=frozenset(),
            approved_instrument_ids=frozenset(_INSTRUMENT_IDS),
            strategic_targets={"na_equity_large": 1.0},
            block_constraints={"na_equity_large": (0.0, 1.0)},
            nav_latest_date={iid: "2026-04-07" for iid in _INSTRUMENT_IDS},
            nav_staleness_threshold_days=10,
        )
        result = validate_construction(payload, ctx)
        check_7 = [c for c in result.checks
                    if c.id == "all_block_min_weights_satisfied"]
        check_8 = [c for c in result.checks
                    if c.id == "all_block_max_weights_satisfied"]
        assert check_7[0].passed is True
        assert check_8[0].passed is True
