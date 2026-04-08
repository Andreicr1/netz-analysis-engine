"""Returns & risk analytics for the Discovery Analysis page (Phase 5).

DB-only hot path. Fetches daily NAV, monthly compound returns (from the
``nav_monthly_returns_agg`` Timescale continuous aggregate), the latest
``fund_risk_metrics`` row, and computes rolling vol/Sharpe + a monthly
return histogram in pure Python.

Shape matches the Analysis page contract consumed by
``discovery_analysis.py``. Keep helpers pure — rolling/histogram run
synchronously after the gathered DB round-trips.
"""

from __future__ import annotations

import asyncio
import math
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

Window = Literal["1y", "3y", "5y", "max"]
WINDOW_INTERVAL: dict[str, str] = {
    "1y": "1 year",
    "3y": "3 years",
    "5y": "5 years",
    "max": "50 years",
}


async def _nav_series(
    db: AsyncSession, instrument_id: str, window: Window,
) -> list[dict[str, Any]]:
    # nav_timeseries is GLOBAL (no organization_id) — migration 0069.
    sql = f"""
        SELECT nav_date, nav, return_1d
        FROM nav_timeseries
        WHERE instrument_id = :id
          AND nav_date >= NOW() - INTERVAL '{WINDOW_INTERVAL[window]}'
        ORDER BY nav_date ASC
    """
    res = await db.execute(text(sql), {"id": instrument_id})
    return [dict(r) for r in res.mappings().all()]


async def _monthly_returns(
    db: AsyncSession, instrument_id: str, window: Window,
) -> list[dict[str, Any]]:
    # nav_monthly_returns_agg columns (migration 0069): instrument_id,
    # month, compound_log_return, compound_return, trading_days, min_nav,
    # max_nav. No organization_id, no month_end_nav.
    sql = f"""
        SELECT month, compound_return, compound_log_return, trading_days
        FROM nav_monthly_returns_agg
        WHERE instrument_id = :id
          AND month >= NOW() - INTERVAL '{WINDOW_INTERVAL[window]}'
        ORDER BY month ASC
    """
    res = await db.execute(text(sql), {"id": instrument_id})
    return [dict(r) for r in res.mappings().all()]


async def _risk_metrics(
    db: AsyncSession, instrument_id: str,
) -> dict[str, Any] | None:
    sql = """
        SELECT *
        FROM fund_risk_metrics
        WHERE instrument_id = :id
        ORDER BY calc_date DESC
        LIMIT 1
    """
    res = await db.execute(text(sql), {"id": instrument_id})
    row = res.mappings().first()
    return dict(row) if row else None


def _compute_rolling(
    nav_series: list[dict[str, Any]], window_days: int = 252,
) -> list[dict[str, Any]]:
    """Rolling annualized vol + Sharpe from the ``return_1d`` column."""
    out: list[dict[str, Any]] = []
    returns = [p["return_1d"] for p in nav_series if p.get("return_1d") is not None]
    if len(returns) < window_days:
        return out
    for i in range(window_days, len(nav_series)):
        window_slice = returns[i - window_days : i]
        if len(window_slice) < window_days:
            continue
        mean = sum(window_slice) / len(window_slice)
        var = sum((r - mean) ** 2 for r in window_slice) / (len(window_slice) - 1)
        vol = math.sqrt(var) * math.sqrt(252)
        sharpe = (mean * 252) / vol if vol > 0 else 0.0
        out.append(
            {
                "date": nav_series[i]["nav_date"],
                "rolling_vol": vol,
                "rolling_sharpe": sharpe,
            },
        )
    return out


def _compute_return_distribution(
    monthly: list[dict[str, Any]],
) -> dict[str, Any]:
    """Bucket monthly returns into a 20-bin histogram for charting."""
    if not monthly:
        return {"bins": [], "counts": []}
    values = [
        m["compound_return"]
        for m in monthly
        if m.get("compound_return") is not None
    ]
    if not values:
        return {"bins": [], "counts": []}
    lo, hi = min(values), max(values)
    n_bins = 20
    width = (hi - lo) / n_bins if hi > lo else 0.01
    counts = [0] * n_bins
    for v in values:
        idx = min(int((v - lo) / width), n_bins - 1) if width > 0 else 0
        counts[idx] += 1
    bins = [round(lo + i * width, 4) for i in range(n_bins)]
    return {
        "bins": bins,
        "counts": counts,
        "mean": sum(values) / len(values),
    }


async def fetch_returns_risk(
    db: AsyncSession,
    instrument_id: str,
    window: Window = "3y",
) -> dict[str, Any]:
    """Aggregate returns + risk payload for the Analysis page."""
    nav, monthly, risk = await asyncio.gather(
        _nav_series(db, instrument_id, window),
        _monthly_returns(db, instrument_id, window),
        _risk_metrics(db, instrument_id),
    )
    rolling = _compute_rolling(nav)
    distribution = _compute_return_distribution(monthly)
    return {
        "window": window,
        "nav_series": nav,
        "monthly_returns": monthly,
        "rolling_metrics": rolling,
        "return_distribution": distribution,
        "risk_metrics": risk,
        "disclosure": {"has_nav": len(nav) > 0},
    }
