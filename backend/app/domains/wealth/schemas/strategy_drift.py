"""Pydantic schemas for strategy drift detection API."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator


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


class DriftEventOut(BaseModel):
    """Single drift event from strategy_drift_alerts history."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    instrument_id: UUID
    status: str
    severity: str
    anomalous_count: int
    total_metrics: int
    metric_details: list[dict[str, Any]] | None = None
    is_current: bool = False
    detected_at: datetime
    created_at: datetime | None = None
    snapshot_date: date | None = None
    drift_magnitude: Decimal | None = None
    drift_threshold: Decimal | None = None
    rebalance_triggered: bool | None = None
    breached: bool = False
    asset_class_breakdown: list[dict[str, Any]] | None = None

    @model_validator(mode="after")
    def derive_computed_fields(self) -> DriftEventOut:
        if self.status in ("breach", "critical"):
            self.breached = True
        if self.asset_class_breakdown is None and self.metric_details:
            self.asset_class_breakdown = self.metric_details
        return self


class DriftHistoryOut(BaseModel):
    """Drift history for a single instrument (mapped from 'profile' concept)."""

    instrument_id: UUID
    instrument_name: str
    events: list[DriftEventOut]
    total: int
    computed_at: datetime | None = None
