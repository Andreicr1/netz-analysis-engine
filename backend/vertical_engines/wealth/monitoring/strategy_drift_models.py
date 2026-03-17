"""Strategy drift detection domain models.

Frozen dataclasses for cross-boundary safety. These are NOT ORM models —
ORM models live in backend/app/domains/wealth/models/.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MetricDrift:
    """Z-score result for a single metric."""

    metric_name: str
    recent_mean: float
    baseline_mean: float
    baseline_std: float
    z_score: float
    is_anomalous: bool  # |z| > threshold (strict greater-than)


@dataclass(frozen=True, slots=True)
class StrategyDriftResult:
    """Drift detection result for one instrument."""

    instrument_id: str
    instrument_name: str
    status: str  # "stable" | "drift_detected" | "insufficient_data"
    anomalous_count: int
    total_metrics: int
    metrics: tuple[MetricDrift, ...]
    severity: str  # "none" | "moderate" (1-2 metrics) | "severe" (3+ metrics)
    detected_at: str  # ISO datetime


@dataclass(frozen=True, slots=True)
class StrategyDriftScanResult:
    """Scan results for all instruments."""

    scanned_count: int
    alerts: tuple[StrategyDriftResult, ...]  # only drift_detected items, sorted by anomalous_count desc
    all_results: tuple[StrategyDriftResult, ...]  # every instrument (stable + insufficient + drift_detected)
    stable_count: int
    insufficient_data_count: int
    scan_timestamp: str
