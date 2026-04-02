"""Attribution domain models — wealth-specific wrappers.

Frozen dataclasses for cross-boundary safety.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class BlockAttribution:
    """Attribution for a single allocation block."""

    block_id: str
    sector: str  # block display_name
    portfolio_weight: float
    benchmark_weight: float
    portfolio_return: float
    benchmark_return: float
    allocation_effect: float
    selection_effect: float
    interaction_effect: float
    total_effect: float


@dataclass(frozen=True, slots=True)
class PortfolioAttributionResult:
    """Full attribution for a portfolio profile."""

    profile: str
    start_date: date
    end_date: date
    granularity: str  # "monthly" | "quarterly"
    total_portfolio_return: float
    total_benchmark_return: float
    total_excess_return: float
    allocation_total: float
    selection_total: float
    interaction_total: float
    total_allocation_combined: float  # allocation + interaction for committee
    blocks: tuple[BlockAttribution, ...]
    n_periods: int
    benchmark_available: bool
    benchmark_approach: str  # always "policy"
