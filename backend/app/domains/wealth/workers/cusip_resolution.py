"""CUSIP resolution worker — resolves pending CUSIPs to tickers via OpenFIGI.

Usage:
    python -m app.domains.wealth.workers.cusip_resolution

Drains _cusip_resolve_queue and resolves new CUSIPs from sec_13f_holdings
and sec_nport_holdings that are missing from sec_cusip_ticker_map.

Applies never-raises pattern: all exceptions are caught, logged, and the
worker always returns a summary dict.

GLOBAL TABLE: No organization_id, no RLS.
Advisory lock ID = 900_025.
"""

from __future__ import annotations

import asyncio
import os

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory as async_session

logger = structlog.get_logger()
CUSIP_RESOLUTION_LOCK_ID = 900_025

# ── Config ────────────────────────────────────────────────────────

_OPENFIGI_BATCH_URL = "https://api.openfigi.com/v3/mapping"
_MAX_BATCH_SIZE = 100  # OpenFIGI hard limit
_UPSERT_BATCH = 500
_MAX_CUSIPS_PER_RUN = 5_000  # cap per execution to respect rate limits
_TRADEABLE_EXCHANGES = frozenset({"US", "UN", "UW", "UA", "UR", "UT"})

# Exponential backoff for rate limits
_BACKOFF_BASE = 2.0
_BACKOFF_MAX = 120.0
_MAX_RETRIES = 3


async def run_cusip_resolution(*, max_cusips: int = _MAX_CUSIPS_PER_RUN) -> dict:
    """Resolve pending CUSIPs from queue + discover new unresolved CUSIPs.

    Three-phase process:
    1. Drain _cusip_resolve_queue entries not yet in sec_cusip_ticker_map
    2. Discover new CUSIPs from 13F/N-PORT holdings missing from the map
    3. Resolve via OpenFIGI batch API and upsert to sec_cusip_ticker_map

    Never raises — all errors are caught and logged.
    """
    async with async_session() as db:
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({CUSIP_RESOLUTION_LOCK_ID})"),
        )
        if not lock_result.scalar():
            logger.warning("cusip_resolution already running (advisory lock not acquired)")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            return await _resolve_cusips(db, max_cusips=max_cusips)
        except Exception as exc:
            logger.error("cusip_resolution_fatal", error=str(exc), exc_info=True)
            return {"status": "error", "error": str(exc)}
        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({CUSIP_RESOLUTION_LOCK_ID})"),
            )


async def _resolve_cusips(db: AsyncSession, *, max_cusips: int) -> dict:
    """Core resolution logic."""
    stats = {
        "status": "completed",
        "queue_drained": 0,
        "new_discovered": 0,
        "resolved": 0,
        "tradeable": 0,
        "unresolved": 0,
        "errors": 0,
    }

    # ── Phase 1: Drain queue — CUSIPs in _cusip_resolve_queue not yet resolved ──
    queue_result = await db.execute(text("""
        SELECT q.cusip, q.issuer_name
        FROM _cusip_resolve_queue q
        LEFT JOIN sec_cusip_ticker_map m ON q.cusip = m.cusip
        WHERE m.cusip IS NULL
        ORDER BY q.cusip
        LIMIT :lim
    """), {"lim": max_cusips})
    queue_rows = queue_result.fetchall()
    stats["queue_drained"] = len(queue_rows)

    # ── Phase 2: Discover new CUSIPs from holdings not in map ──
    remaining = max_cusips - len(queue_rows)
    discover_rows: list = []
    if remaining > 0:
        discover_result = await db.execute(text("""
            SELECT DISTINCT h.cusip, h.issuer_name
            FROM (
                SELECT cusip, issuer_name FROM sec_13f_holdings
                WHERE cusip IS NOT NULL AND LENGTH(cusip) = 9
                UNION
                SELECT cusip, issuer_name FROM sec_nport_holdings
                WHERE cusip IS NOT NULL AND LENGTH(cusip) = 9
            ) h
            LEFT JOIN sec_cusip_ticker_map m ON h.cusip = m.cusip
            WHERE m.cusip IS NULL
            ORDER BY h.cusip
            LIMIT :lim
        """), {"lim": remaining})
        discover_rows = discover_result.fetchall()
        stats["new_discovered"] = len(discover_rows)

    # Merge and deduplicate
    seen: set[str] = set()
    to_resolve: list[tuple[str, str | None]] = []
    for cusip, issuer_name in [*queue_rows, *discover_rows]:
        if cusip not in seen:
            seen.add(cusip)
            to_resolve.append((cusip, issuer_name))

    if not to_resolve:
        logger.info("cusip_resolution_nothing_to_do")
        return stats

    logger.info(
        "cusip_resolution_start",
        total=len(to_resolve),
        from_queue=stats["queue_drained"],
        from_discovery=stats["new_discovered"],
    )

    # ── Phase 3: Resolve via OpenFIGI ──
    api_key = os.environ.get("OPENFIGI_API_KEY")
    if not api_key:
        logger.warning("OPENFIGI_API_KEY not set — using free tier (25 req/min)")

    import httpx

    async with httpx.AsyncClient(timeout=30.0) as http:
        batches = [
            to_resolve[i: i + _MAX_BATCH_SIZE]
            for i in range(0, len(to_resolve), _MAX_BATCH_SIZE)
        ]

        rate_limit = 250 if api_key else 25
        sleep_between = 60.0 / rate_limit
        all_rows: list[dict] = []

        for batch_num, batch in enumerate(batches, 1):
            cusips = [c for c, _ in batch]
            rows = await _resolve_batch_with_backoff(http, cusips, api_key)

            for row in rows:
                if row["resolved_via"] != "unresolved":
                    stats["resolved"] += 1
                    if row["is_tradeable"]:
                        stats["tradeable"] += 1
                else:
                    stats["unresolved"] += 1
            all_rows.extend(rows)

            # Periodic upsert to avoid memory buildup
            if len(all_rows) >= 2000:
                await _upsert_rows(db, all_rows)
                all_rows.clear()

            if batch_num % 50 == 0:
                logger.info(
                    "cusip_resolution_progress",
                    batch=f"{batch_num}/{len(batches)}",
                    resolved=stats["resolved"],
                    unresolved=stats["unresolved"],
                )

            await asyncio.sleep(sleep_between)

        # Final upsert
        if all_rows:
            await _upsert_rows(db, all_rows)

    # ── Phase 4: Clean resolved entries from the queue ──
    cleaned = await _clean_resolved_from_queue(db)
    logger.info("cusip_resolution_queue_cleaned", removed=cleaned)

    logger.info("cusip_resolution_complete", **stats)
    return stats


# ── OpenFIGI batch resolution with exponential backoff ──────────


async def _resolve_batch_with_backoff(
    http: "httpx.AsyncClient",
    cusips: list[str],
    api_key: str | None,
) -> list[dict]:
    """Resolve a CUSIP batch via OpenFIGI with retry + exponential backoff.

    Never raises — returns unresolved placeholders on permanent failure.
    """
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["X-OPENFIGI-APIKEY"] = api_key

    payload = [{"idType": "ID_CUSIP", "idValue": c} for c in cusips]

    for attempt in range(_MAX_RETRIES):
        try:
            resp = await http.post(
                _OPENFIGI_BATCH_URL, json=payload, headers=headers,
            )

            if resp.status_code == 429:
                backoff = min(_BACKOFF_BASE * (2 ** attempt), _BACKOFF_MAX)
                logger.warning(
                    "openfigi_rate_limited",
                    attempt=attempt + 1,
                    backoff_s=backoff,
                )
                await asyncio.sleep(backoff)
                continue

            resp.raise_for_status()
            results = resp.json()

            if not isinstance(results, list) or len(results) != len(cusips):
                logger.warning(
                    "openfigi_bad_response",
                    expected=len(cusips),
                    got=len(results) if isinstance(results, list) else "non-list",
                )
                return [_unresolved(c) for c in cusips]

            return _parse_batch_results(cusips, results)

        except Exception as exc:
            backoff = min(_BACKOFF_BASE * (2 ** attempt), _BACKOFF_MAX)
            logger.warning(
                "openfigi_batch_error",
                attempt=attempt + 1,
                error=str(exc),
                backoff_s=backoff,
            )
            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(backoff)

    # All retries exhausted — return unresolved placeholders
    logger.error(
        "openfigi_batch_exhausted",
        cusips=len(cusips),
        max_retries=_MAX_RETRIES,
    )
    return [_unresolved(c) for c in cusips]


def _parse_batch_results(cusips: list[str], results: list[dict]) -> list[dict]:
    """Parse OpenFIGI batch response into upsert-ready dicts."""
    rows = []
    for cusip, result in zip(cusips, results, strict=True):
        if "data" not in result or not result["data"]:
            rows.append(_unresolved(cusip))
            continue

        best = _pick_best(result["data"])
        ticker = best.get("ticker")
        exchange = best.get("exchCode")
        rows.append({
            "cusip": cusip,
            "ticker": ticker,
            "issuer_name": best.get("name"),
            "exchange": exchange,
            "security_type": best.get("securityType"),
            "figi": best.get("figi"),
            "composite_figi": best.get("compositeFIGI"),
            "resolved_via": "openfigi",
            "is_tradeable": bool(ticker and exchange in _TRADEABLE_EXCHANGES),
        })
    return rows


def _unresolved(cusip: str) -> dict:
    return {
        "cusip": cusip,
        "ticker": None,
        "issuer_name": None,
        "exchange": None,
        "security_type": None,
        "figi": None,
        "composite_figi": None,
        "resolved_via": "unresolved",
        "is_tradeable": False,
    }


def _pick_best(candidates: list[dict]) -> dict:
    """Pick best match: prefer equity on US exchange."""
    equity_types = {"Common Stock", "ADR", "ETP"}
    us_exchanges = {"US", "UN", "UA", "UW"}

    equity = [c for c in candidates if c.get("securityType") in equity_types]
    pool = equity if equity else candidates

    us = [c for c in pool if c.get("exchCode") in us_exchanges]
    return us[0] if us else pool[0]


# ── DB operations ─────────────────────────────────────────────────

_UPSERT_SQL = """
    INSERT INTO sec_cusip_ticker_map
        (cusip, ticker, issuer_name, exchange, security_type,
         figi, composite_figi, resolved_via, is_tradeable, last_verified_at)
    VALUES (:cusip, :ticker, :issuer_name, :exchange, :security_type,
            :figi, :composite_figi, :resolved_via, :is_tradeable, NOW())
    ON CONFLICT (cusip) DO UPDATE SET
        ticker           = EXCLUDED.ticker,
        issuer_name      = EXCLUDED.issuer_name,
        exchange         = EXCLUDED.exchange,
        security_type    = EXCLUDED.security_type,
        figi             = EXCLUDED.figi,
        composite_figi   = EXCLUDED.composite_figi,
        resolved_via     = EXCLUDED.resolved_via,
        is_tradeable     = EXCLUDED.is_tradeable,
        last_verified_at = NOW()
    WHERE sec_cusip_ticker_map.resolved_via = 'unresolved'
       OR EXCLUDED.resolved_via != 'unresolved'
"""


async def _upsert_rows(db: AsyncSession, rows: list[dict]) -> None:
    """Batch upsert resolved CUSIPs to sec_cusip_ticker_map."""
    if not rows:
        return

    for i in range(0, len(rows), _UPSERT_BATCH):
        batch = rows[i: i + _UPSERT_BATCH]
        for row in batch:
            try:
                await db.execute(text(_UPSERT_SQL), row)
            except Exception as exc:
                logger.warning(
                    "cusip_upsert_row_failed",
                    cusip=row.get("cusip"),
                    error=str(exc),
                )
        await db.commit()


async def _clean_resolved_from_queue(db: AsyncSession) -> int:
    """Remove entries from _cusip_resolve_queue that are now in sec_cusip_ticker_map."""
    try:
        result = await db.execute(text("""
            DELETE FROM _cusip_resolve_queue q
            USING sec_cusip_ticker_map m
            WHERE q.cusip = m.cusip
              AND m.resolved_via != 'unresolved'
        """))
        await db.commit()
        return result.rowcount or 0
    except Exception as exc:
        await db.rollback()
        logger.warning("cusip_queue_cleanup_failed", error=str(exc))
        return 0


if __name__ == "__main__":
    asyncio.run(run_cusip_resolution())
