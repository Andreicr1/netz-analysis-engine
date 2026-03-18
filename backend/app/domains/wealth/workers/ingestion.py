"""NAV ingestion worker — fetches daily prices from Yahoo Finance.

Usage:
    python -m app.workers.ingestion

Fetches NAV/prices for all active funds using batch yf.download(),
then upserts results per-fund into nav_timeseries with a single commit.
"""

import asyncio
import concurrent.futures
import math
import uuid
from datetime import date, timedelta

import structlog
import yfinance as yf
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db.engine import async_session_factory as async_session
from app.core.tenancy.middleware import set_rls_context
from app.domains.wealth.models.fund import Fund
from app.domains.wealth.models.nav import NavTimeseries

logger = structlog.get_logger()

NAV_INGESTION_LOCK_ID = 900_006
MAX_RETRIES = 3
BACKOFF_BASE = 1  # 1s, 4s, 16s

# Dedicated thread pool for data I/O — isolates from default asyncio pool
# Prevents thread starvation when pipeline runs concurrently with API requests
_io_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="data-io"
)


def _batch_download(tickers: list[str], start: str, end: str):
    """Synchronous batch download — runs in dedicated thread pool."""
    return yf.download(
        tickers=tickers,
        start=start,
        end=end,
        interval="1d",
        auto_adjust=True,
        repair=True,
        threads=True,
        group_by="ticker",
        timeout=30,
        progress=False,
    )


async def run_ingestion(org_id: uuid.UUID, lookback_days: int = 30) -> dict[str, int]:
    """Fetch latest NAV/prices for all active funds using batch download.

    Uses yf.download() for efficient batch HTTP, then iterates per-fund
    for upsert. Single commit after all funds processed.
    """
    logger.info("Starting NAV ingestion", lookback_days=lookback_days)
    results: dict[str, int] = {}

    async with async_session() as db:
        await set_rls_context(db, org_id)
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({NAV_INGESTION_LOCK_ID})")
        )
        acquired = lock_result.scalar()
        if not acquired:
            logger.info("worker_skipped", reason="another instance running")
            return {"status": "skipped", "reason": "NAV ingestion already running"}
        try:
            stmt = select(Fund).where(Fund.is_active == True, Fund.ticker.is_not(None))
            result = await db.execute(stmt)
            funds = result.scalars().all()

            if not funds:
                logger.info("No active funds with tickers")
                return results

            # Build ticker -> fund mapping
            ticker_fund_map = {f.ticker: f for f in funds if f.ticker}
            tickers_list = list(ticker_fund_map.keys())
            logger.info("Funds to ingest", count=len(tickers_list))

            end_date = date.today()
            start_date = end_date - timedelta(days=lookback_days)

            # Batch download with retry
            hist = None
            for attempt in range(MAX_RETRIES):
                try:
                    loop = asyncio.get_event_loop()
                    hist = await loop.run_in_executor(
                        _io_executor,
                        _batch_download, tickers_list, str(start_date), str(end_date),
                    )
                    break
                except Exception as e:
                    wait = BACKOFF_BASE * (4 ** attempt)
                    logger.warning(
                        "yfinance batch download failed, retrying",
                        attempt=attempt + 1,
                        wait=wait,
                        error=str(e),
                    )
                    if attempt == MAX_RETRIES - 1:
                        logger.error("yfinance batch download exhausted retries")
                        return results
                    await asyncio.sleep(wait)

            if hist is None or hist.empty:
                logger.info("No data returned from batch download")
                return results

            is_multi = len(tickers_list) > 1

            # Per-fund iteration: extract data, build rows, accumulate for batch upsert
            all_rows: list[dict] = []

            for ticker, fund in ticker_fund_map.items():
                try:
                    if is_multi:
                        ticker_data = hist[ticker]
                    else:
                        ticker_data = hist

                    # Drop NaN rows to handle batch alignment gaps
                    ticker_data = ticker_data.dropna(subset=["Close"])

                    if ticker_data.empty:
                        logger.info("No data for ticker", ticker=ticker)
                        results[ticker] = 0
                        continue

                    # Suspicious price jump detection (possible unhandled split)
                    closes = ticker_data["Close"]
                    if len(closes) > 1:
                        returns = closes.pct_change().dropna()
                        if len(returns) > 0:
                            max_abs = float(returns.abs().max())
                            if max_abs > 0.5:
                                logger.warning(
                                    "Suspicious price jump — possible unhandled split",
                                    ticker=ticker,
                                    max_return=round(max_abs, 4),
                                )

                    # Build rows with log returns
                    rows = []
                    prev_close = None
                    for idx, row in ticker_data.iterrows():
                        nav_date = idx.date() if hasattr(idx, "date") else idx
                        close_price = float(row["Close"])

                        # Validate NAV — zero or negative is a data error, not a floor case
                        if close_price <= 0:
                            logger.warning(
                                "Invalid NAV — zero or negative price skipped",
                                ticker=ticker,
                                nav_date=str(nav_date),
                                close_price=close_price,
                            )
                            prev_close = None  # Reset: next row cannot compute a valid return
                            continue

                        return_1d = None
                        if prev_close is not None:
                            # Log return: ln(P_t / P_{t-1}) — unbiased for multi-period compounding
                            return_1d = math.log(close_price / prev_close)
                            # Flag extreme returns — possible data error or unhandled corporate action
                            if abs(return_1d) > 0.25:
                                logger.warning(
                                    "Extreme log return flagged — possible data error",
                                    ticker=ticker,
                                    nav_date=str(nav_date),
                                    log_return=round(return_1d, 6),
                                )

                        prev_close = close_price
                        rows.append({
                            "instrument_id": fund.fund_id,
                            "nav_date": nav_date,
                            "nav": round(close_price, 6),
                            "return_1d": round(return_1d, 8) if return_1d is not None else None,
                            "return_type": "log",
                            "currency": fund.currency or "USD",
                            "source": "yahoo",
                        })

                    all_rows.extend(rows)
                    results[ticker] = len(rows)
                    logger.info("Processed", ticker=ticker, rows=len(rows))

                except (KeyError, TypeError) as e:
                    logger.warning(
                        "Ticker missing from batch result",
                        ticker=ticker,
                        error=str(e),
                    )
                    results[ticker] = 0
                    continue

            # Chunked batch upsert to avoid large WAL writes on big lookbacks
            UPSERT_CHUNK = 5000
            if all_rows:
                for i in range(0, len(all_rows), UPSERT_CHUNK):
                    chunk = all_rows[i:i + UPSERT_CHUNK]
                    stmt = pg_insert(NavTimeseries).values(chunk)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["instrument_id", "nav_date"],
                        set_={
                            "nav": stmt.excluded.nav,
                            "return_1d": stmt.excluded.return_1d,
                            "return_type": stmt.excluded.return_type,
                            "source": stmt.excluded.source,
                        },
                    )
                    await db.execute(stmt)
                    await db.commit()
                    await set_rls_context(db, org_id)
        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({NAV_INGESTION_LOCK_ID})")
            )

    total = sum(results.values())
    logger.info("Ingestion complete", total_rows=total, funds_processed=len(results))
    return results


if __name__ == "__main__":
    asyncio.run(run_ingestion())
