"""Strategy drift scanner — detects fund behavior changes via z-score.

Compares recent metric distribution (90d of calc_dates) against baseline (360d).
Designed to run in asyncio.to_thread(). Pure sync, no DB, no I/O.

Formula:
    z = (μ_recent - μ_baseline) / σ_baseline

Alert when |z| > threshold (strict greater-than: z=2.0 exactly is NOT anomalous).
Severity:
    - "severe" if anomalous_count >= 3 of 7 metrics (~43%)
    - "moderate" if >= 1
    - "none" if 0

NOTE: If METRICS_TO_CHECK is reduced below 3, "severe" becomes unreachable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

from vertical_engines.wealth.monitoring.strategy_drift_models import (
    MetricDrift,
    StrategyDriftResult,
    StrategyDriftScanResult,
)

logger = structlog.get_logger()

# FundRiskMetrics columns to check for behavioral drift
METRICS_TO_CHECK: tuple[str, ...] = (
    "volatility_1y",
    "max_drawdown_1y",
    "sharpe_1y",
    "sortino_1y",
    "alpha_1y",
    "beta_1y",
    "tracking_error_1y",
)

# Guard for σ_baseline near zero — skip metric to avoid division by zero
_EPSILON = 1e-10

# Default config values (overridable via ConfigService)
_DEFAULT_RECENT_WINDOW_DAYS = 90
_DEFAULT_BASELINE_WINDOW_DAYS = 360
_DEFAULT_Z_THRESHOLD = 2.0
_DEFAULT_MIN_BASELINE_POINTS = 20
_DEFAULT_MIN_RECENT_POINTS = 5


def _resolve_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Merge config with defaults."""
    defaults = {
        "recent_window_days": _DEFAULT_RECENT_WINDOW_DAYS,
        "baseline_window_days": _DEFAULT_BASELINE_WINDOW_DAYS,
        "z_threshold": _DEFAULT_Z_THRESHOLD,
        "min_baseline_points": _DEFAULT_MIN_BASELINE_POINTS,
        "min_recent_points": _DEFAULT_MIN_RECENT_POINTS,
    }
    if config:
        defaults.update(config)
    return defaults


def scan_strategy_drift(
    metrics_history: list[dict[str, Any]],
    instrument_id: str,
    instrument_name: str,
    config: dict[str, Any] | None = None,
) -> StrategyDriftResult:
    """Detect behavior change for a single instrument.

    Parameters
    ----------
    metrics_history : list[dict]
        FundRiskMetrics rows as dicts, each with a 'calc_date' key and metric columns.
        Must be sorted by calc_date ascending.
    instrument_id : str
        UUID string of the instrument.
    instrument_name : str
        Display name for alerting.
    config : dict | None
        Overrides for thresholds. Keys: recent_window_days, baseline_window_days,
        z_threshold, min_baseline_points, min_recent_points.

    Returns
    -------
    StrategyDriftResult
        With status "stable", "drift_detected", or "insufficient_data".

    """
    cfg = _resolve_config(config)
    now_dt = datetime.now(UTC)

    if not metrics_history:
        return StrategyDriftResult(
            instrument_id=instrument_id,
            instrument_name=instrument_name,
            status="insufficient_data",
            anomalous_count=0,
            total_metrics=0,
            metrics=(),
            severity="none",
            detected_at=now_dt,
        )

    # Split into recent and baseline windows by calc_date count
    # metrics_history is sorted by calc_date ascending
    total_points = len(metrics_history)
    recent_count = min(cfg["recent_window_days"], total_points)
    baseline_count = min(cfg["baseline_window_days"], total_points)

    recent_rows = metrics_history[-recent_count:]
    baseline_rows = metrics_history[-baseline_count:]

    # Check minimum sample sizes
    if len(baseline_rows) < cfg["min_baseline_points"]:
        return StrategyDriftResult(
            instrument_id=instrument_id,
            instrument_name=instrument_name,
            status="insufficient_data",
            anomalous_count=0,
            total_metrics=0,
            metrics=(),
            severity="none",
            detected_at=now_dt,
        )

    if len(recent_rows) < cfg["min_recent_points"]:
        return StrategyDriftResult(
            instrument_id=instrument_id,
            instrument_name=instrument_name,
            status="insufficient_data",
            anomalous_count=0,
            total_metrics=0,
            metrics=(),
            severity="none",
            detected_at=now_dt,
        )

    # Compute z-scores per metric
    metric_drifts: list[MetricDrift] = []
    anomalous_count = 0

    for metric_name in METRICS_TO_CHECK:
        # Extract values, skip None/NaN
        baseline_vals = [
            float(r[metric_name])
            for r in baseline_rows
            if r.get(metric_name) is not None
            and not (isinstance(r[metric_name], float) and np.isnan(r[metric_name]))
        ]
        recent_vals = [
            float(r[metric_name])
            for r in recent_rows
            if r.get(metric_name) is not None
            and not (isinstance(r[metric_name], float) and np.isnan(r[metric_name]))
        ]

        if not baseline_vals or not recent_vals:
            # Skip metric if no valid data — don't count toward total
            continue

        mu_baseline = float(np.mean(baseline_vals))
        sigma_baseline = float(np.std(baseline_vals, ddof=1)) if len(baseline_vals) > 1 else 0.0
        mu_recent = float(np.mean(recent_vals))

        # Guard: σ near zero → metric is constant, skip
        if sigma_baseline < _EPSILON:
            metric_drifts.append(
                MetricDrift(
                    metric_name=metric_name,
                    recent_mean=round(mu_recent, 6),
                    baseline_mean=round(mu_baseline, 6),
                    baseline_std=0.0,
                    z_score=0.0,
                    is_anomalous=False,
                ),
            )
            continue

        z = (mu_recent - mu_baseline) / sigma_baseline
        # Strict greater-than: z=2.0 exactly is NOT anomalous
        is_anomalous = abs(z) > cfg["z_threshold"]

        if is_anomalous:
            anomalous_count += 1

        metric_drifts.append(
            MetricDrift(
                metric_name=metric_name,
                recent_mean=round(mu_recent, 6),
                baseline_mean=round(mu_baseline, 6),
                baseline_std=round(sigma_baseline, 6),
                z_score=round(z, 4),
                is_anomalous=is_anomalous,
            ),
        )

    # Severity grading
    if anomalous_count >= 3:
        severity = "severe"
    elif anomalous_count >= 1:
        severity = "moderate"
    else:
        severity = "none"

    status = "drift_detected" if anomalous_count > 0 else "stable"

    return StrategyDriftResult(
        instrument_id=instrument_id,
        instrument_name=instrument_name,
        status=status,
        anomalous_count=anomalous_count,
        total_metrics=len(metric_drifts),
        metrics=tuple(metric_drifts),
        severity=severity,
        detected_at=now_dt,
    )


def scan_all_strategy_drift(
    all_instruments_metrics: dict[str, list[dict[str, Any]]],
    instrument_names: dict[str, str],
    config: dict[str, Any] | None = None,
) -> StrategyDriftScanResult:
    """Scan all instruments for strategy drift.

    Parameters
    ----------
    all_instruments_metrics : dict
        instrument_id → list of FundRiskMetrics dicts (sorted by calc_date asc).
    instrument_names : dict
        instrument_id → display name.
    config : dict | None
        Overrides for thresholds.

    Returns
    -------
    StrategyDriftScanResult
        With only drift_detected instruments in alerts.

    """
    now_dt = datetime.now(UTC)
    alerts: list[StrategyDriftResult] = []
    all_results: list[StrategyDriftResult] = []
    stable_count = 0
    insufficient_count = 0

    for instrument_id, metrics_history in all_instruments_metrics.items():
        name = instrument_names.get(instrument_id, instrument_id)
        result = scan_strategy_drift(metrics_history, instrument_id, name, config)
        all_results.append(result)

        if result.status == "drift_detected":
            alerts.append(result)
        elif result.status == "stable":
            stable_count += 1
        else:
            insufficient_count += 1

    # Sort alerts by anomalous_count descending (most severe first)
    alerts.sort(key=lambda a: a.anomalous_count, reverse=True)

    return StrategyDriftScanResult(
        scanned_count=len(all_instruments_metrics),
        alerts=tuple(alerts),
        all_results=tuple(all_results),
        stable_count=stable_count,
        insufficient_data_count=insufficient_count,
        scan_timestamp=now_dt,
    )
