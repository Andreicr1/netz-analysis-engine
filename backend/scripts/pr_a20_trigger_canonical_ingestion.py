"""PR-A20 Section B — one-off NAV ingestion for canonical tickers.

Pulls 5y of daily OHLC from the configured instrument provider for
the 5 tickers that are missing NAV history after migration 0147:

* VTI — in the catalog, 0 nav_timeseries rows (audit evidence
  2026-04-18 01:15 UTC).
* IVV, BND, TLT, SHY — freshly inserted by migration 0147.

Scoped to these tickers only so it runs in <30s; the full
`instrument_ingestion` worker (~9k tickers) is not required. Writes
into the global `nav_timeseries` hypertable, bypassing the advisory
lock because this is a narrow manual trigger, not the nightly worker
path.

Idempotent — `ON CONFLICT (instrument_id, nav_date)` DO UPDATE preserves
the latest provider value. Safe to re-run.
"""
from __future__ import annotations

import asyncio
import math
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.db.engine import async_session_factory  # noqa: E402
from app.services.providers import get_instrument_provider  # noqa: E402

logger = structlog.get_logger()

CANONICAL_TICKERS = ["VTI", "IVV", "BND", "TLT", "SHY"]
LOOKBACK_PERIOD = "5y"  # ≥ 1260 trading days per spec §1.B
UPSERT_CHUNK = 500


async def main() -> None:
    async with async_session_factory() as db:
        db.expire_on_commit = False  # type: ignore[attr-defined]

        ticker_map: dict[str, str] = {}
        for ticker in CANONICAL_TICKERS:
            row = await db.execute(
                text(
                    "SELECT instrument_id::text FROM instruments_universe "
                    "WHERE ticker = :t AND is_active LIMIT 1"
                ),
                {"t": ticker},
            )
            instrument_id = row.scalar()
            if not instrument_id:
                logger.warning("ticker_not_in_catalog", ticker=ticker)
                continue
            ticker_map[ticker] = instrument_id

        if not ticker_map:
            print("No canonical tickers resolved — aborting.")
            return

        provider = get_instrument_provider()
        history = await asyncio.to_thread(
            provider.fetch_batch_history,
            list(ticker_map.keys()),
            LOOKBACK_PERIOD,
        )

        all_rows: list[dict[str, object]] = []
        for ticker, instrument_id in ticker_map.items():
            ticker_data = history.get(ticker) if history else None
            if ticker_data is None or ticker_data.empty:
                print(f"{ticker}: provider returned no data")
                continue
            if "Close" not in ticker_data.columns:
                print(f"{ticker}: no Close column")
                continue
            ticker_data = ticker_data.dropna(subset=["Close"])
            prev_close: float | None = None
            count = 0
            for idx, row in ticker_data.iterrows():
                nav_date = idx.date() if hasattr(idx, "date") else idx
                close_price = float(row["Close"])
                if close_price <= 0:
                    prev_close = None
                    continue
                return_1d = None
                if prev_close is not None and prev_close > 0:
                    return_1d = math.log(close_price / prev_close)
                prev_close = close_price
                all_rows.append(
                    {
                        "instrument_id": instrument_id,
                        "nav_date": nav_date,
                        "nav": round(close_price, 6),
                        "return_1d": round(return_1d, 8)
                        if return_1d is not None
                        else None,
                        "return_type": "log",
                        "currency": "USD",
                        "source": "tiingo",
                    }
                )
                count += 1
            print(f"{ticker}: {count} rows prepared")

        if not all_rows:
            print("No rows to upsert.")
            return

        upsert_sql = text(
            """
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
            """
        )
        total = 0
        for i in range(0, len(all_rows), UPSERT_CHUNK):
            chunk = all_rows[i : i + UPSERT_CHUNK]
            await db.execute(upsert_sql, chunk)
            await db.commit()
            total += len(chunk)
        print(f"Upserted {total} NAV rows across {len(ticker_map)} tickers.")


if __name__ == "__main__":
    asyncio.run(main())
