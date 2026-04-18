"""PR-A26.2 Section D - propose-mode honours operator overrides.

Exercises ``_build_propose_block_constraints`` directly: given a set
of StrategicAllocation-shaped stubs, asserts the resulting
``BlockConstraint`` list carries the override bounds verbatim, that
excluded blocks collapse to ``[0, 0]`` even with an override, and that
unmarked blocks default to ``[0, 1]``.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domains.wealth.routes.model_portfolios import (
    _build_propose_block_constraints,
)


@dataclass
class _BC:
    block_id: str
    min_weight: float
    max_weight: float


class _Row:
    """Minimal StrategicAllocation stand-in (attribute access only)."""

    def __init__(
        self,
        block_id: str,
        *,
        excluded: bool = False,
        override_min: float | None = None,
        override_max: float | None = None,
    ) -> None:
        self.block_id = block_id
        self.excluded_from_portfolio = excluded
        self.override_min = (
            Decimal(str(override_min)) if override_min is not None else None
        )
        self.override_max = (
            Decimal(str(override_max)) if override_max is not None else None
        )


CANON: list[str] = [
    "na_equity_large", "na_equity_growth", "na_equity_value", "na_equity_small",
    "dm_europe_equity", "dm_asia_equity", "em_equity",
    "fi_us_aggregate", "fi_us_treasury", "fi_us_short_term",
    "fi_us_high_yield", "fi_us_tips", "fi_ig_corporate", "fi_em_debt",
    "alt_real_estate", "alt_gold", "alt_commodities", "cash",
]


def _as_map(constraints) -> dict[str, tuple[float, float]]:
    return {bc.block_id: (bc.min_weight, bc.max_weight) for bc in constraints}


def test_override_bounds_propagate_to_block_constraints() -> None:
    allocations = [_Row(b) for b in CANON]
    # Override only two blocks.
    allocations[0] = _Row("na_equity_large", override_max=0.15)
    allocations[10] = _Row(
        "fi_us_high_yield", override_min=0.02, override_max=0.10,
    )

    constraints, override_blocks = _build_propose_block_constraints(
        allocations=allocations,
        canonical_block_ids=CANON,
        block_constraint_cls=_BC,
    )
    bc_map = _as_map(constraints)

    assert bc_map["na_equity_large"] == (0.0, 0.15)
    assert bc_map["fi_us_high_yield"] == (0.02, 0.10)
    # Unconstrained blocks remain [0, 1].
    assert bc_map["cash"] == (0.0, 1.0)
    assert bc_map["em_equity"] == (0.0, 1.0)

    # Telemetry tag surfaces exactly the two override blocks.
    assert set(override_blocks) == {"na_equity_large", "fi_us_high_yield"}


def test_excluded_block_collapses_to_zero_even_with_override() -> None:
    allocations = [_Row(b) for b in CANON]
    allocations[15] = _Row(
        "alt_gold", excluded=True, override_max=0.25,
    )

    constraints, _ = _build_propose_block_constraints(
        allocations=allocations,
        canonical_block_ids=CANON,
        block_constraint_cls=_BC,
    )
    bc_map = _as_map(constraints)
    assert bc_map["alt_gold"] == (0.0, 0.0)


def test_only_one_bound_set_keeps_other_at_default() -> None:
    allocations = [_Row(b) for b in CANON]
    allocations[0] = _Row("na_equity_large", override_max=0.20)  # min defaults
    allocations[1] = _Row("na_equity_growth", override_min=0.05)  # max defaults

    constraints, _ = _build_propose_block_constraints(
        allocations=allocations,
        canonical_block_ids=CANON,
        block_constraint_cls=_BC,
    )
    bc_map = _as_map(constraints)
    assert bc_map["na_equity_large"] == (0.0, 0.20)
    assert bc_map["na_equity_growth"] == (0.05, 1.0)


def test_no_overrides_at_all_yields_bare_zero_one() -> None:
    allocations = [_Row(b) for b in CANON]
    constraints, overrides = _build_propose_block_constraints(
        allocations=allocations,
        canonical_block_ids=CANON,
        block_constraint_cls=_BC,
    )
    assert overrides == []
    for bc in constraints:
        assert (bc.min_weight, bc.max_weight) == (0.0, 1.0)
