"""Rolling returns service.

Pure sync computation — no I/O, no DB access. Receives daily returns array
and computes rolling annualized returns for standard institutional windows.

Reusable across entity_analytics, LongFormReport, fact_sheet, track_record.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Standard institutional rolling windows (label, trading days)
ROLLING_WINDOWS: list[tuple[str, int]] = [
    ("1M", 21),
    ("3M", 63),
    ("6M", 126),
    ("1Y", 252),
]


@dataclass(frozen=True, slots=True)
class RollingSeriesResult:
    """A single rolling return time series for one window."""

    window_label: str
    window_days: int
    dates: list[str]
    values: list[float]


@dataclass(frozen=True, slots=True)
class RollingReturnsResult:
    """Collection of rolling return series across standard windows."""

    series: list[RollingSeriesResult] = field(default_factory=list)


def compute_rolling_returns(
    dates: list[str],
    returns: np.ndarray,
    windows: list[tuple[str, int]] | None = None,
) -> list[RollingSeriesResult]:
    """Compute rolling annualized returns for each window.

    Parameters
    ----------
    dates : list[str]
        ISO date strings aligned to ``returns``.
    returns : np.ndarray
        Daily returns array (T,).
    windows : list[tuple[str, int]] | None
        List of (label, trading_days) tuples. Defaults to ROLLING_WINDOWS.

    Returns
    -------
    list[RollingSeriesResult]
        One entry per window that has enough data.

    """
    if windows is None:
        windows = ROLLING_WINDOWS

    n = len(returns)
    result: list[RollingSeriesResult] = []

    for label, window in windows:
        if n < window:
            continue
        roll_dates: list[str] = []
        roll_vals: list[float] = []
        for i in range(window, n + 1):
            window_returns = returns[i - window: i]
            cum = float(np.prod(1.0 + window_returns))
            ann = cum ** (252 / window) - 1.0
            roll_dates.append(dates[i - 1])
            roll_vals.append(round(ann, 6))
        result.append(RollingSeriesResult(
            window_label=label,
            window_days=window,
            dates=roll_dates,
            values=roll_vals,
        ))

    return result
