"""Response schemas for risk timeseries endpoint.

Flat [{time, value}] arrays optimized for TradingView chart injection.
"""

from datetime import date
from typing import Any

from pydantic import BaseModel


class TimeseriesPoint(BaseModel):
    time: str  # ISO-8601 date
    value: float


class RegimePoint(BaseModel):
    time: str  # ISO-8601 date
    value: float  # p_high_vol probability
    regime: str  # classified_regime label


class RiskTimeseriesOut(BaseModel):
    instrument_id: str
    ticker: str | None  # resolved from instruments_universe for display only
    from_date: date
    to_date: date
    drawdown: list[dict[str, Any]]  # [{time, value}]
    volatility_garch: list[dict[str, Any]]  # [{time, value}]
    regime_prob: list[dict[str, Any]]  # [{time, value, regime}]
