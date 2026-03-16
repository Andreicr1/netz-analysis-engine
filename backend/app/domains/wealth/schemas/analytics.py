import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


class BacktestRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    run_id: uuid.UUID
    profile: str
    params: dict[str, Any]
    status: str
    results: dict[str, Any] | None = None
    cv_metrics: dict[str, Any] | None = None
    error_message: str | None = None
    started_at: datetime
    completed_at: datetime | None = None


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


class ParetoOptimizeResult(BaseModel):
    profile: str
    recommended_weights: dict[str, float]
    pareto_sharpe: list[float]
    pareto_cvar: list[float]
    n_solutions: int
    seed: int
    input_hash: str
    status: str
