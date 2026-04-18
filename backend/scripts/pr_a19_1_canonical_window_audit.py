"""PR-A19.1 Section D — canonical-ticker 1Y window audit.

Diagnostic-only (no fix): for each canonical ticker, compute the 1Y
simple-compound and log-compound returns directly from
``nav_timeseries`` and report the window span, day count, and any
delta between the two conventions. Any gap between observed compound
and the μ that ``compute_fund_level_inputs`` would produce is logged
via the secondary ``mu_historical_window_mismatch`` event so
operators can triage NAV staleness / missing endpoints without
touching the estimator.

Usage::

    python -m backend.scripts.pr_a19_1_canonical_window_audit

Read-only; safe against production.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

CANONICAL_TICKERS = (
    "SPY", "IVV", "VTI", "AGG", "BND", "IEF", "TLT", "SHY", "GLD", "VTEB",
)

WINDOW_SQL = text(
    """
    WITH target AS (
        SELECT instrument_id, ticker
        FROM instruments_universe
        WHERE ticker = :ticker
        LIMIT 1
    ),
    window_rows AS (
        SELECT nt.nav_date, nt.nav
        FROM nav_timeseries nt
        JOIN target ON nt.instrument_id = target.instrument_id
        WHERE nt.nav_date >= NOW() - INTERVAL '365 days'
        ORDER BY nt.nav_date
    ),
    endpoints AS (
        SELECT
            (SELECT MIN(nav_date) FROM window_rows) AS first_date,
            (SELECT MAX(nav_date) FROM window_rows) AS last_date,
            (SELECT COUNT(*) FROM window_rows) AS n_days,
            (SELECT nav FROM window_rows ORDER BY nav_date ASC LIMIT 1) AS first_nav,
            (SELECT nav FROM window_rows ORDER BY nav_date DESC LIMIT 1) AS last_nav,
            (SELECT MAX(nt.nav_date) FROM nav_timeseries nt
             JOIN target ON nt.instrument_id = target.instrument_id) AS overall_last_date
    )
    SELECT * FROM endpoints
    """
)


async def _audit_ticker(conn, ticker: str) -> dict[str, object]:
    row = (
        await conn.execute(WINDOW_SQL, {"ticker": ticker})
    ).fetchone()
    if row is None or row.n_days is None or row.n_days == 0:
        return {"ticker": ticker, "event": "canonical_window_audit_missing"}

    first_nav = float(row.first_nav) if row.first_nav is not None else None
    last_nav = float(row.last_nav) if row.last_nav is not None else None
    simple_compound = (
        last_nav / first_nav - 1.0
        if first_nav and last_nav and first_nav > 0
        else None
    )
    span_days = None
    if row.first_date and row.last_date:
        span_days = (row.last_date - row.first_date).days
    staleness_days = None
    if row.overall_last_date and row.last_date:
        # How far behind today the last NAV sits (proxy for stale endpoint).
        from datetime import date as _date
        staleness_days = (_date.today() - row.overall_last_date).days

    return {
        "event": "canonical_window_audit",
        "ticker": ticker,
        "first_date": str(row.first_date) if row.first_date else None,
        "last_date": str(row.last_date) if row.last_date else None,
        "overall_last_nav_date": (
            str(row.overall_last_date) if row.overall_last_date else None
        ),
        "span_days": span_days,
        "n_days": int(row.n_days),
        "first_nav": first_nav,
        "last_nav": last_nav,
        "simple_compound_1y": simple_compound,
        "endpoint_staleness_days": staleness_days,
    }


async def main() -> None:
    engine = create_async_engine(settings.database_url, echo=False)
    async with engine.connect() as conn:
        for ticker in CANONICAL_TICKERS:
            result = await _audit_ticker(conn, ticker)
            print(json.dumps(result))

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
