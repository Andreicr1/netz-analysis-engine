"""Frozen dataclasses for model portfolio operations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True, slots=True)
class FundWeight:
    """A single fund's weight in a portfolio composition."""

    instrument_id: uuid.UUID
    fund_name: str
    block_id: str
    weight: float
    score: float


@dataclass(frozen=True, slots=True)
class PortfolioComposition:
    """Result of portfolio construction — per-fund weights summing to 1.0."""

    profile: str
    funds: list[FundWeight] = field(default_factory=list)
    total_weight: float = 0.0
    optimization: OptimizationMeta | None = None

    def validate_weights(self) -> bool:
        """Check that weights sum to approximately 1.0."""
        return abs(self.total_weight - 1.0) < 1e-6


@dataclass(frozen=True, slots=True)
class OptimizationMeta:
    """Metadata from the CLARABEL/NSGA-II optimizer attached to a composition."""

    expected_return: float
    portfolio_volatility: float
    sharpe_ratio: float
    solver: str  # "CLARABEL", "SCS", "heuristic_fallback"
    status: str  # "optimal", "infeasible", "solver_failed", "fallback"
    cvar_95: float | None = None  # parametric CVaR (negative = loss)
    cvar_limit: float | None = None
    cvar_within_limit: bool = True


@dataclass(frozen=True, slots=True)
class FoldMetrics:
    """Metrics for a single backtest fold."""

    fold: int
    sharpe: float | None
    cvar_95: float | None
    max_drawdown: float | None
    n_obs: int


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Result of walk-forward backtesting."""

    portfolio_id: uuid.UUID | None
    lookback_days: int
    folds: list[FoldMetrics] = field(default_factory=list)
    mean_sharpe: float | None = None
    std_sharpe: float | None = None
    positive_folds: int = 0
    total_folds: int = 0
    inception_date: date | None = None
    youngest_fund_start: date | None = None


@dataclass(frozen=True, slots=True)
class LiveNAV:
    """Result of live NAV computation."""

    portfolio_id: uuid.UUID
    as_of: date
    nav: float
    daily_return: float | None = None
    inception_nav: float = 1000.0


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    """Result for a single stress scenario."""

    name: str
    start_date: date
    end_date: date
    portfolio_return: float
    max_drawdown: float
    recovery_days: int | None = None


@dataclass(frozen=True, slots=True)
class StressResult:
    """Result of stress scenario analysis."""

    portfolio_id: uuid.UUID | None
    scenarios: list[ScenarioResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Construction Advisor dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BlockInfo:
    """Lightweight block metadata extracted from AllocationBlock ORM."""

    block_id: str
    display_name: str
    asset_class: str
    benchmark_ticker: str | None = None


@dataclass(frozen=True, slots=True)
class BlockGap:
    """A single allocation block that is missing or underweight."""

    block_id: str
    display_name: str
    asset_class: str
    target_weight: float
    current_weight: float
    gap_weight: float
    priority: int
    reason: str


@dataclass(frozen=True, slots=True)
class CoverageAnalysis:
    """Summary of how well the portfolio covers strategic allocation blocks."""

    total_blocks: int
    covered_blocks: int
    covered_pct: float
    block_gaps: list[BlockGap] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class FundCandidate:
    """Pre-fetched candidate fund data (extracted from ORM before thread dispatch)."""

    instrument_id: str
    name: str
    ticker: str | None
    block_id: str
    strategy_label: str | None
    volatility_1y: float | None
    sharpe_1y: float | None
    manager_score: float | None
    in_universe: bool
    external_id: str  # CIK or ISIN


@dataclass(frozen=True, slots=True)
class CandidateFund:
    """A scored candidate fund with projected CVaR impact."""

    block_id: str
    instrument_id: str
    name: str
    ticker: str | None
    strategy_label: str | None
    volatility_1y: float | None
    correlation_with_portfolio: float
    overlap_pct: float
    projected_cvar_95: float | None
    cvar_improvement: float  # (current - projected) / abs(current)
    in_universe: bool
    external_id: str
    has_holdings_data: bool = True


@dataclass(frozen=True, slots=True)
class MinimumViableSet:
    """Smallest set of funds that brings CVaR within the profile limit."""

    funds: list[str]  # instrument_ids
    projected_cvar_95: float
    projected_within_limit: bool
    blocks_filled: list[str]
    search_method: str  # "brute_force" or "greedy_with_swap"


@dataclass(frozen=True, slots=True)
class AlternativeProfile:
    """An alternative risk profile where the current portfolio would pass."""

    profile: str
    cvar_limit: float
    current_cvar_would_pass: bool


@dataclass(frozen=True, slots=True)
class ConstructionAdvice:
    """Full advisor response — block gaps, candidates, projections, MVS."""

    portfolio_id: str
    profile: str
    current_cvar_95: float
    cvar_limit: float
    cvar_gap: float
    coverage: CoverageAnalysis
    candidates: list[CandidateFund] = field(default_factory=list)
    minimum_viable_set: MinimumViableSet | None = None
    alternative_profiles: list[AlternativeProfile] = field(default_factory=list)
    projected_cvar_is_heuristic: bool = True
