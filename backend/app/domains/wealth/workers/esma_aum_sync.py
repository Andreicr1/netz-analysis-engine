"""ESMA UCITS AUM enrichment via Yahoo Finance — GLOBAL.

Fetches AUM (totalAssets) from Yahoo Finance for UCITS funds with resolved
yahoo_ticker in esma_funds.  Converts native currency to USD using FX rates
(also from Yahoo) and writes to instruments_universe.attributes (JSONB).

Lock ID: 900_111 (global)
Frequency: weekly
Scope: global — ESMA data shared across all tenants
Sources: yfinance Ticker.info["totalAssets"], Ticker("<CCY>USD=X").info for FX
Idempotency: skips funds with aum_fetched_at < 7 days ago
Charter §3 compliance:
  - ExternalProviderGate (30s per-call, circuit breaker after 10 failures)
  - Advisory lock via pg_try_advisory_lock(900_111)
  - Degraded propagation — individual fund failures logged + marked, worker continues
  - DB-first — writes to instruments_universe.attributes; no Yahoo in user-facing path
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import time
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text

from app.core.db.engine import async_session_factory
from app.core.runtime.provider_gate import (
    ExternalProviderGate,
    GateConfig,
    ProviderGateError,
)

logger = structlog.get_logger()

ESMA_AUM_SYNC_LOCK_ID = 900_111

# Yahoo gate — per-call timeout 30s, circuit opens after 10 consecutive failures
_yahoo_gate: ExternalProviderGate[Any] = ExternalProviderGate(
    GateConfig(
        name="yahoo_aum",
        timeout_s=30.0,
        failure_threshold=10,
        recovery_after_s=60.0,
    ),
)

# Isolated gate for Q87 priority batch — smaller threshold so a bad run
# fails fast without poisoning the main gate's circuit state.
_q87_priority_gate: ExternalProviderGate[Any] = ExternalProviderGate(
    GateConfig(
        name="yahoo_aum_priority_q87",
        timeout_s=30.0,
        failure_threshold=5,
        recovery_after_s=60.0,
    ),
)

# Thread pool for blocking yfinance calls
_io_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="esma-aum-io",
)

_MAX_CONCURRENT = 4
_LOG_BATCH_SIZE = 100
_UPDATE_CHUNK = 50

# FX pairs for UCITS domicile currencies → USD
_CURRENCY_FX_PAIRS: dict[str, str] = {
    "EUR": "EURUSD=X",
    "GBP": "GBPUSD=X",
    "CHF": "CHFUSD=X",
    "SEK": "SEKUSD=X",
    "DKK": "DKKUSD=X",
    "NOK": "NOKUSD=X",
}

# Yahoo returns sub-unit codes for some exchanges (e.g. GBp = pence on LSE).
# totalAssets is in full units regardless, so normalise to parent currency.
_CURRENCY_NORMALIZE: dict[str, str] = {
    "GBp": "GBP",
    "ILA": "ILS",
    "ZAc": "ZAR",
}


# ---------------------------------------------------------------------------
# Blocking helpers (run in thread pool)
# ---------------------------------------------------------------------------


def _sync_fetch_info(ticker: str) -> dict[str, Any]:
    """Blocking yfinance Ticker.info call.

    Catches expected HTTP errors (404 Not Found, 401 Unauthorized/rate-limit)
    so the ExternalProviderGate circuit breaker only trips on real network
    failures, not on "ticker unknown" or transient 401 rate limits.
    """
    import yfinance as yf

    try:
        t = yf.Ticker(ticker)
        return dict(t.info) if t.info else {}
    except Exception as exc:
        msg = str(exc)
        # 404 / 401 are expected — ticker not found or rate-limited.
        # Return empty dict so gate does not count these as failures.
        if "404" in msg or "401" in msg or "Not Found" in msg or "Unauthorized" in msg:
            return {}
        raise  # Real network error → let gate handle it


def _sync_fetch_fx_rate(pair: str) -> float | None:
    """Blocking yfinance FX rate fetch."""
    import yfinance as yf

    t = yf.Ticker(pair)
    info = t.info or {}
    rate = info.get("regularMarketPrice") or info.get("previousClose")
    if rate and isinstance(rate, (int, float)) and rate > 0:
        return float(rate)
    return None


# ---------------------------------------------------------------------------
# FX cache (per-run in-memory)
# ---------------------------------------------------------------------------

_fx_cache: dict[str, float] = {}


async def _fetch_fx_rates() -> dict[str, float]:
    """Fetch USD conversion rates for common UCITS currencies."""
    global _fx_cache  # noqa: PLW0603
    _fx_cache = {"USD": 1.0}
    loop = asyncio.get_event_loop()

    for currency, pair in _CURRENCY_FX_PAIRS.items():
        try:
            async def _fx_coro(p: str = pair) -> Any:
                return await loop.run_in_executor(
                    _io_executor, _sync_fetch_fx_rate, p,
                )

            rate = await _yahoo_gate.call(
                op_key=f"fx:{pair}",
                coro_factory=_fx_coro,
            )
            if rate:
                _fx_cache[currency] = rate
                logger.info(
                    "esma_aum_sync.fx_rate",
                    currency=currency,
                    rate=round(rate, 6),
                )
            else:
                logger.warning(
                    "esma_aum_sync.fx_rate_unavailable",
                    currency=currency,
                )
        except ProviderGateError as e:
            logger.warning(
                "esma_aum_sync.fx_rate_unavailable",
                currency=currency,
                error=str(e)[:200],
            )

    return _fx_cache


async def _resolve_fx(currency: str) -> float | None:
    """Resolve FX rate from cache, fetching on-the-fly if missing."""
    if currency in _fx_cache:
        return _fx_cache[currency]
    # Try fetching an unknown currency on-the-fly
    pair = f"{currency}USD=X"
    loop = asyncio.get_event_loop()
    try:
        async def _fx_coro() -> Any:
            return await loop.run_in_executor(
                _io_executor, _sync_fetch_fx_rate, pair,
            )

        rate: Any = await _yahoo_gate.call(
            op_key=f"fx:{pair}",
            coro_factory=_fx_coro,
        )
        if rate:
            _fx_cache[currency] = float(rate)
            return float(rate)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def run_esma_aum_sync(
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """Fetch AUM from Yahoo Finance for UCITS funds with yahoo_ticker.

    Parameters
    ----------
    limit : int | None
        Max funds to process (for smoke testing).  None = all candidates.
    """
    t0 = time.monotonic()
    logger.info("esma_aum_sync.start", limit=limit)

    async with async_session_factory() as db:
        lock = await db.execute(
            text(f"SELECT pg_try_advisory_lock({ESMA_AUM_SYNC_LOCK_ID})"),
        )
        if not lock.scalar():
            logger.warning("esma_aum_sync.lock_held")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            return await _do_sync(db, limit=limit, t0=t0)
        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({ESMA_AUM_SYNC_LOCK_ID})"),
            )


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


async def _do_sync(
    db: Any,
    *,
    limit: int | None,
    t0: float,
) -> dict[str, Any]:
    """Fetch AUM, convert to USD, update instruments_universe."""

    # 1. FX rates upfront
    fx_rates = await _fetch_fx_rates()
    logger.info(
        "esma_aum_sync.fx_rates_loaded",
        currencies=list(fx_rates.keys()),
    )

    loop = asyncio.get_event_loop()

    # ── Phase 1: priority batch — Q87 manual-seed funds FIRST ──
    # These are explicit institutional blue-chips that must clear before
    # the main batch risks tripping the Yahoo circuit breaker.
    priority_result = await db.execute(
        text("""
            SELECT ticker,
                   attributes->>'fund_lei' AS lei
            FROM instruments_universe
            WHERE attributes->>'fund_subtype' = 'ucits'
              AND (attributes->>'_q87_manual_seed')::bool = true
              AND ticker IS NOT NULL
              AND (
                  (attributes->>'aum_fetched_at')::timestamptz
                      < NOW() - INTERVAL '7 days'
                  OR attributes->>'aum_fetched_at' IS NULL
              )
            ORDER BY ticker
        """),
    )
    priority_candidates = priority_result.fetchall()

    priority_updates: list[dict[str, Any]] = []
    priority_populated = 0
    priority_degraded = 0
    if priority_candidates:
        logger.info(
            "esma_aum_sync.priority_batch_start",
            count=len(priority_candidates),
        )
        priority_updates, priority_populated, priority_degraded = (
            await _process_candidates(
                priority_candidates, loop, gate=_q87_priority_gate, label="priority_q87",
            )
        )
        logger.info(
            "esma_aum_sync.priority_batch_complete",
            populated=priority_populated,
            degraded=priority_degraded,
        )

    # ── Phase 2: main batch — remaining UCITS funds ──
    # Gate may trip mid-batch; acceptable for non-priority funds since they
    # have no institutional commitment yet.
    limit_clause = f"LIMIT {int(limit)}" if limit else ""
    main_result = await db.execute(
        text(f"""
            SELECT ticker,
                   attributes->>'fund_lei' AS lei
            FROM instruments_universe
            WHERE attributes->>'fund_subtype' = 'ucits'
              AND COALESCE((attributes->>'_q87_manual_seed')::bool, false) = false
              AND ticker IS NOT NULL
              AND (
                  (attributes->>'aum_fetched_at')::timestamptz
                      < NOW() - INTERVAL '7 days'
                  OR attributes->>'aum_fetched_at' IS NULL
              )
            ORDER BY ticker
            {limit_clause}
        """),
    )
    main_candidates = main_result.fetchall()

    main_updates: list[dict[str, Any]] = []
    main_populated = 0
    main_degraded = 0
    if main_candidates:
        logger.info(
            "esma_aum_sync.main_batch_start",
            count=len(main_candidates),
        )
        main_updates, main_populated, main_degraded = (
            await _process_candidates(
                main_candidates, loop, gate=_yahoo_gate, label="main",
            )
        )

    # ── Merge + persist ──
    all_updates = priority_updates + main_updates
    total_candidates = len(priority_candidates) + len(main_candidates)
    aum_populated = priority_populated + main_populated
    degraded_count = priority_degraded + main_degraded

    now_str = datetime.now(timezone.utc).isoformat()
    updated_rows = await _batch_update(db, all_updates, now_str)

    elapsed = round(time.monotonic() - t0, 1)
    logger.info(
        "esma_aum_sync.complete",
        total_processed=total_candidates,
        priority_populated=priority_populated,
        priority_degraded=priority_degraded,
        main_populated=main_populated,
        main_degraded=main_degraded,
        updated_rows=updated_rows,
        duration_seconds=elapsed,
    )
    return _summary(total_candidates, aum_populated, degraded_count, updated_rows, elapsed)


async def _process_candidates(
    candidates: list[Any],
    loop: asyncio.AbstractEventLoop,
    *,
    gate: ExternalProviderGate[Any],
    label: str,
) -> tuple[list[dict[str, Any]], int, int]:
    """Process a batch of candidates using the given gate.

    Returns (updates, aum_populated, degraded_count).
    """
    sem = asyncio.Semaphore(_MAX_CONCURRENT)

    async def _process_one(ticker: str, lei: str | None) -> dict[str, Any]:
        async with sem:
            return await _fetch_aum(ticker, lei or "", loop, gate=gate)

    updates: list[dict[str, Any]] = []
    aum_populated = 0
    degraded_count = 0

    coroutines = [_process_one(r.ticker, r.lei) for r in candidates]
    for batch_start in range(0, len(coroutines), _LOG_BATCH_SIZE):
        batch = coroutines[batch_start : batch_start + _LOG_BATCH_SIZE]
        batch_results = await asyncio.gather(*batch, return_exceptions=True)

        for r in batch_results:
            if isinstance(r, BaseException):
                degraded_count += 1
                continue
            updates.append(r)
            if r.get("aum_usd") is not None:
                aum_populated += 1
            else:
                degraded_count += 1

        logger.info(
            "esma_aum_sync.batch_progress",
            label=label,
            processed=min(batch_start + len(batch), len(candidates)),
            remaining=max(0, len(candidates) - batch_start - len(batch)),
            aum_populated=aum_populated,
            degraded=degraded_count,
        )

    return updates, aum_populated, degraded_count


# ---------------------------------------------------------------------------
# Per-ticker fetch + convert
# ---------------------------------------------------------------------------


async def _fetch_aum(
    ticker: str,
    lei: str,
    loop: asyncio.AbstractEventLoop,
    *,
    gate: ExternalProviderGate[Any] | None = None,
) -> dict[str, Any]:
    """Fetch Yahoo info for *ticker*, convert totalAssets to USD."""
    _gate = gate or _yahoo_gate
    try:
        async def _info_coro() -> Any:
            return await loop.run_in_executor(
                _io_executor, _sync_fetch_info, ticker,
            )

        info: dict[str, Any] = await _gate.call(
            op_key=f"info:{ticker}",
            coro_factory=_info_coro,
        )
    except ProviderGateError as e:
        logger.warning(
            "esma_aum_sync.fund_degraded",
            lei=lei,
            ticker=ticker,
            reason=f"yahoo_gate_error: {e}",
        )
        return _degraded(ticker, "yahoo_gate_error")
    except Exception as e:
        logger.warning(
            "esma_aum_sync.fund_degraded",
            lei=lei,
            ticker=ticker,
            reason=str(e)[:200],
        )
        return _degraded(ticker, "yahoo_fetch_error")

    raw_currency = info.get("currency", "USD")
    currency = _CURRENCY_NORMALIZE.get(raw_currency, raw_currency)

    aum_native, aum_method = _extract_aum(info)
    if aum_native is None:
        logger.debug(
            "esma_aum_sync.fund_degraded",
            lei=lei,
            ticker=ticker,
            reason="yahoo_totalAssets_missing",
        )
        return _degraded(ticker, "yahoo_totalAssets_missing", currency=currency)

    # FX conversion
    fx_rate = await _resolve_fx(currency)
    if fx_rate is None:
        logger.warning(
            "esma_aum_sync.fund_degraded",
            lei=lei,
            ticker=ticker,
            reason="fx_unavailable",
            currency=currency,
        )
        return _degraded(
            ticker,
            f"fx_unavailable_{currency}",
            aum_native=aum_native,
            currency=currency,
        )

    aum_usd = round(aum_native * fx_rate, 2)
    logger.debug(
        "esma_aum_sync.fund_aum_fetched",
        lei=lei,
        ticker=ticker,
        aum_usd=aum_usd,
        aum_method=aum_method,
        currency_native=currency,
        fx_rate=round(fx_rate, 6),
    )
    return {
        "ticker": ticker,
        "aum_usd": aum_usd,
        "aum_native": aum_native,
        "aum_native_currency": currency,
        "aum_method": aum_method,
        "aum_degraded": False,
        "aum_degraded_reason": None,
    }


def _extract_aum(info: dict[str, Any]) -> tuple[float | None, str]:
    """Extract AUM from Yahoo info dict with fallback to nav x shares.

    Returns (aum, method). method in {'totalAssets', 'nav_x_shares', 'unavailable'}.
    """
    total_assets = info.get("totalAssets")
    if (
        total_assets is not None
        and isinstance(total_assets, (int, float))
        and total_assets > 0
    ):
        return float(total_assets), "totalAssets"

    # Fallback: derive from navPrice x sharesOutstanding (typical for .L ETFs)
    nav = info.get("navPrice") or info.get("regularMarketPrice")
    shares = info.get("sharesOutstanding")
    if (
        nav is not None
        and shares is not None
        and isinstance(nav, (int, float))
        and isinstance(shares, (int, float))
        and nav > 0
        and shares > 0
    ):
        return float(nav) * float(shares), "nav_x_shares"

    return None, "unavailable"


def _degraded(
    ticker: str,
    reason: str,
    *,
    aum_native: float | None = None,
    currency: str | None = None,
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "aum_usd": None,
        "aum_native": aum_native,
        "aum_native_currency": currency,
        "aum_degraded": True,
        "aum_degraded_reason": reason,
    }


# ---------------------------------------------------------------------------
# DB batch update
# ---------------------------------------------------------------------------


async def _batch_update(
    db: Any,
    updates: list[dict[str, Any]],
    now_str: str,
) -> int:
    """Write AUM results back to instruments_universe.attributes.

    Split write paths:
    - Successful fetches: overwrite all AUM fields + bump aum_fetched_at.
    - Degraded fetches: only update aum_degraded/aum_degraded_reason/aum_last_attempt_at.
      Preserves prior aum_usd + aum_fetched_at so the 7-day retry window stays open.

    Each row UPDATE is wrapped in a SAVEPOINT so a single-row failure
    does not abort the outer transaction (PostgreSQL semantics).
    """
    update_sql = text("""
        UPDATE instruments_universe
        SET attributes = attributes || CAST(:attrs AS jsonb),
            updated_at = now()
        WHERE ticker = :ticker
          AND attributes->>'fund_subtype' = 'ucits'
    """)

    total = 0
    for i in range(0, len(updates), _UPDATE_CHUNK):
        chunk = updates[i : i + _UPDATE_CHUNK]
        for u in chunk:
            is_degraded = u.get("aum_degraded", False)

            if is_degraded:
                # Preserve last good AUM — only track failure metadata
                attrs: dict[str, Any] = {
                    "aum_degraded": True,
                    "aum_degraded_reason": u["aum_degraded_reason"],
                    "aum_last_attempt_at": now_str,
                }
            else:
                attrs = {
                    "aum_usd": u["aum_usd"],
                    "aum_native": u["aum_native"],
                    "aum_native_currency": u["aum_native_currency"],
                    "aum_source": "yahoo_finance",
                    "aum_method": u.get("aum_method", "totalAssets"),
                    "aum_fetched_at": now_str,
                    "aum_degraded": False,
                    "aum_degraded_reason": None,
                    "aum_last_attempt_at": now_str,
                }

            sp = await db.begin_nested()  # SAVEPOINT
            try:
                await db.execute(
                    update_sql,
                    {"ticker": u["ticker"], "attrs": json.dumps(attrs)},
                )
                await sp.commit()  # RELEASE SAVEPOINT
                total += 1
            except Exception as e:
                await sp.rollback()  # ROLLBACK TO SAVEPOINT
                logger.warning(
                    "esma_aum_sync.update_failed",
                    ticker=u["ticker"],
                    error=str(e)[:200],
                )
        await db.commit()
    return total


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _summary(
    total: int,
    populated: int,
    degraded: int,
    updated: int,
    elapsed: float,
) -> dict[str, Any]:
    return {
        "status": "complete",
        "total_processed": total,
        "aum_populated": populated,
        "degraded": degraded,
        "updated_rows": updated,
        "duration_seconds": elapsed,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    result = asyncio.run(run_esma_aum_sync(limit=limit))
    print(json.dumps(result, indent=2))
