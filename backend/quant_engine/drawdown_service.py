"""Drawdown analysis service.

Pure sync computation — no I/O, no DB access. Receives NAV arrays and dates,
returns drawdown series and period decomposition.

Reusable across entity_analytics, LongFormReport, fact_sheet, track_record.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np


@dataclass(frozen=True, slots=True)
class DrawdownPeriodResult:
    """A single drawdown episode with start, trough, optional recovery."""

    start_date: date
    trough_date: date
    end_date: date | None
    depth: float
    duration_days: int
    recovery_days: int | None


@dataclass(frozen=True, slots=True)
class DrawdownResult:
    """Full drawdown analysis: series + period decomposition + summary stats."""

    series: np.ndarray  # drawdown values aligned to input dates
    max_drawdown: float
    current_drawdown: float
    periods: list[DrawdownPeriodResult]
    longest_duration_days: int | None
    avg_recovery_days: float | None


def compute_drawdown_series(navs: np.ndarray) -> np.ndarray:
    """Compute drawdown series from NAV array.

    Returns array of same length as ``navs`` with values in [-1, 0].
    """
    if len(navs) == 0:
        return np.array([])
    running_max = np.maximum.accumulate(navs)
    return (navs - running_max) / np.where(running_max > 0, running_max, 1.0)


def extract_drawdown_periods(
    dates: list[date],
    dd_series: np.ndarray,
    top_n: int = 5,
) -> list[DrawdownPeriodResult]:
    """Extract worst drawdown periods ranked by depth (most negative first).

    Period start is the index of the most recent peak (dd == 0) preceding the
    drawdown, matching institutional reporting conventions where duration
    spans peak-to-recovery, not first-loss-to-recovery.
    """
    periods: list[DrawdownPeriodResult] = []
    in_dd = False
    last_peak_idx = 0
    start_idx = 0
    trough_idx = 0
    trough_val = 0.0

    for i, v in enumerate(dd_series):
        if v == 0:
            last_peak_idx = i

        if v < 0:
            if not in_dd:
                in_dd = True
                start_idx = last_peak_idx
                trough_idx = i
                trough_val = v
            elif v < trough_val:
                trough_idx = i
                trough_val = v
        elif in_dd:
            periods.append(DrawdownPeriodResult(
                start_date=dates[start_idx],
                trough_date=dates[trough_idx],
                end_date=dates[i],
                depth=round(float(trough_val), 6),
                duration_days=(dates[i] - dates[start_idx]).days,
                recovery_days=(dates[i] - dates[trough_idx]).days,
            ))
            in_dd = False

    # Open drawdown (no recovery yet)
    if in_dd:
        periods.append(DrawdownPeriodResult(
            start_date=dates[start_idx],
            trough_date=dates[trough_idx],
            end_date=None,
            depth=round(float(trough_val), 6),
            duration_days=(dates[-1] - dates[start_idx]).days,
            recovery_days=None,
        ))

    periods.sort(key=lambda p: p.depth)
    return periods[:top_n]


def analyze_drawdowns(
    navs: np.ndarray,
    dates: list[date],
    top_n: int = 5,
) -> DrawdownResult:
    """Full drawdown analysis: series, periods, and summary statistics.

    Parameters
    ----------
    navs : np.ndarray
        NAV values aligned to ``dates``.
    dates : list[date]
        Trading dates corresponding to ``navs``.
    top_n : int
        Number of worst drawdown periods to return.

    """
    dd_series = compute_drawdown_series(navs)
    periods = extract_drawdown_periods(dates, dd_series, top_n=top_n)

    max_dd = round(float(np.min(dd_series)), 6) if len(dd_series) > 0 else 0.0
    current_dd = round(float(dd_series[-1]), 6) if len(dd_series) > 0 else 0.0

    longest = max((p.duration_days for p in periods), default=None)
    recovery_list = [p.recovery_days for p in periods if p.recovery_days is not None]
    avg_recovery = (
        round(sum(recovery_list) / len(recovery_list), 1) if recovery_list else None
    )

    return DrawdownResult(
        series=dd_series,
        max_drawdown=max_dd,
        current_drawdown=current_dd,
        periods=periods,
        longest_duration_days=longest,
        avg_recovery_days=avg_recovery,
    )
