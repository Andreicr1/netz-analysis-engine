"""Pydantic schemas for correlation regime API."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class InstrumentCorrelationRead(BaseModel):
    model_config = ConfigDict(extra="ignore")

    instrument_a_id: UUID
    instrument_a_name: str
    instrument_b_id: UUID
    instrument_b_name: str
    current_correlation: float
    baseline_correlation: float
    correlation_change: float
    is_contagion: bool


class ConcentrationRead(BaseModel):
    model_config = ConfigDict(extra="ignore")

    eigenvalues: list[float]
    explained_variance_ratios: list[float]
    first_eigenvalue_ratio: float
    concentration_status: str
    diversification_ratio: float
    dr_alert: bool
    absorption_ratio: float
    absorption_status: str


class CorrelationRegimeRead(BaseModel):
    model_config = ConfigDict(extra="ignore")

    profile: str
    instrument_count: int
    window_days: int
    correlation_matrix: list[list[float]]
    instrument_labels: list[str]
    contagion_pairs: list[InstrumentCorrelationRead]
    concentration: ConcentrationRead
    average_correlation: float
    baseline_average_correlation: float
    regime_shift_detected: bool
    computed_at: datetime


class PairCorrelationTimeseriesRead(BaseModel):
    model_config = ConfigDict(extra="ignore")

    instrument_a_id: UUID
    instrument_a_name: str
    instrument_b_id: UUID
    instrument_b_name: str
    dates: list[str]
    correlations: list[float]
    window_days: int
