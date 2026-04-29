"""Strategy drift scanner — detects fund behavior changes via z-score.

Compares recent metric distribution (90d of calc_dates) against a
**non-overlapping** baseline (preceding 270d when recent=90, baseline=360).
Designed to run in asyncio.to_thread(). Pure sync, no DB, no I/O.

Formula:
    z = (μ_recent - μ_baseline) / σ_baseline

Alert when |z| > threshold (strict greater-than: z=2.0 exactly is NOT anomalous).

Hysteresis (C-12):
    Once drift_detected, the close threshold (default 1.5) applies — a fund must
    fall below z_close_threshold to return to stable. Prevents daily flapping
    when z oscillates near the open threshold.

Flat-baseline guard (C-09):
    When σ_baseline < ε (constant metric), an absolute-distance check replaces
    the z-score. Breakouts from flat baselines (e.g., index fund TE → active TE)
    are detected via ``flat_baseline_abs_tol`` (default 0.001 = 10bps).

Severity:
    - "severe" if anomalous_count >= 3 of 7 metrics (~43%)
    - "moderate" if >= 1
    - "none" if 0

NOTE: If METRICS_TO_CHECK is reduced below 3, "severe" becomes unreachable.

Config keys
-----------
recent_window_days : int (default 90)
baseline_window_days : int (default 360)
z_threshold : float (default 2.0)
    Open threshold — z must exceed this to trigger drift_detected from stable.
z_close_threshold : float (default 1.5)
    Close threshold — z must fall below this to return to stable from
    drift_detected. Must be < z_threshold; validated at config resolution.
min_baseline_points : int (default 20)
    Minimum data points in baseline after excluding recent window.
    If the non-overlapping baseline has fewer rows, returns insufficient_data.
min_recent_points : int (default 5)
flat_baseline_abs_tol : float (default 0.001 = 10bps)
    Absolute tolerance for breakout detection when σ_baseline is degenerate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

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
_DEFAULT_Z_CLOSE_THRESHOLD = 1.5
_DEFAULT_MIN_BASELINE_POINTS = 20
_DEFAULT_MIN_RECENT_POINTS = 5
_DEFAULT_FLAT_BASELINE_ABS_TOL = 0.001  # 10bps


def _resolve_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Merge config with defaults and validate constraints.

    Raises
    ------
    ValueError
        If z_close_threshold >= z_threshold (inverted hysteresis band).
    """
    defaults = {
        "recent_window_days": _DEFAULT_RECENT_WINDOW_DAYS,
        "baseline_window_days": _DEFAULT_BASELINE_WINDOW_DAYS,
        "z_threshold": _DEFAULT_Z_THRESHOLD,
        "z_close_threshold": _DEFAULT_Z_CLOSE_THRESHOLD,
        "min_baseline_points": _DEFAULT_MIN_BASELINE_POINTS,
        "min_recent_points": _DEFAULT_MIN_RECENT_POINTS,
        "flat_baseline_abs_tol": _DEFAULT_FLAT_BASELINE_ABS_TOL,
    }
    if config:
        defaults.update(config)

    # Validate hysteresis band: close must be strictly less than open
    if defaults["z_close_threshold"] >= defaults["z_threshold"]:
        raise ValueError(
            f"z_close_threshold ({defaults['z_close_threshold']}) must be "
            f"< z_threshold ({defaults['z_threshold']}). "
            f"Inverted hysteresis band disables drift persistence."
        )

    return defaults


def scan_strategy_drift(
    metrics_history: list[dict[str, Any]],
    instrument_id: str,
    instrument_name: str,
    config: dict[str, Any] | None = None,
    *,
    previous_status: Literal["stable", "drift_detected"] | None = None,
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
        z_threshold, z_close_threshold, min_baseline_points, min_recent_points,
        flat_baseline_abs_tol.
    previous_status : "stable" | "drift_detected" | None
        Previous scan status for this instrument (keyword-only). When
        ``"drift_detected"``, the close threshold (z_close_threshold) is used
        instead of the open threshold — providing hysteresis to prevent
        alert flapping.

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

    # Split into recent and baseline windows by calc_date count.
    # C-01 fix: baseline EXCLUDES recent window to prevent mu_baseline
    # from absorbing the recent shift and biasing z toward zero.
    total_points = len(metrics_history)
    recent_count = min(cfg["recent_window_days"], total_points)
    baseline_count = min(cfg["baseline_window_days"], total_points)

    recent_rows = metrics_history[-recent_count:]
    # Non-overlapping baseline: everything in the baseline window BEFORE the recent window.
    # baseline_rows = metrics_history[-baseline_count : -recent_count]
    # Edge case: if baseline_count <= recent_count, this slice is empty → insufficient_data.
    if baseline_count > recent_count:
        baseline_rows = metrics_history[-baseline_count:-recent_count]
    else:
        baseline_rows = []

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

    # C-12: Hysteresis — select threshold based on previous status
    open_threshold = cfg["z_threshold"]
    close_threshold = cfg["z_close_threshold"]
    threshold_to_apply = (
        close_threshold if previous_status == "drift_detected" else open_threshold
    )

    # Compute z-scores per metric
    metric_drifts: list[MetricDrift] = []
    anomalous_count = 0
    flat_baseline_tol = cfg["flat_baseline_abs_tol"]

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

        # C-09: Flat-baseline guard — σ near zero means metric was constant.
        # Instead of unconditionally marking is_anomalous=False, check
        # absolute distance to detect breakouts from flat baselines
        # (e.g., passive index fund tracking error jumping from 0 to 5%).
        if sigma_baseline < _EPSILON:
            abs_diff = abs(mu_recent - mu_baseline)
            is_anomalous = abs_diff > flat_baseline_tol

            if is_anomalous:
                anomalous_count += 1

            metric_drifts.append(
                MetricDrift(
                    metric_name=metric_name,
                    recent_mean=round(mu_recent, 6),
                    baseline_mean=round(mu_baseline, 6),
                    baseline_std=0.0,
                    z_score=0.0,  # sentinel — σ was degenerate
                    is_anomalous=is_anomalous,
                ),
            )
            continue

        z = (mu_recent - mu_baseline) / sigma_baseline
        # Strict greater-than with hysteresis-aware threshold
        is_anomalous = abs(z) > threshold_to_apply

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
    *,
    previous_statuses: dict[str, str] | None = None,
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
    previous_statuses : dict | None
        instrument_id → previous status ("stable" | "drift_detected").
        Used for hysteresis. When None, all instruments use open threshold.

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
    prev_map = previous_statuses or {}

    for instrument_id, metrics_history in all_instruments_metrics.items():
        name = instrument_names.get(instrument_id, instrument_id)
        prev_status = prev_map.get(instrument_id)
        result = scan_strategy_drift(
            metrics_history,
            instrument_id,
            name,
            config,
            previous_status=prev_status,
        )
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
