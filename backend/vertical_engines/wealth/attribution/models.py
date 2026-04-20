"""Attribution domain models — wealth-specific.

Two families:
  - Portfolio-level Brinson-Fachler (BlockAttribution, PortfolioAttributionResult) —
    consumed by strategic allocation attribution routes/fact sheets.
  - Fund-level rail cascade (AttributionRequest, FundAttributionResult,
    ReturnsBasedResult, StyleExposure, RailBadge) — consumed by DD ch.4.

Frozen dataclasses for cross-boundary safety.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID


@dataclass(frozen=True, slots=True)
class BlockAttribution:
    """Attribution for a single allocation block (portfolio-level)."""

    block_id: str
    sector: str
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
    """Full attribution for a portfolio profile (policy benchmark)."""

    profile: str
    start_date: date
    end_date: date
    granularity: str
    total_portfolio_return: float
    total_benchmark_return: float
    total_excess_return: float
    allocation_total: float
    selection_total: float
    interaction_total: float
    total_allocation_combined: float
    blocks: tuple[BlockAttribution, ...]
    n_periods: int
    benchmark_available: bool
    benchmark_approach: str


# ---------------------------------------------------------------------------
# Fund-level attribution rail cascade (PR-Q3 and onward)
# ---------------------------------------------------------------------------


class RailBadge(str, enum.Enum):
    """Attribution confidence rail used to render DD ch.4.

    Netz-owned enum. Frontend maps to sanitized copy — never leaks the raw
    quant term (Sharpe regression, Brinson-Fachler, IPCA factor model).
    """

    RAIL_HOLDINGS = "RAIL_HOLDINGS"
    RAIL_IPCA = "RAIL_IPCA"
    RAIL_PROXY = "RAIL_PROXY"
    RAIL_RETURNS = "RAIL_RETURNS"
    RAIL_NONE = "RAIL_NONE"


@dataclass(frozen=True, slots=True)
class StyleExposure:
    """Single style basket exposure (ticker -> weight)."""

    ticker: str
    weight: float


@dataclass(frozen=True, slots=True)
class ReturnsBasedResult:
    """Output of Sharpe 1992 returns-based style regression.

    When ``degraded`` is True, the remaining numeric fields are zeros and
    ``degraded_reason`` carries the machine-readable cause (solver status,
    ``insufficient_history``, ``rank_deficient``, ``no_variance``, ...).
    """

    exposures: tuple[StyleExposure, ...]
    r_squared: float
    tracking_error_annualized: float
    confidence: float
    n_months: int
    degraded: bool = False
    degraded_reason: str | None = None


@dataclass(frozen=True, slots=True)
class AttributionRequest:
    """Input for the fund-level attribution dispatcher."""

    fund_instrument_id: UUID
    asof: date
    lookback_months: int = 60
    style_tickers: tuple[str, ...] = (
        "SPY", "IWM", "EFA", "EEM", "AGG", "HYG", "LQD",
    )
    min_months: int = 36


@dataclass(frozen=True, slots=True)
class FundAttributionResult:
    """Dispatcher output — which rail ran and its payload.

    Only one of (returns_based, holdings_based, proxy, ipca) is populated
    per call. When ``badge == RAIL_NONE``, all rails are None and
    ``reason`` explains why (``insufficient_history``, ``solver_failed``,
    ``no_data`` …).
    """

    fund_instrument_id: UUID
    asof: date
    badge: RailBadge
    returns_based: ReturnsBasedResult | None = None
    holdings_based: object | None = None  # PR-Q4
    proxy: object | None = None  # PR-Q5
    ipca: object | None = None  # PR-Q9
    reason: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
