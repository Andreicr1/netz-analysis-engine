"""Worker: equity_characteristics_compute — 6 Kelly-Pruitt-Su characteristics monthly.

Advisory lock : 900_091
Frequency     : daily after tiingo_fundamentals_ingestion (04:30 UTC)
Idempotent    : yes — ON CONFLICT (instrument_id, as_of) DO UPDATE
"""

from __future__ import annotations

import io
import time
from datetime import date, timedelta
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import structlog
from sqlalchemy import text

from app.core.db.engine import async_session_factory as async_session
from app.services.storage_client import get_storage_client
from app.domains.wealth.services.characteristics_derivation import (
    derive_book_to_market,
    derive_investment_growth,
    derive_momentum_12_1,
    derive_profitability_gross,
    derive_quality_roa,
    derive_size,
)

logger = structlog.get_logger()

LOCK_ID = 900_091


async def run_equity_characteristics_compute(
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Compute 6 equity characteristics for all instruments with Tiingo data."""
    started = time.monotonic()

    async with async_session() as db:
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({LOCK_ID})"),
        )
        if not lock_result.scalar():
            logger.warning("equity_characteristics_compute already running")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            stats = await _compute_all(db, limit=limit, dry_run=dry_run)
        finally:
            await db.execute(text(f"SELECT pg_advisory_unlock({LOCK_ID})"))

    stats["duration_seconds"] = round(time.monotonic() - started, 2)
    logger.info("equity_characteristics.complete", **stats)
    return stats


async def _compute_all(
    db: Any,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Core computation loop."""
    universe = await _load_tiingo_universe(db, limit=limit)
    stats: dict[str, Any] = {
        "status": "ok",
        "candidates": len(universe),
        "computed": 0,
        "rows_upserted": 0,
        "errors": 0,
    }

    all_rows: list[dict[str, Any]] = []
    for ticker, instrument_id in universe:
        try:
            rows = await _compute_ticker(db, ticker, instrument_id)
            if rows and not dry_run:
                upserted = await _upsert_rows(db, rows)
                stats["rows_upserted"] += upserted
            if rows:
                all_rows.extend(rows)
            stats["computed"] += 1
        except Exception:
            logger.exception("equity_characteristics.ticker_error", ticker=ticker)
            stats["errors"] += 1

    if not dry_run:
        await db.commit()
        await _write_silver_parquet(all_rows)

    return stats


async def _load_tiingo_universe(
    db: Any, limit: int | None = None
) -> list[tuple[str, str]]:
    """Load tickers with Tiingo fundamentals data joined to instruments_universe."""
    sql = text("""
        SELECT DISTINCT d.ticker, i.id::text
        FROM tiingo_fundamentals_daily d
        JOIN instruments_universe i ON i.ticker = d.ticker
        ORDER BY d.ticker
    """)
    result = await db.execute(sql)
    rows = result.fetchall()
    if limit:
        rows = rows[:limit]
    return [(r[0], r[1]) for r in rows]


async def _compute_ticker(
    db: Any, ticker: str, instrument_id: str
) -> list[dict[str, Any]]:
    """Compute monthly characteristics for one ticker across all available months."""
    market_caps = await _fetch_monthly_market_cap(db, ticker)
    statements = await _fetch_latest_statements(db, ticker)
    nav_series = await _fetch_nav_series(db, instrument_id)

    months = sorted(market_caps.keys())
    rows: list[dict[str, Any]] = []

    for month_end in months:
        mkt_cap = market_caps.get(month_end)
        stmt_data = statements.get(month_end, {})

        total_equity = stmt_data.get("totalEquity")
        total_assets = stmt_data.get("totalAssets")
        gross_profit = stmt_data.get("grossProfit")
        revenue = stmt_data.get("revenue")
        cost_of_revenue = stmt_data.get("costRev")
        filing_date = stmt_data.get("_filing_date")

        net_income_ttm = _compute_ttm(statements, month_end, "netIncome")
        total_assets_yoy = _get_yoy_value(statements, month_end, "totalAssets")

        rows.append({
            "instrument_id": instrument_id,
            "ticker": ticker,
            "as_of": month_end,
            "size_log_mkt_cap": derive_size(mkt_cap),
            "book_to_market": derive_book_to_market(total_equity, mkt_cap),
            "mom_12_1": derive_momentum_12_1(nav_series, month_end),
            "quality_roa": derive_quality_roa(net_income_ttm, total_assets),
            "investment_growth": derive_investment_growth(total_assets, total_assets_yoy),
            "profitability_gross": derive_profitability_gross(
                gross_profit, revenue, cost_of_revenue
            ),
            "source_filing_date": filing_date,
        })

    return rows


def _compute_ttm(
    statements: dict[date, dict[str, Any]], current_month: date, key: str
) -> float | None:
    """Sum trailing 4 quarters of a line item for TTM computation."""
    quarterly_values: list[tuple[date, float]] = []
    for month_end, data in statements.items():
        if month_end <= current_month and key in data and data[key] is not None:
            quarterly_values.append((month_end, data[key]))
    quarterly_values.sort(key=lambda x: x[0], reverse=True)
    trailing = quarterly_values[:4]
    if len(trailing) < 2:
        return None
    return sum(v for _, v in trailing)


def _get_yoy_value(
    statements: dict[date, dict[str, Any]], current_month: date, key: str
) -> float | None:
    """Look up the value from ~12 months ago for YoY comparison."""
    day = min(current_month.day, 28)
    target = date(current_month.year - 1, current_month.month, day)
    best: float | None = None
    best_dist = 45
    for month_end, data in statements.items():
        dist = abs((month_end - target).days)
        if dist < best_dist and key in data:
            best = data[key]
            best_dist = dist
    return best


async def _fetch_monthly_market_cap(
    db: Any, ticker: str
) -> dict[date, float | None]:
    """Last-day-of-month market cap from tiingo_fundamentals_daily."""
    sql = text("""
        SELECT DISTINCT ON (date_trunc('month', as_of))
            (date_trunc('month', as_of) + INTERVAL '1 month - 1 day')::date AS month_end,
            market_cap
        FROM tiingo_fundamentals_daily
        WHERE ticker = :ticker
        ORDER BY date_trunc('month', as_of), as_of DESC
    """)
    result = await db.execute(sql, {"ticker": ticker})
    return {row[0]: float(row[1]) if row[1] is not None else None for row in result.fetchall()}


async def _fetch_latest_statements(
    db: Any, ticker: str
) -> dict[date, dict[str, Any]]:
    """Latest statement line items per month, deduped by filing_date DESC."""
    sql = text("""
        SELECT DISTINCT ON (period_end, line_item)
            period_end,
            line_item,
            value,
            filing_date
        FROM tiingo_fundamentals_statements
        WHERE ticker = :ticker
        ORDER BY period_end, line_item, filing_date DESC
    """)
    result = await db.execute(sql, {"ticker": ticker})

    by_month: dict[date, dict[str, Any]] = {}
    for row in result.fetchall():
        period_end, line_item, value, filing_date = row
        month_end = _to_month_end(period_end)
        if month_end not in by_month:
            by_month[month_end] = {}
        by_month[month_end][line_item] = float(value) if value is not None else None
        if filing_date and (
            by_month[month_end].get("_filing_date") is None
            or filing_date > by_month[month_end]["_filing_date"]
        ):
            by_month[month_end]["_filing_date"] = filing_date

    return by_month


async def _fetch_nav_series(db: Any, instrument_id: str) -> pd.Series:
    """Monthly NAV series for momentum calculation."""
    sql = text("""
        SELECT DISTINCT ON (date_trunc('month', ts))
            (date_trunc('month', ts) + INTERVAL '1 month - 1 day')::date AS month_end,
            last(nav, ts) AS nav_eom
        FROM nav_timeseries
        WHERE instrument_id = :iid
        GROUP BY date_trunc('month', ts)
        ORDER BY date_trunc('month', ts)
    """)
    result = await db.execute(sql, {"iid": instrument_id})
    rows = result.fetchall()
    if not rows:
        return pd.Series(dtype=float)
    dates = [r[0] for r in rows]
    values = [float(r[1]) if r[1] is not None else None for r in rows]
    return pd.Series(values, index=pd.DatetimeIndex(dates))


def _to_month_end(d: date) -> date:
    """Snap any date to its month-end."""
    if d.month == 12:
        return date(d.year + 1, 1, 1) - timedelta(days=1)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


async def _upsert_rows(db: Any, rows: list[dict[str, Any]]) -> int:
    """Upsert characteristics rows via ON CONFLICT."""
    if not rows:
        return 0

    upsert_sql = text("""
        INSERT INTO equity_characteristics_monthly (
            instrument_id, ticker, as_of,
            size_log_mkt_cap, book_to_market, mom_12_1,
            quality_roa, investment_growth, profitability_gross,
            source_filing_date, computed_at
        ) VALUES (
            :instrument_id, :ticker, :as_of,
            :size_log_mkt_cap, :book_to_market, :mom_12_1,
            :quality_roa, :investment_growth, :profitability_gross,
            :source_filing_date, now()
        )
        ON CONFLICT (instrument_id, as_of) DO UPDATE SET
            ticker = EXCLUDED.ticker,
            size_log_mkt_cap = EXCLUDED.size_log_mkt_cap,
            book_to_market = EXCLUDED.book_to_market,
            mom_12_1 = EXCLUDED.mom_12_1,
            quality_roa = EXCLUDED.quality_roa,
            investment_growth = EXCLUDED.investment_growth,
            profitability_gross = EXCLUDED.profitability_gross,
            source_filing_date = EXCLUDED.source_filing_date,
            computed_at = now()
    """)

    batch_size = 500
    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        for row in batch:
            await db.execute(upsert_sql, row)
        total += len(batch)

    return total


async def _write_silver_parquet(rows: list[dict[str, Any]]) -> None:
    """Dual-write to silver parquet, grouped by as_of month."""
    if not rows:
        return
    df = pd.DataFrame(rows)
    storage = get_storage_client()
    for as_of, group in df.groupby("as_of"):
        buf = io.BytesIO()
        table = pa.Table.from_pandas(group, preserve_index=False)
        pq.write_table(table, buf, compression="zstd")
        path = f"silver/_global/equity_characteristics/{as_of}/chars.parquet"
        try:
            await storage.write(path, buf.getvalue(), content_type="application/octet-stream")
        except Exception:
            logger.warning("equity_characteristics.parquet_write_failed", as_of=str(as_of))
