"""Frozen dataclasses for fact-sheet PDF generation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True, slots=True)
class ReturnMetrics:
    """Period return metrics for a portfolio."""

    mtd: float | None = None
    qtd: float | None = None
    ytd: float | None = None
    one_year: float | None = None
    three_year: float | None = None
    since_inception: float | None = None
    inception_date: date | None = None
    is_backtest: bool = False


@dataclass(frozen=True, slots=True)
class RiskMetrics:
    """Key risk metrics for display."""

    annualized_vol: float | None = None
    sharpe: float | None = None
    max_drawdown: float | None = None
    cvar_95: float | None = None


@dataclass(frozen=True, slots=True)
class HoldingRow:
    """A single fund holding for the top-holdings table."""

    fund_name: str
    block_id: str
    weight: float


@dataclass(frozen=True, slots=True)
class AllocationBlock:
    """Allocation by block for pie chart."""

    block_id: str
    weight: float


@dataclass(frozen=True, slots=True)
class AttributionRow:
    """Brinson attribution row for institutional report."""

    block_name: str
    allocation_effect: float
    selection_effect: float
    interaction_effect: float
    total_effect: float


@dataclass(frozen=True, slots=True)
class StressRow:
    """Stress scenario result for institutional report."""

    name: str
    start_date: date
    end_date: date
    portfolio_return: float
    max_drawdown: float


@dataclass(frozen=True, slots=True)
class NavPoint:
    """Single NAV data point for time series chart."""

    nav_date: date
    nav: float
    benchmark_nav: float | None = None


@dataclass(frozen=True, slots=True)
class RegimePoint:
    """Regime data point for overlay chart."""

    regime_date: date
    regime: str  # "expansion", "contraction", "crisis"


@dataclass(frozen=True, slots=True)
class FactSheetData:
    """All data needed to render a fact-sheet PDF.

    Built by FactSheetEngine from DB + vertical engine outputs.
    Passed as a frozen bundle to renderers — safe across thread boundaries.
    """

    portfolio_id: uuid.UUID
    portfolio_name: str
    profile: str  # "conservative", "moderate", "growth"
    as_of: date
    inception_date: date | None = None

    # Returns
    returns: ReturnMetrics = field(default_factory=ReturnMetrics)
    benchmark_returns: ReturnMetrics | None = None

    # Risk
    risk: RiskMetrics = field(default_factory=RiskMetrics)

    # Holdings & allocation
    holdings: list[HoldingRow] = field(default_factory=list)
    allocations: list[AllocationBlock] = field(default_factory=list)

    # NAV time series (for chart)
    nav_series: list[NavPoint] = field(default_factory=list)

    # Attribution (institutional only)
    attribution: list[AttributionRow] = field(default_factory=list)

    # Stress (institutional only)
    stress: list[StressRow] = field(default_factory=list)

    # Regime overlay (institutional only)
    regimes: list[RegimePoint] = field(default_factory=list)

    # LLM-generated commentary (set by engine after prompt call)
    manager_commentary: str = ""

    # Benchmark label
    benchmark_label: str = ""
