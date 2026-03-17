"""Pydantic schemas for strategy drift detection API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MetricDriftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    metric_name: str
    recent_mean: float
    baseline_mean: float
    baseline_std: float
    z_score: float
    is_anomalous: bool


class StrategyDriftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    alert_type: Literal["behavior_change"] = "behavior_change"  # G5: discriminator for frontend union
    instrument_id: UUID
    instrument_name: str
    status: str
    anomalous_count: int
    total_metrics: int
    metrics: list[MetricDriftRead]
    severity: str
    detected_at: datetime


class StrategyDriftScanRead(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scanned_count: int
    alerts: list[StrategyDriftRead]
    stable_count: int
    insufficient_data_count: int
    scan_timestamp: datetime
