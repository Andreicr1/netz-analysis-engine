"""Schemas for the polymorphic entity analytics vitrine.

Seven metric groups matching eVestment institutional standards:
1. Risk Statistics (Sharpe, Sortino, Calmar, Vol, Alpha, Beta, TE, IR)
2. Drawdown Analysis (series, max, current, recovery)
3. Up/Down Capture Ratios (vs benchmark)
4. Rolling Returns (1M, 3M, 6M, 1Y time series)
5. Return Distribution (histogram, skew, kurtosis, VaR, CVaR)
6. Return Statistics (eVestment Sections I-V: gain/loss, deviations, ratios)
7. Tail Risk (eVestment Section VII: parametric/modified VaR, ETL, ETR, normality)
"""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field

# ── 1. Risk Statistics ──────────────────────────────────────────────────

class RiskStatistics(BaseModel):
    annualized_return: float | None = None
    annualized_volatility: float | None = None
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    calmar_ratio: float | None = None
    max_drawdown: float | None = None
    alpha: float | None = None
    beta: float | None = None
    tracking_error: float | None = None
    information_ratio: float | None = None
    n_observations: int = 0


# ── 2. Drawdown Analysis ───────────────────────────────────────────────

class DrawdownPeriod(BaseModel):
    start_date: str
    trough_date: str
    end_date: str | None = None
    depth: float
    duration_days: int
    recovery_days: int | None = None


class DrawdownAnalysis(BaseModel):
    dates: list[str]
    values: list[float]
    max_drawdown: float | None = None
    current_drawdown: float | None = None
    longest_duration_days: int | None = None
    avg_recovery_days: float | None = None
    worst_periods: list[DrawdownPeriod] = Field(default_factory=list)


# ── 3. Capture Ratios ──────────────────────────────────────────────────

class CaptureRatios(BaseModel):
    up_capture: float | None = None
    down_capture: float | None = None
    up_number_ratio: float | None = None
    down_number_ratio: float | None = None
    up_periods: int = 0
    down_periods: int = 0
    benchmark_source: str = "spy_fallback"  # "param" | "block" | "spy_fallback"
    benchmark_label: str = "SPY"


# ── 4. Rolling Returns ─────────────────────────────────────────────────

class RollingSeries(BaseModel):
    window_label: str  # "1M", "3M", "6M", "1Y"
    dates: list[str]
    values: list[float]


class RollingReturns(BaseModel):
    series: list[RollingSeries] = Field(default_factory=list)


# ── 5. Return Distribution ─────────────────────────────────────────────

class ReturnDistribution(BaseModel):
    bin_edges: list[float]
    bin_counts: list[int]
    mean: float | None = None
    std: float | None = None
    skewness: float | None = None
    kurtosis: float | None = None
    var_95: float | None = None
    cvar_95: float | None = None


# ── 6. Return Statistics (eVestment Sections I-V) ─────────────────────

class ReturnStatistics(BaseModel):
    arithmetic_mean_monthly: float | None = None
    geometric_mean_monthly: float | None = None
    avg_monthly_gain: float | None = None
    avg_monthly_loss: float | None = None
    gain_loss_ratio: float | None = None
    gain_std_dev: float | None = None
    loss_std_dev: float | None = None
    downside_deviation: float | None = None
    semi_deviation: float | None = None
    sterling_ratio: float | None = None
    omega_ratio: float | None = None
    treynor_ratio: float | None = None
    jensen_alpha: float | None = None
    up_percentage_ratio: float | None = None
    down_percentage_ratio: float | None = None
    r_squared: float | None = None


# ── 7. Tail Risk (eVestment Section VII) ──────────────────────────────

class TailRiskMetrics(BaseModel):
    var_parametric_90: float | None = None
    var_parametric_95: float | None = None
    var_parametric_99: float | None = None
    var_modified_95: float | None = None
    var_modified_99: float | None = None
    etl_95: float | None = None
    etl_modified_95: float | None = None
    etr_95: float | None = None
    starr_ratio: float | None = None
    rachev_ratio: float | None = None
    jarque_bera_stat: float | None = None
    jarque_bera_pvalue: float | None = None
    is_normal: bool | None = None


# ── 8. Insider Sentiment (Alternative Data) ──────────────────────────────

class InsiderSummary(BaseModel):
    buy_value: float = 0.0
    sell_value: float = 0.0


class InsiderData(BaseModel):
    insider_sentiment_score: float | None = None
    insider_summary: InsiderSummary


# ── Unified Response ────────────────────────────────────────────────────

class EntityAnalyticsResponse(BaseModel):
    entity_id: uuid.UUID
    entity_type: str  # "instrument" | "model_portfolio"
    entity_name: str
    as_of_date: date
    window: str = "1y"
    risk_statistics: RiskStatistics
    drawdown: DrawdownAnalysis
    capture: CaptureRatios
    rolling_returns: RollingReturns
    distribution: ReturnDistribution
    return_statistics: ReturnStatistics | None = None  # Group 6
    tail_risk: TailRiskMetrics | None = None  # Group 7
    insider_data: InsiderData | None = None  # Group 8 (Alternative Data)
