"""Pydantic schemas for strategy drift detection API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
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
    # TODO: snapshot_date — not in model yet
    # TODO: drift_magnitude — not in model yet
    # TODO: threshold — not in model yet
    # TODO: breached — not in model yet
    # TODO: rebalance_triggered — not in model yet
    # TODO: asset_class_breakdown — not in model yet


class DriftHistoryOut(BaseModel):
    """Drift history for a single instrument (mapped from 'profile' concept)."""

    instrument_id: UUID
    instrument_name: str
    events: list[DriftEventOut]
    total: int
    # TODO: computed_at — no model-level field; using query time instead
    computed_at: datetime | None = None
