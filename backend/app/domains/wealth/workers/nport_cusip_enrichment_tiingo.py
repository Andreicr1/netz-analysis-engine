"""N-PORT CUSIP sector enrichment via Tiingo Fundamentals Meta.

Closes the PR-Q4 enrichment gap: after the holdings matview ships, 15k+
equity CUSIPs in sec_nport_holdings still carry raw N-PORT issuer codes
(CORP, EC, EP) instead of GICS sectors. The default enrichment path in
data_providers/sec/shared.py (SIC heuristic → OpenFIGI marketSector →
keyword) has poor yield on the long tail.

This worker uses Tiingo's /tiingo/fundamentals/meta endpoint, which
returns `sector` (GICS-approximate) and `industry` derived from SEC SIC
filings — 100% coverage for US equities.

Two-phase pipeline:

    A) CUSIP → ticker via OpenFIGI batch (100 CUSIPs/request)
    B) ticker → Tiingo fundamentals meta (100 tickers/request)

Results upsert `gics_sector`, `tiingo_industry`, `sic_code`, `ticker` into
sec_cusip_ticker_map; propagates `gics_sector` into sec_nport_holdings
for all matching equity holdings; refreshes mv_nport_sector_attribution
CONCURRENTLY at the end.

GLOBAL table, no RLS. Advisory lock 900_110. Fail-open on all API calls
(individual batch failures logged but don't abort the run). Idempotent —
safe to re-run; skips rows already enriched in the last 90 days.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Iterable
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory as async_session

logger = structlog.get_logger()

NPORT_TIINGO_ENRICHMENT_LOCK_ID = 900_110
_OPENFIGI_BATCH_SIZE = 100
_TIINGO_BATCH_SIZE = 100
# Tiingo free fundamentals tier: ~2400 req/hr. 100 tickers/req → ~4M
# tickers/hr. The real bottleneck is OpenFIGI (25 req/min free tier).
# Default cadence adds a small sleep between batches to be polite.
_OPENFIGI_BATCH_SLEEP_S = 2.5
_TIINGO_BATCH_SLEEP_S = 0.3
# Skip tickers whose meta was fetched in the last N days (re-enrich later).
_TIINGO_STALENESS_DAYS = 90

# N-PORT raw codes that indicate "no GICS classification yet" in
# sec_nport_holdings.sector. Mirrors the list in nport_ingestion worker.
_RAW_NPORT_CODES: tuple[str, ...] = (
    "CORP", "UST", "USGA", "USGSE", "NUSS", "MUN", "RF", "PF", "OTHER", "EC", "OT",
)

TIINGO_META_URL = "https://api.tiingo.com/tiingo/fundamentals/meta"

# Tiingo free/evaluation tier returns this literal string in every restricted
# field instead of null. We must scrub before hitting the DB, otherwise the
# INTEGER sic_code UPDATE aborts with DatatypeMismatch and kills the whole
# transaction. Seen on tickers outside the DOW-30-ish evaluation whitelist.
_TIINGO_GATED_SENTINEL = "Field not available for free/evaluation"


def _scrub_tiingo_value(value: Any) -> Any:
    """Convert the Tiingo evaluation-gate sentinel into None."""
    if isinstance(value, str) and value == _TIINGO_GATED_SENTINEL:
        return None
    return value


async def run(
    *,
    max_openfigi_batches: int | None = None,
    max_tiingo_batches: int | None = None,
) -> dict[str, Any]:
    """Run a full enrichment cycle.

    Parameters cap API calls for safety when running ad-hoc. In production
    scheduling, both are None (process everything).
    """
    async with async_session() as db:
        got = await db.execute(
            text(f"SELECT pg_try_advisory_lock({NPORT_TIINGO_ENRICHMENT_LOCK_ID})"),
        )
        if not got.scalar():
            logger.warning("nport_cusip_tiingo_enrichment_lock_held")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            phase_a = await _phase_resolve_tickers(
                db, max_batches=max_openfigi_batches,
            )
            phase_b = await _phase_fetch_tiingo_meta(
                db, max_batches=max_tiingo_batches,
            )
            propagated = await _propagate_to_nport_holdings(db)
            summary = {
                "status": "completed",
                "phase_a": phase_a,
                "phase_b": phase_b,
                "nport_rows_updated": propagated,
            }
            logger.info("nport_cusip_tiingo_enrichment_complete", **summary)
        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({NPORT_TIINGO_ENRICHMENT_LOCK_ID})"),
            )

    # Matview refresh outside the lock (same pattern as nport_ingestion).
    refresh = await _refresh_matview()
    summary["matview_refresh"] = refresh
    return summary


# ---------------------------------------------------------------------------
# Phase A — CUSIP → ticker via OpenFIGI
# ---------------------------------------------------------------------------


async def _phase_resolve_tickers(
    db: AsyncSession,
    *,
    max_batches: int | None,
) -> dict[str, Any]:
    """Upsert tickers for distinct equity CUSIPs in N-PORT that lack them.

    Pulls CUSIPs present in sec_nport_holdings as equity (EC/EP) whose
    sector is still a raw N-PORT code and whose corresponding row in
    sec_cusip_ticker_map either doesn't exist or has no ticker. Tiny
    working set — the matview enrichment runs pick them up within days.
    """
    api_key = os.getenv("OPENFIGI_API_KEY")
    cusips_needed = await _distinct_cusips_without_ticker(db)
    logger.info("nport_cusip_tiingo_phase_a_start", candidates=len(cusips_needed))

    if not cusips_needed:
        return {"candidates": 0, "resolved": 0, "batches": 0, "skipped": True}

    resolved_total = 0
    batches_run = 0

    import httpx

    from data_providers.sec.shared import resolve_cusip_to_ticker_batch

    async with httpx.AsyncClient() as http_client:
        for batch in _chunks(cusips_needed, _OPENFIGI_BATCH_SIZE):
            if max_batches is not None and batches_run >= max_batches:
                break
            try:
                results = await resolve_cusip_to_ticker_batch(
                    list(batch),
                    http_client=http_client,
                    api_key=api_key,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "nport_cusip_tiingo_openfigi_batch_failed",
                    error=str(exc),
                    batch_size=len(batch),
                )
                batches_run += 1
                await asyncio.sleep(_OPENFIGI_BATCH_SLEEP_S)
                continue

            resolved = await _upsert_ticker_map(db, results)
            resolved_total += resolved
            batches_run += 1
            logger.info(
                "nport_cusip_tiingo_openfigi_batch_done",
                batch=batches_run,
                resolved=resolved,
                size=len(batch),
            )
            await asyncio.sleep(_OPENFIGI_BATCH_SLEEP_S)

    return {
        "candidates": len(cusips_needed),
        "resolved": resolved_total,
        "batches": batches_run,
    }


async def _distinct_cusips_without_ticker(db: AsyncSession) -> list[str]:
    """Equity CUSIPs in N-PORT with raw sector + no ticker in the map yet."""
    rows = (await db.execute(text("""
        SELECT DISTINCT h.cusip
        FROM sec_nport_holdings h
        LEFT JOIN sec_cusip_ticker_map m ON m.cusip = h.cusip
        WHERE h.asset_class IN ('EC', 'EP')
          AND h.sector = ANY(:raw_codes)
          AND (m.ticker IS NULL OR m.cusip IS NULL)
    """), {"raw_codes": list(_RAW_NPORT_CODES)})).all()
    return [r[0] for r in rows if r[0]]


async def _upsert_ticker_map(
    db: AsyncSession, results: Iterable[Any],
) -> int:
    """Upsert CusipTickerResult rows into sec_cusip_ticker_map."""
    payload = []
    for r in results:
        ticker = r.ticker or None
        payload.append({
            "cusip": r.cusip,
            "ticker": ticker,
            "issuer_name": r.issuer_name,
            "exchange": r.exchange,
            "security_type": r.security_type,
            "figi": r.figi,
            "composite_figi": r.composite_figi,
            "resolved_via": "openfigi" if ticker else "openfigi_unresolved",
            "is_tradeable": bool(ticker),
        })

    if not payload:
        return 0

    await db.execute(text("""
        INSERT INTO sec_cusip_ticker_map
            (cusip, ticker, issuer_name, exchange, security_type,
             figi, composite_figi, resolved_via, is_tradeable, last_verified_at)
        VALUES
            (:cusip, :ticker, :issuer_name, :exchange, :security_type,
             :figi, :composite_figi, :resolved_via, :is_tradeable, now())
        ON CONFLICT (cusip) DO UPDATE SET
            ticker = COALESCE(EXCLUDED.ticker, sec_cusip_ticker_map.ticker),
            issuer_name = COALESCE(EXCLUDED.issuer_name, sec_cusip_ticker_map.issuer_name),
            exchange = COALESCE(EXCLUDED.exchange, sec_cusip_ticker_map.exchange),
            security_type = COALESCE(EXCLUDED.security_type, sec_cusip_ticker_map.security_type),
            figi = COALESCE(EXCLUDED.figi, sec_cusip_ticker_map.figi),
            composite_figi = COALESCE(EXCLUDED.composite_figi, sec_cusip_ticker_map.composite_figi),
            resolved_via = EXCLUDED.resolved_via,
            is_tradeable = EXCLUDED.is_tradeable,
            last_verified_at = now()
    """), payload)
    await db.commit()
    return sum(1 for p in payload if p["ticker"])


# ---------------------------------------------------------------------------
# Phase B — ticker → Tiingo fundamentals meta
# ---------------------------------------------------------------------------


async def _phase_fetch_tiingo_meta(
    db: AsyncSession,
    *,
    max_batches: int | None,
) -> dict[str, Any]:
    api_key = os.getenv("TIINGO_API_KEY")
    if not api_key:
        logger.warning("nport_cusip_tiingo_phase_b_no_key")
        return {"candidates": 0, "enriched": 0, "batches": 0, "skipped": True}

    tickers = await _distinct_tickers_needing_meta(db)
    logger.info("nport_cusip_tiingo_phase_b_start", candidates=len(tickers))

    if not tickers:
        return {"candidates": 0, "enriched": 0, "batches": 0}

    enriched_total = 0
    batches_run = 0

    import httpx

    async with httpx.AsyncClient(timeout=30.0) as http_client:
        for batch in _chunks(tickers, _TIINGO_BATCH_SIZE):
            if max_batches is not None and batches_run >= max_batches:
                break

            metas = await _fetch_tiingo_meta_batch(http_client, api_key, list(batch))
            enriched = await _upsert_tiingo_meta(db, metas)
            enriched_total += enriched
            batches_run += 1
            logger.info(
                "nport_cusip_tiingo_meta_batch_done",
                batch=batches_run,
                enriched=enriched,
                size=len(batch),
            )
            await asyncio.sleep(_TIINGO_BATCH_SLEEP_S)

    return {
        "candidates": len(tickers),
        "enriched": enriched_total,
        "batches": batches_run,
    }


async def _distinct_tickers_needing_meta(db: AsyncSession) -> list[str]:
    """Tickers with no GICS sector OR stale Tiingo meta."""
    rows = (await db.execute(text("""
        SELECT DISTINCT m.ticker
        FROM sec_cusip_ticker_map m
        JOIN sec_nport_holdings h ON h.cusip = m.cusip
        WHERE m.ticker IS NOT NULL
          AND h.asset_class IN ('EC', 'EP')
          AND h.sector = ANY(:raw_codes)
          AND (
              m.gics_sector IS NULL
              OR m.tiingo_meta_fetched_at IS NULL
              OR m.tiingo_meta_fetched_at < now() - make_interval(days => :staleness)
          )
    """), {
        "raw_codes": list(_RAW_NPORT_CODES),
        "staleness": _TIINGO_STALENESS_DAYS,
    })).all()
    return [r[0] for r in rows if r[0]]


async def _fetch_tiingo_meta_batch(
    http_client: Any, api_key: str, tickers: list[str],
) -> list[dict[str, Any]]:
    """Call Tiingo /tiingo/fundamentals/meta for up to 100 tickers.

    Returns raw payloads aligned by ticker. Unknown tickers are dropped
    by Tiingo's response — we don't raise.
    """
    try:
        resp = await http_client.get(
            TIINGO_META_URL,
            params={
                "tickers": ",".join(tickers),
                "token": api_key,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning(
            "nport_cusip_tiingo_meta_request_failed",
            error=str(exc),
            size=len(tickers),
        )
        return []

    if not isinstance(data, list):
        logger.warning(
            "nport_cusip_tiingo_meta_unexpected_shape",
            got=type(data).__name__,
        )
        return []
    return data


async def _upsert_tiingo_meta(
    db: AsyncSession, metas: list[dict[str, Any]],
) -> int:
    if not metas:
        return 0

    payload = []
    gated = 0
    for meta in metas:
        ticker = meta.get("ticker")
        if not ticker:
            continue
        sector = _scrub_tiingo_value(meta.get("sector"))
        industry = _scrub_tiingo_value(meta.get("industry"))
        sic_raw = _scrub_tiingo_value(meta.get("sicCode"))
        # sicCode is INTEGER on disk — coerce, ignore non-numeric sentinels.
        try:
            sic_code = int(sic_raw) if sic_raw is not None else None
        except (TypeError, ValueError):
            sic_code = None
        if sector is None and industry is None and sic_code is None:
            # Evaluation-tier gate — count but skip the UPDATE (no-op).
            gated += 1
            continue
        payload.append({
            "ticker": (ticker or "").upper(),
            "gics_sector": sector,
            "tiingo_industry": industry,
            "sic_code": sic_code,
        })
    if gated:
        logger.info("nport_cusip_tiingo_meta_gated_skipped", count=gated)

    if not payload:
        return 0

    # Updates every matching ticker row — one Tiingo ticker maps to all
    # CUSIPs sharing it (e.g. share classes). This is correct: all classes
    # of the same issuer belong to the same GICS sector.
    await db.execute(text("""
        UPDATE sec_cusip_ticker_map
           SET gics_sector = COALESCE(:gics_sector, gics_sector),
               tiingo_industry = COALESCE(:tiingo_industry, tiingo_industry),
               sic_code = COALESCE(:sic_code, sic_code),
               tiingo_meta_fetched_at = now()
         WHERE UPPER(ticker) = :ticker
    """), payload)
    await db.commit()
    return sum(1 for p in payload if p["gics_sector"])


# ---------------------------------------------------------------------------
# Propagate to sec_nport_holdings + matview refresh
# ---------------------------------------------------------------------------


async def _propagate_to_nport_holdings(db: AsyncSession) -> int:
    """Push gics_sector from sec_cusip_ticker_map into sec_nport_holdings.

    Only touches equity rows still carrying a raw N-PORT code. Idempotent.
    """
    result = await db.execute(text("""
        UPDATE sec_nport_holdings h
           SET sector = m.gics_sector
          FROM sec_cusip_ticker_map m
         WHERE m.cusip = h.cusip
           AND m.gics_sector IS NOT NULL
           AND h.asset_class IN ('EC', 'EP')
           AND h.sector = ANY(:raw_codes)
    """), {"raw_codes": list(_RAW_NPORT_CODES)})
    await db.commit()
    count = result.rowcount or 0
    logger.info("nport_cusip_tiingo_propagated", rows=count)
    return int(count)


async def _refresh_matview() -> dict[str, Any]:
    start = time.monotonic()
    try:
        async with async_session() as s:
            await s.execute(text(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY "
                "mv_nport_sector_attribution",
            ))
            await s.commit()
        return {
            "status": "refreshed",
            "duration_s": round(time.monotonic() - start, 3),
        }
    except Exception as exc:
        return {
            "status": "failed",
            "error": str(exc),
            "duration_s": round(time.monotonic() - start, 3),
        }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _chunks(seq: list[str], n: int) -> Iterable[list[str]]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


if __name__ == "__main__":
    asyncio.run(run())
