from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


SignificanceLevel = Literal["high", "medium", "low", "none"]


class ResearchMetricPoint(BaseModel):
    label: str
    value: float
    significance: SignificanceLevel = "none"


class MarketSensitivitiesPayload(BaseModel):
    exposures: list[ResearchMetricPoint] = Field(default_factory=list)
    r_squared: float | None = None
    systematic_risk_pct: float | None = None
    as_of_date: date | None = None


class StyleBiasPayload(BaseModel):
    exposures: list[ResearchMetricPoint] = Field(default_factory=list)
    as_of_date: date | None = None


class SingleFundResearchResponse(BaseModel):
    instrument_id: uuid.UUID
    instrument_name: str
    ticker: str | None = None
    market_sensitivities: MarketSensitivitiesPayload
    style_bias: StyleBiasPayload


class ResearchScatterResponse(BaseModel):
    instrument_ids: list[uuid.UUID]
    names: list[str]
    tickers: list[str | None]
    expected_returns: list[float | None]
    tail_risks: list[float | None]
    volatilities: list[float | None]
    strategies: list[str]
    strategy_map: dict[str, str]
    as_of_dates: list[date | None]


class CorrelationMatrixRequest(BaseModel):
    instrument_ids: list[uuid.UUID] = Field(min_length=2, max_length=200)
    window_days: int = Field(default=252, ge=60, le=2520)


class CorrelationMatrixPayload(BaseModel):
    instrument_ids: list[uuid.UUID]
    labels: list[str]
    historical_matrix: list[list[float]]
    structural_matrix: list[list[float]]
    regime_state_at_calc: str | None = None
    effective_window_days: int
    as_of_date: date | None = None
    cache_key: str
    psd_enforced: bool = True
    diagonal_normalized: bool = True


class CorrelationMatrixAccepted(BaseModel):
    job_id: str
    stream_url: str
    status: Literal["accepted"] = "accepted"
    cache_key: str
