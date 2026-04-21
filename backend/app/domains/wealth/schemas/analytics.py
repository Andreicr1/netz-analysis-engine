import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BacktestParams(BaseModel):
    """Typed, bounded parameters for a backtest run.

    ``extra="forbid"`` prevents unknown keys from being stored in the
    ``backtest_runs.params`` JSONB column (storage-amplification guard).
    """

    model_config = ConfigDict(extra="forbid")

    cv: bool = False
    gap: int = Field(default=2, ge=1, le=63, description="Walk-forward gap in trading days (1–63)")
    n_splits: int = Field(default=5, ge=2, le=20, description="Number of TimeSeriesSplit folds (2–20)")


class BacktestRequest(BaseModel):
    profile: str
    params: BacktestParams = Field(default_factory=BacktestParams)


class BacktestFoldMetrics(BaseModel):
    model_config = ConfigDict(extra="ignore")
    fold: int
    train_start: date | None = None
    train_end: date | None = None
    test_start: date | None = None
    test_end: date | None = None
    sharpe: float | None = None
    cvar_95: float | None = None
    max_drawdown: float | None = None
    n_obs: int = 0


class BacktestResultDetail(BaseModel):
    model_config = ConfigDict(extra="ignore")
    folds: list[BacktestFoldMetrics] = []
    mean_sharpe: float | None = None
    std_sharpe: float | None = None
    positive_folds: int = 0
    n_splits_computed: int = 0


class BacktestRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    run_id: uuid.UUID
    profile: str
    params: dict[str, Any]
    status: str
    results: BacktestResultDetail | None = None
    cv_metrics: dict[str, Any] | None = None
    error_message: str | None = None
    started_at: datetime
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def coerce_results(self) -> "BacktestRunRead":
        if self.results and isinstance(self.results, dict):
            self.results = BacktestResultDetail(**self.results)
        return self


class OptimizeRequest(BaseModel):
    profile: str
    expected_returns: dict[str, float] | None = None
    constraints: dict[str, Any] | None = None


class OptimizeResult(BaseModel):
    profile: str
    weights: dict[str, float]
    expected_return: float | None = None
    expected_risk: float | None = None
    sharpe_ratio: float | None = None


class CorrelationMatrix(BaseModel):
    blocks: list[str]
    matrix: list[list[float]]
    as_of_date: date | None = None


class RollingCorrelationResult(BaseModel):
    dates: list[str]
    values: list[float]
    instrument_a: str
    instrument_b: str


class ParetoOptimizeResult(BaseModel):
    profile: str
    recommended_weights: dict[str, float]
    pareto_sharpe: list[float]
    pareto_cvar: list[float]
    n_solutions: int
    seed: int
    input_hash: str
    status: str
    job_id: str | None = None


# ── Risk Budgeting (eVestment p.43-44) ────────────────────────────────


class FundRiskBudgetRead(BaseModel):
    block_id: str
    block_name: str
    weight: float
    mean_return: float
    mctr: float | None = None
    pctr: float | None = None
    mcetl: float | None = None
    pcetl: float | None = None
    implied_return_vol: float | None = None
    implied_return_etl: float | None = None
    difference_vol: float | None = None
    difference_etl: float | None = None


class RiskBudgetResponse(BaseModel):
    profile: str
    portfolio_volatility: float
    portfolio_etl: float
    portfolio_starr: float | None = None
    funds: list[FundRiskBudgetRead] = Field(default_factory=list)
    as_of_date: date | None = None


# ── Factor Analysis (eVestment p.46) ──────────────────────────────────


class FactorContribution(BaseModel):
    factor_label: str
    pct_contribution: float


class FactorAnalysisResponse(BaseModel):
    profile: str
    data_available: bool = True
    systematic_risk_pct: float = 0.0
    specific_risk_pct: float = 0.0
    factor_contributions: list[FactorContribution] = Field(default_factory=list)
    r_squared: float = 0.0
    portfolio_factor_exposures: dict[str, float] = Field(default_factory=dict)
    as_of_date: date | None = None


# ── Monte Carlo Simulation ───────────────────────────────────────────


class MonteCarloConfidenceBar(BaseModel):
    horizon: str
    horizon_days: int
    pct_5: float
    pct_10: float
    pct_25: float
    pct_50: float
    pct_75: float
    pct_90: float
    pct_95: float
    mean: float


class MonteCarloRequest(BaseModel):
    entity_id: uuid.UUID
    n_simulations: int = Field(default=10_000, ge=1_000, le=100_000)
    statistic: str = Field(default="max_drawdown", pattern="^(max_drawdown|return|sharpe)$")
    horizons: list[int] | None = None


class MonteCarloResponse(BaseModel):
    entity_id: uuid.UUID
    entity_name: str
    n_simulations: int
    statistic: str
    percentiles: dict[str, float] = Field(default_factory=dict)
    mean: float
    median: float
    std: float
    historical_value: float
    confidence_bars: list[MonteCarloConfidenceBar] = Field(default_factory=list)


# ── Peer Group Rankings (eVestment Section IV) ───────────────────────


class PeerRankingRead(BaseModel):
    metric_name: str
    value: float | None = None
    percentile: float = 0.0
    quartile: int = 4
    peer_count: int = 0
    peer_median: float = 0.0
    peer_p25: float = 0.0
    peer_p75: float = 0.0


class PeerGroupResponse(BaseModel):
    entity_id: uuid.UUID
    entity_name: str
    strategy_label: str
    peer_count: int = 0
    rankings: list[PeerRankingRead] = Field(default_factory=list)
    as_of_date: date | None = None


# ── Active Share (eVestment p.73) ────────────────────────────────────


class ActiveShareResponse(BaseModel):
    entity_id: uuid.UUID
    entity_name: str
    active_share: float
    overlap: float
    active_share_efficiency: float | None = None
    n_portfolio_positions: int = 0
    n_benchmark_positions: int = 0
    n_common_positions: int = 0
    as_of_date: date | None = None
