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

    def validate_weights(self) -> bool:
        """Check that weights sum to approximately 1.0."""
        return abs(self.total_weight - 1.0) < 1e-6


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
