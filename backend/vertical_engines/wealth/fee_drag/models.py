"""Fee Drag Calculator domain models.

Frozen dataclasses for cross-boundary safety. These are NOT ORM models --
ORM models live in backend/app/domains/wealth/models/.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FeeBreakdown:
    """Fee breakdown for a single instrument."""

    management_fee_pct: float
    performance_fee_pct: float
    other_fees_pct: float  # bid-ask spread, brokerage, etc.
    total_fee_pct: float


@dataclass(frozen=True, slots=True)
class FeeDragResult:
    """Fee drag analysis for a single instrument."""

    instrument_id: uuid.UUID
    instrument_name: str
    instrument_type: str
    gross_expected_return: float  # annualized %
    fee_breakdown: FeeBreakdown
    net_expected_return: float  # gross - total fees
    fee_drag_pct: float  # total_fee / gross (ratio of fees to gross return)
    fee_efficient: bool  # True if fee drag below threshold


@dataclass(frozen=True, slots=True)
class PortfolioFeeDrag:
    """Portfolio-level aggregate fee drag."""

    total_instruments: int
    weighted_gross_return: float
    weighted_net_return: float
    weighted_fee_drag_pct: float
    inefficient_count: int
    results: tuple[FeeDragResult, ...]
