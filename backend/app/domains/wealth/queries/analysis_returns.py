"""Returns & risk analytics for the Discovery Analysis page (Phase 5).

DB-only hot path. Fetches daily NAV, monthly compound returns (from the
``nav_monthly_returns_agg`` Timescale continuous aggregate), the latest
``fund_risk_metrics`` row, and computes rolling vol/Sharpe + a monthly
return histogram in pure Python.

Shape matches the Analysis page contract consumed by
``discovery_analysis.py``. Keep helpers pure — rolling/histogram run
synchronously after the sequential DB round-trips.
"""

from __future__ import annotations

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
    # nav_monthly_returns_agg real columns (verified against live schema):
    # instrument_id, month, nav_open, nav_close, trading_days,
    # avg_daily_return, daily_volatility. Compound return is computed
    # inline as (nav_close / nav_open) - 1 with a NULLIF guard to avoid
    # divide-by-zero on stale-NAV instruments. The earlier implementation
    # referenced columns (``compound_return``, ``compound_log_return``,
    # ``min_nav``, ``max_nav``) that do not exist — it blew up in
    # production but was shielded from tests by the pre-existing
    # ``asyncio.gather`` short-circuit in ``fetch_returns_risk``.
    sql = f"""
        SELECT
            month,
            trading_days,
            (nav_close / NULLIF(nav_open, 0)) - 1 AS compound_return
        FROM nav_monthly_returns_agg
        WHERE instrument_id = :id
          AND month >= NOW() - INTERVAL '{WINDOW_INTERVAL[window]}'
        ORDER BY month ASC
    """
    res = await db.execute(text(sql), {"id": instrument_id})
    return [
        {
            "month": r["month"],
            "trading_days": int(r["trading_days"]) if r["trading_days"] is not None else 0,
            "compound_return": float(r["compound_return"]) if r["compound_return"] is not None else None,
        }
        for r in res.mappings().all()
    ]


# Explicit projection — the frontend contract is pinned to these keys.
# Do not add columns here without updating the wealth-os TS types.
# ``peer_strategy_label`` is renamed to ``peer_strategy`` at the payload
# boundary for parity with the Screener's ``scoring_metrics.peer_strategy``
# key — keeps cross-path consistency for the charting agent.
RISK_METRICS_COLUMNS: tuple[str, ...] = (
    "sharpe_1y",
    "volatility_1y",
    "volatility_garch",
    "cvar_95_12m",
    "cvar_95_conditional",
    "max_drawdown_1y",
    "return_1y",
    "manager_score",
    "blended_momentum_score",
    "peer_sharpe_pctl",
    "peer_sortino_pctl",
    "peer_return_pctl",
    "peer_drawdown_pctl",
    "peer_count",
    "peer_strategy_label",
    "calc_date",
)


async def _risk_metrics(
    db: AsyncSession, instrument_id: str,
) -> dict[str, Any] | None:
    """Latest ``fund_risk_metrics`` row for the instrument.

    Returns a flat dict with exactly the keys declared in
    :data:`RISK_METRICS_COLUMNS`, with ``peer_strategy_label`` renamed
    to ``peer_strategy`` at the boundary. Missing rows → ``None``.
    """
    sql = text(
        f"""
        SELECT {", ".join(RISK_METRICS_COLUMNS)}
        FROM fund_risk_metrics
        WHERE instrument_id = :id
        ORDER BY calc_date DESC
        LIMIT 1
        """,
    )
    res = await db.execute(sql, {"id": instrument_id})
    row = res.mappings().first()
    if row is None:
        return None
    payload = {col: row[col] for col in RISK_METRICS_COLUMNS}
    payload["peer_strategy"] = payload.pop("peer_strategy_label")
    return payload


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
    """Aggregate returns + risk payload for the Analysis page.

    The three DB reads run sequentially on the shared ``AsyncSession``.
    ``asyncio.gather`` is incompatible with ``asyncpg`` on a single
    connection ("another operation is in progress") and opening parallel
    sessions would break the RLS ``SET LOCAL`` context. The endpoint is
    behind a 1-hour Redis cache, so the ~30 ms added by serialization is
    not user-visible at steady state.
    """
    nav = await _nav_series(db, instrument_id, window)
    monthly = await _monthly_returns(db, instrument_id, window)
    risk = await _risk_metrics(db, instrument_id)
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
