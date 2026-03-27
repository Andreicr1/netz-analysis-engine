"""Benchmark NAV ingestion worker — fetches benchmark prices from Yahoo Finance.

Downloads benchmark NAV data for all allocation blocks with a benchmark_ticker,
then upserts into benchmark_nav (global table, no RLS).

Advisory lock prevents concurrent runs. Validates data quality on ingestion.
Fails loudly if no blocks have benchmark tickers configured.
"""

import asyncio
import concurrent.futures
import math
from datetime import date, timedelta

import structlog
import yfinance as yf
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db.engine import async_session_factory as async_session
from app.domains.wealth.models.benchmark_nav import BenchmarkNav
from app.domains.wealth.models.block import AllocationBlock

logger = structlog.get_logger()

# Deterministic lock ID — never use hash() (non-deterministic across processes)
BENCHMARK_INGEST_LOCK_ID = 900_004

MAX_RETRIES = 3
BACKOFF_BASE = 1  # 1s, 4s, 16s
UPSERT_CHUNK = 200  # Short transactions to prevent connection pool starvation

# Maximum NaN ratio before rejecting a ticker's data
_MAX_NAN_RATIO = 0.05  # 5%

# Staleness threshold in business days
_STALE_THRESHOLD_DAYS = 7

# Dedicated thread pool — isolates from default asyncio pool
_io_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="benchmark-io",
)


def _batch_download(tickers: list[str], start: str, end: str):
    """Synchronous batch download — runs in dedicated thread pool.

    Uses threads=True for yfinance's internal batch parallelism.
    Never parallelize individual .info calls (yfinance global mutable state).
    """
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


async def run_benchmark_ingest(lookback_days: int = 3650) -> dict[str, int | list[str]]:
    """Fetch benchmark NAV for all active allocation blocks.

    Returns dict with blocks_updated, rows_upserted, stale_blocks, skipped_tickers.
    Raises RuntimeError if no blocks have benchmark_ticker configured.
    """
    logger.info("Starting benchmark NAV ingestion", lookback_days=lookback_days)

    async with async_session() as db:
        # Advisory lock — skip if already running (non-blocking)
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({BENCHMARK_INGEST_LOCK_ID})"),
        )
        if not lock_result.scalar():
            logger.warning("Benchmark ingest already running — skipping")
            return {"blocks_updated": 0, "rows_upserted": 0, "stale_blocks": [], "skipped_tickers": []}

        try:
            return await _do_ingest(db, lookback_days)
        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({BENCHMARK_INGEST_LOCK_ID})"),
            )


async def _do_ingest(db, lookback_days: int) -> dict[str, int | list[str]]:
    """Core ingestion logic — separated for advisory lock cleanup."""
    # 1. Load blocks with benchmark tickers
    stmt = select(AllocationBlock).where(
        AllocationBlock.benchmark_ticker.is_not(None),
        AllocationBlock.is_active == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    blocks = result.scalars().all()

    if not blocks:
        raise RuntimeError(
            "No allocation blocks with benchmark_ticker configured. "
            "Populate allocation_blocks.benchmark_ticker before running benchmark ingestion.",
        )

    # 2. Deduplicate tickers — multiple blocks may share a ticker (e.g., SPY)
    ticker_to_blocks: dict[str, list[str]] = {}
    for block in blocks:
        ticker = block.benchmark_ticker.strip().upper()
        ticker_to_blocks.setdefault(ticker, []).append(block.block_id)

    unique_tickers = list(ticker_to_blocks.keys())
    logger.info(
        "Benchmark tickers to fetch",
        unique_tickers=len(unique_tickers),
        total_blocks=len(blocks),
        tickers=unique_tickers,
    )

    # 3. Batch download with retry
    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)
    hist = None

    loop = asyncio.get_event_loop()
    for attempt in range(MAX_RETRIES):
        try:
            hist = await loop.run_in_executor(
                _io_executor,
                _batch_download,
                unique_tickers,
                str(start_date),
                str(end_date),
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
                return {"blocks_updated": 0, "rows_upserted": 0, "stale_blocks": [], "skipped_tickers": unique_tickers}
            await asyncio.sleep(wait)

    if hist is None or hist.empty:
        logger.error("No data returned from yfinance batch download")
        return {"blocks_updated": 0, "rows_upserted": 0, "stale_blocks": [], "skipped_tickers": unique_tickers}

    is_multi = len(unique_tickers) > 1

    # 4. Process each ticker, validate, build rows
    all_rows: list[dict] = []
    blocks_updated: set[str] = set()
    skipped_tickers: list[str] = []

    for ticker, block_ids in ticker_to_blocks.items():
        try:
            ticker_data = hist[ticker] if is_multi else hist

            # Data validation: completely empty or all-NaN → invalid ticker
            close_col = ticker_data["Close"]
            if ticker_data.empty or close_col.isna().all():
                logger.error(
                    "benchmark_ticker_not_found — ticker returned no data from yfinance. "
                    "Check allocation_blocks.benchmark_ticker is a valid yfinance symbol.",
                    ticker=ticker,
                    block_ids=block_ids,
                )
                skipped_tickers.append(ticker)
                continue

            # Data validation: NaN ratio above threshold
            nan_ratio = float(close_col.isna().sum()) / max(len(close_col), 1)
            if nan_ratio > _MAX_NAN_RATIO:
                logger.error(
                    "benchmark_ticker_data_quality — NaN ratio too high",
                    ticker=ticker,
                    block_ids=block_ids,
                    nan_ratio=round(nan_ratio, 4),
                    threshold=_MAX_NAN_RATIO,
                )
                skipped_tickers.append(ticker)
                continue

            ticker_data = ticker_data.dropna(subset=["Close"])
            if ticker_data.empty:
                logger.error(
                    "benchmark_ticker_no_valid_prices — all rows filtered after NaN removal",
                    ticker=ticker,
                    block_ids=block_ids,
                )
                skipped_tickers.append(ticker)
                continue

            # Data validation: zero/negative prices
            has_invalid = (close_col.dropna() <= 0).any()
            if has_invalid:
                logger.error(
                    "benchmark_ticker_invalid_prices — zero or negative prices detected",
                    ticker=ticker,
                    block_ids=block_ids,
                )
                skipped_tickers.append(ticker)
                continue

            # Build rows with log returns
            rows: list[dict] = []
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
                    # Flag extreme returns — possible data error
                    if abs(return_1d) > 0.5:
                        logger.warning(
                            "Extreme benchmark return flagged",
                            ticker=ticker,
                            nav_date=str(nav_date),
                            log_return=round(return_1d, 6),
                        )

                prev_close = close_price

                # Create one row per block_id that uses this ticker
                for block_id in block_ids:
                    rows.append({
                        "block_id": block_id,
                        "nav_date": nav_date,
                        "nav": round(close_price, 6),
                        "return_1d": round(return_1d, 8) if return_1d is not None else None,
                        "return_type": "log",
                        "source": "yfinance",
                    })

            all_rows.extend(rows)
            blocks_updated.update(block_ids)
            logger.info(
                "Processed benchmark ticker",
                ticker=ticker,
                blocks=block_ids,
                rows=len(rows),
            )

        except (KeyError, TypeError) as e:
            logger.warning(
                "Ticker missing from batch result",
                ticker=ticker,
                error=str(e),
            )
            skipped_tickers.append(ticker)
            continue

    # 5. Chunked batch upsert
    total_upserted = 0
    if all_rows:
        for i in range(0, len(all_rows), UPSERT_CHUNK):
            chunk = all_rows[i : i + UPSERT_CHUNK]
            stmt = pg_insert(BenchmarkNav).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["block_id", "nav_date"],
                set_={
                    "nav": stmt.excluded.nav,
                    "return_1d": stmt.excluded.return_1d,
                    "return_type": stmt.excluded.return_type,
                    "source": stmt.excluded.source,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            await db.execute(stmt)
            await db.commit()
            total_upserted += len(chunk)

    # 6. Staleness check — single GROUP BY query instead of N+1 per-block selects
    stale_blocks: list[str] = []
    stale_cutoff = date.today() - timedelta(days=_STALE_THRESHOLD_DAYS)
    block_ids_all = [b.block_id for b in blocks]
    stale_stmt = (
        select(
            BenchmarkNav.block_id,
            func.max(BenchmarkNav.nav_date).label("latest_date"),
        )
        .where(BenchmarkNav.block_id.in_(block_ids_all))
        .group_by(BenchmarkNav.block_id)
    )
    stale_result = await db.execute(stale_stmt)
    latest_by_block: dict[str, date | None] = {row.block_id: row.latest_date for row in stale_result}

    block_ticker: dict[str, str] = {b.block_id: b.benchmark_ticker for b in blocks}
    for block_id in block_ids_all:
        latest_date = latest_by_block.get(block_id)
        if latest_date is None or latest_date < stale_cutoff:
            stale_blocks.append(block_id)
            logger.warning(
                "Stale benchmark data",
                block_id=block_id,
                ticker=block_ticker.get(block_id),
                latest_date=str(latest_date) if latest_date else "never",
            )

    logger.info(
        "Benchmark ingestion complete",
        blocks_updated=len(blocks_updated),
        rows_upserted=total_upserted,
        stale_blocks=stale_blocks,
        skipped_tickers=skipped_tickers,
    )

    return {
        "blocks_updated": len(blocks_updated),
        "rows_upserted": total_upserted,
        "stale_blocks": stale_blocks,
        "skipped_tickers": skipped_tickers,
    }


if __name__ == "__main__":
    asyncio.run(run_benchmark_ingest())
