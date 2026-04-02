"""Instrument universe NAV ingestion worker — GLOBAL.

Fetches NAV history for ALL active instruments across all tenants
using the provider factory (get_instrument_provider), computes log returns,
and upserts into nav_timeseries (global table, no RLS).

Deduplicates by ticker — one Yahoo call per unique ticker regardless of
how many tenants have selected the instrument.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import math
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory
from app.domains.wealth.models.instrument import Instrument
from app.services.providers import get_instrument_provider

logger = structlog.get_logger()

INSTRUMENT_INGESTION_LOCK_ID = 900_010

MAX_RETRIES = 3
BACKOFF_BASE = 1  # 1s, 4s, 16s
UPSERT_CHUNK = 500

# Maximum NaN ratio before rejecting a ticker's data
_MAX_NAN_RATIO = 0.05  # 5%

# Dedicated thread pool for blocking provider calls
_io_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="instrument-io",
)

# Map lookback_days to yfinance period strings
_LOOKBACK_TO_PERIOD = {
    30: "1mo",
    90: "3mo",
    365: "1y",
    730: "2y",
    1095: "3y",
    1825: "5y",
    3650: "10y",
}


def _resolve_period(lookback_days: int) -> str:
    """Map lookback_days to the closest yfinance period string."""
    for threshold, period in sorted(_LOOKBACK_TO_PERIOD.items()):
        if lookback_days <= threshold:
            return period
    return "10y"


async def run_instrument_ingestion(
    lookback_days: int = 3650,
) -> dict[str, int | list[str]]:
    """Fetch NAV history for all active instruments in the global catalog.

    Global worker — no org_id needed. instruments_universe and nav_timeseries
    are both global tables. Deduplicates tickers across all tenants.
    """
    logger.info("Starting instrument NAV ingestion (global)", lookback_days=lookback_days)

    async with async_session_factory() as db:
        db.expire_on_commit = False  # type: ignore[attr-defined]

        # Advisory lock — skip if already running
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({INSTRUMENT_INGESTION_LOCK_ID})"),
        )
        if not lock_result.scalar():
            logger.warning("Instrument ingestion already running — skipping")
            return {
                "instruments_processed": 0,
                "rows_upserted": 0,
                "skipped_tickers": [],
                "errors": [],
            }

        try:
            return await _do_ingest(db, lookback_days)
        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({INSTRUMENT_INGESTION_LOCK_ID})"),
            )


async def _do_ingest(
    db: AsyncSession,
    lookback_days: int,
) -> dict[str, int | list[str]]:
    """Core ingestion logic — separated for advisory lock cleanup."""
    # 1. Query ALL active instruments with tickers (global — no RLS)
    stmt = (
        select(Instrument)
        .where(Instrument.is_active == True)  # noqa: E712
        .where(Instrument.ticker.isnot(None))
        .where(Instrument.ticker != "")
    )
    result = await db.execute(stmt)
    instruments = result.scalars().all()

    if not instruments:
        logger.info("No active instruments with tickers found")
        return {
            "instruments_processed": 0,
            "rows_upserted": 0,
            "skipped_tickers": [],
            "errors": [],
        }

    # Build ticker -> instrument mapping (extract scalars for thread safety)
    # Deduplicates: one Yahoo call per unique ticker
    ticker_map: dict[str, list[tuple[Any, str]]] = {}
    for inst in instruments:
        if not inst.ticker:
            continue
        ticker = inst.ticker.strip().upper()
        ticker_map.setdefault(ticker, []).append(
            (inst.instrument_id, inst.currency or "USD"),
        )

    unique_tickers = list(ticker_map.keys())
    logger.info(
        "Instruments to fetch",
        unique_tickers=len(unique_tickers),
        total_instruments=len(instruments),
    )

    # 2. Batch fetch via provider factory
    provider = get_instrument_provider()
    period = _resolve_period(lookback_days)

    loop = asyncio.get_event_loop()
    history = None
    for attempt in range(MAX_RETRIES):
        try:
            history = await loop.run_in_executor(
                _io_executor,
                provider.fetch_batch_history,
                unique_tickers,
                period,
            )
            break
        except Exception as e:
            wait = BACKOFF_BASE * (4**attempt)
            logger.warning(
                "Provider batch history failed, retrying",
                attempt=attempt + 1,
                wait=wait,
                error=str(e),
            )
            if attempt == MAX_RETRIES - 1:
                logger.error("Provider batch history exhausted retries")
                return {
                    "instruments_processed": 0,
                    "rows_upserted": 0,
                    "skipped_tickers": unique_tickers,
                    "errors": ["Provider batch download exhausted retries"],
                }
            await asyncio.sleep(wait)

    if history is None or not history:
        logger.error("No data returned from provider")
        return {
            "instruments_processed": 0,
            "rows_upserted": 0,
            "skipped_tickers": unique_tickers,
            "errors": ["No data returned from provider"],
        }

    # 3. Process each ticker, validate, build rows
    all_rows: list[dict[str, Any]] = []
    instruments_processed: set[str] = set()
    skipped_tickers: list[str] = []
    errors: list[str] = []

    for ticker, instrument_entries in ticker_map.items():
        try:
            if ticker not in history:
                logger.warning("Ticker not in provider response", ticker=ticker)
                skipped_tickers.append(ticker)
                continue

            ticker_data = history[ticker]

            if ticker_data.empty:
                logger.warning("Empty data for ticker", ticker=ticker)
                skipped_tickers.append(ticker)
                continue

            # Data validation: check Close column exists
            if "Close" not in ticker_data.columns:
                logger.warning("No Close column for ticker", ticker=ticker)
                skipped_tickers.append(ticker)
                continue

            close_col = ticker_data["Close"]

            # NaN ratio check
            nan_ratio = float(close_col.isna().sum()) / max(len(close_col), 1)
            if nan_ratio > _MAX_NAN_RATIO:
                logger.warning(
                    "NaN ratio too high — skipping ticker",
                    ticker=ticker,
                    nan_ratio=round(nan_ratio, 4),
                    threshold=_MAX_NAN_RATIO,
                )
                skipped_tickers.append(ticker)
                continue

            # Zero/negative price check
            valid_close = close_col.dropna()
            if (valid_close <= 0).any():
                logger.warning(
                    "Zero or negative prices detected — skipping ticker",
                    ticker=ticker,
                )
                skipped_tickers.append(ticker)
                continue

            ticker_data = ticker_data.dropna(subset=["Close"])
            if ticker_data.empty:
                logger.warning("All rows filtered after NaN removal", ticker=ticker)
                skipped_tickers.append(ticker)
                continue

            # Build rows with log returns — no organization_id (global table)
            prev_close = None
            for idx, row in ticker_data.iterrows():
                nav_date = idx.date() if hasattr(idx, "date") else idx
                close_price = float(row["Close"])

                if close_price <= 0:
                    prev_close = None
                    continue

                return_1d = None
                if prev_close is not None and prev_close > 0:
                    return_1d = math.log(close_price / prev_close)
                    if abs(return_1d) > 0.25:
                        logger.warning(
                            "Extreme log return flagged",
                            ticker=ticker,
                            nav_date=str(nav_date),
                            log_return=round(return_1d, 6),
                        )

                prev_close = close_price

                # One row per instrument_id that uses this ticker
                for instrument_id, currency in instrument_entries:
                    all_rows.append(
                        {
                            "instrument_id": instrument_id,
                            "nav_date": nav_date,
                            "nav": round(close_price, 6),
                            "return_1d": round(return_1d, 8)
                            if return_1d is not None
                            else None,
                            "return_type": "log",
                            "currency": currency,
                            "source": "yahoo",
                        },
                    )

            instruments_processed.add(ticker)
            logger.info("Processed ticker", ticker=ticker)

        except (KeyError, TypeError) as e:
            logger.warning(
                "Error processing ticker",
                ticker=ticker,
                error=str(e),
            )
            errors.append(f"{ticker}: {e}")
            continue

    # 4. Chunked batch upsert — raw SQL (no organization_id)
    total_upserted = 0
    if all_rows:
        upsert_sql = text("""
            INSERT INTO nav_timeseries
                (instrument_id, nav_date, nav, return_1d, return_type, currency, source)
            VALUES
                (:instrument_id, :nav_date, :nav, :return_1d, :return_type, :currency, :source)
            ON CONFLICT (instrument_id, nav_date)
            DO UPDATE SET
                nav = EXCLUDED.nav,
                return_1d = EXCLUDED.return_1d,
                return_type = EXCLUDED.return_type,
                currency = EXCLUDED.currency,
                source = EXCLUDED.source
        """)
        for i in range(0, len(all_rows), UPSERT_CHUNK):
            chunk = all_rows[i : i + UPSERT_CHUNK]
            try:
                await db.execute(upsert_sql, chunk)
                await db.commit()
                total_upserted += len(chunk)
            except Exception as chunk_err:
                logger.warning(
                    "Chunk upsert failed — rolling back chunk",
                    chunk_index=i,
                    chunk_size=len(chunk),
                    error=str(chunk_err)[:200],
                )
                await db.rollback()
                errors.append(f"chunk {i}: {str(chunk_err)[:100]}")

    logger.info(
        "Instrument ingestion complete",
        instruments_processed=len(instruments_processed),
        rows_upserted=total_upserted,
        skipped_tickers=skipped_tickers,
        errors=errors,
    )

    return {
        "instruments_processed": len(instruments_processed),
        "rows_upserted": total_upserted,
        "skipped_tickers": skipped_tickers,
        "errors": errors,
    }
