"""N-PORT ticker resolution worker — resolves tickers via OpenFIGI for registered funds.

Usage:
    python -m app.domains.wealth.workers.nport_ticker_resolution

Queries sec_registered_funds for funds without tickers, resolves via OpenFIGI
batch API using series_id, and updates the ticker field.

GLOBAL TABLE: No organization_id, no RLS.
Advisory lock ID = 900_025.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Sequence

import structlog
from sqlalchemy import text
from sqlalchemy.engine import Row

from app.core.db.engine import async_session_factory as async_session

logger = structlog.get_logger()
TICKER_LOCK_ID = 900_025
_OPENFIGI_BATCH_SIZE_NO_KEY = 10
_OPENFIGI_BATCH_SIZE_WITH_KEY = 100
_OPENFIGI_RATE_PER_MIN_NO_KEY = 25
_OPENFIGI_RATE_PER_MIN_WITH_KEY = 250
_MAX_FUNDS_PER_RUN = 500
_OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"


async def run_nport_ticker_resolution() -> dict[str, Any]:
    """Resolve tickers for registered funds without ticker via OpenFIGI."""
    async with async_session() as db:
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({TICKER_LOCK_ID})"),
        )
        if not lock_result.scalar():
            logger.warning("nport_ticker_resolution already running (advisory lock not acquired)")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            # Get funds needing ticker resolution
            result = await db.execute(
                text("""
                    SELECT cik, series_id, class_id, fund_name
                    FROM sec_registered_funds
                    WHERE ticker IS NULL
                      AND aum_below_threshold = FALSE
                    ORDER BY total_assets DESC NULLS LAST
                    LIMIT :limit
                """),
                {"limit": _MAX_FUNDS_PER_RUN},
            )
            funds = result.all()

            if not funds:
                logger.info("nport_ticker_no_funds_to_resolve")
                return {"status": "completed", "resolved": 0, "total": 0}

            api_key = os.environ.get("OPENFIGI_API_KEY")
            if not api_key:
                logger.warning("nport_ticker_resolution.no_api_key — using free tier (25 req/min × 10 jobs)")

            batch_size = _OPENFIGI_BATCH_SIZE_WITH_KEY if api_key else _OPENFIGI_BATCH_SIZE_NO_KEY
            rate_limit = _OPENFIGI_RATE_PER_MIN_WITH_KEY if api_key else _OPENFIGI_RATE_PER_MIN_NO_KEY
            sleep_between = 60.0 / rate_limit  # 0.24s with key, 2.4s without

            logger.info(
                "nport_ticker_resolution.start",
                funds=len(funds),
                batch_size=batch_size,
                rate_limit_per_min=rate_limit,
                has_api_key=bool(api_key),
            )

            resolved = 0
            errors = 0

            # Process in batches of 100 with API key, 10 without (OpenFIGI v3)
            for batch_start in range(0, len(funds), batch_size):
                batch = funds[batch_start:batch_start + batch_size]

                try:
                    tickers = await _resolve_batch_openfigi(batch, api_key=api_key)

                    for (cik, _, _, _), ticker in zip(batch, tickers, strict=True):
                        if ticker:
                            await db.execute(
                                text(
                                    "UPDATE sec_registered_funds "
                                    "SET ticker = :ticker "
                                    "WHERE cik = :cik",
                                ),
                                {"cik": cik, "ticker": ticker},
                            )
                            resolved += 1

                    await db.commit()

                except Exception as exc:
                    errors += 1
                    logger.warning(
                        "nport_ticker_batch_failed",
                        batch_start=batch_start,
                        error=str(exc),
                    )

                await asyncio.sleep(sleep_between)

            summary = {
                "status": "completed",
                "total": len(funds),
                "resolved": resolved,
                "errors": errors,
            }
            logger.info("nport_ticker_resolution_complete", **summary)
            return summary

        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({TICKER_LOCK_ID})"),
            )


async def _resolve_batch_openfigi(
    batch: Sequence[Row[Any] | tuple[Any, ...]],
    *,
    api_key: str | None = None,
) -> list[str | None]:
    """Resolve a batch of funds to tickers via OpenFIGI.

    Each batch item: (cik, series_id, class_id, fund_name).
    Returns list of resolved tickers (or None) in same order.
    """
    import httpx

    payload = []
    for _, series_id, class_id, fund_name in batch:
        # Try series ID first, then fund name
        if series_id:
            payload.append({"idType": "BASE_TICKER", "idValue": series_id})
        else:
            payload.append({"idType": "BASE_TICKER", "idValue": fund_name or ""})

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-OPENFIGI-APIKEY"] = api_key

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                _OPENFIGI_URL,
                json=payload,
                headers=headers,
                timeout=30.0,
            )
            if resp.status_code != 200:
                logger.warning("openfigi_batch_status", status=resp.status_code)
                return [None] * len(batch)

            results = resp.json()
            if not isinstance(results, list) or len(results) != len(batch):
                return [None] * len(batch)

            tickers: list[str | None] = []
            for result in results:
                if result.get("data"):
                    ticker = result["data"][0].get("ticker")
                    tickers.append(ticker)
                else:
                    tickers.append(None)

            return tickers

    except Exception as exc:
        logger.warning("openfigi_batch_failed", error=str(exc))
        return [None] * len(batch)


if __name__ == "__main__":
    asyncio.run(run_nport_ticker_resolution())
