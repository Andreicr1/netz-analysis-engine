"""Rebalancing Engine domain models.

Frozen dataclasses for cross-boundary safety. These are NOT ORM models --
ORM models live in backend/app/domains/wealth/models/.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RebalanceImpact:
    """Impact assessment when an instrument is removed or regime changes."""

    instrument_id: uuid.UUID
    affected_portfolios: tuple[uuid.UUID, ...]  # model portfolio IDs
    weight_gap: float  # weight of removed instrument (0.0-1.0)
    trigger: str  # "deactivation" | "regime_change"


@dataclass(frozen=True, slots=True)
class WeightProposal:
    """Proposed weight redistribution for a single portfolio."""

    portfolio_id: uuid.UUID
    old_weights: dict[str, float]  # block_id -> weight
    new_weights: dict[str, float]  # block_id -> weight
    cvar_before: float
    cvar_after: float
    feasible: bool
    reason: str | None  # None if feasible, explanation if not


@dataclass(frozen=True, slots=True)
class RebalanceResult:
    """Full rebalance computation result."""

    impact: RebalanceImpact
    proposals: tuple[WeightProposal, ...]
    all_feasible: bool
    computed_at: datetime
