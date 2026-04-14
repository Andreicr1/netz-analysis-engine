"""Worker: tiingo_enrichment — populate tiingo_description on instruments_universe.attributes.

Advisory lock: 900_061 (deterministic literal)
Frequency: weekly, 30 minutes after universe_sync
Idempotent: updates rows with NULL ``tiingo_description`` or stale (> 30 days).

Writes these keys into the JSONB ``attributes`` column:
    - ``tiingo_description`` (str, normalized UTF-8; "" if Tiingo returns empty)
    - ``tiingo_description_updated_at`` (ISO8601 UTC timestamp)
    - ``tiingo_start_date`` / ``tiingo_end_date`` (str) — bonus metadata, free from ``/daily/``

Rationale
---------
Tiingo's ``/tiingo/daily/{ticker}`` meta endpoint returns a rich textual
``description`` for every fund vehicle type (ETF, mutual fund, closed-end, BDC,
MMF). That field is the only reliable seed signal for the upcoming strategy-
label classifier rewrite (Fase 2).

One row per series
------------------
``instruments_universe`` already stores one row per SEC series. Empirical pilot
(5 random CIKs × 3 tickers each) confirmed that series within the same CIK have
*different* Tiingo descriptions — i.e. share classes are not aliased here and
CIK-level fanout is unsafe. The mutual-fund API endpoint ``/tiingo/funds/`` is
gated behind a separate entitlement not enabled on the current Power plan.

Per-ticker throttled fetch
--------------------------
With 5,446 candidates and a 10,000 req/hour budget, we target ~2.0 req/s
sustained (25% margin below the 2.78 req/s ceiling):

    concurrency = 2   +   per-request delay = 1.0s/thread  →  ~2.0 req/s

A full bootstrap run takes ~45 min. Subsequent weekly runs only touch rows
with expired TTL, so steady-state wall time is seconds.

Circuit-breaker
---------------
Tiingo does NOT expose ``X-RateLimit-*`` headers (verified empirically). The
only external signal is 429. Thirty consecutive 429s short-circuits the run
to avoid exhausting the shared API quota for other workers
(``macro_ingestion``, ``benchmark_ingest``). Already-committed rows persist;
the next run picks up via TTL.

Design notes
------------
- Tiingo is called via a blocking ``httpx.Client`` inside a
  ``ThreadPoolExecutor`` to honor its sync contract without async reentrancy.
- Writes use ``attributes || jsonb_build_object(...)`` to preserve every
  other attribute key (``strategy_label``, ``sec_cik``, ``series_id``, …).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import settings
from app.core.db.engine import async_session_factory as async_session

logger = structlog.get_logger()

TIINGO_ENRICHMENT_LOCK_ID = 900_061
TIINGO_BASE_URL = "https://api.tiingo.com"

# Throttle math: Tiingo Power tier allows 10,000 req/hour (= 2.78 req/s). We
# target 2.0 req/s to leave 25% headroom for other workers sharing the key.
# concurrency=2 + 1.0s per-thread delay ≈ 2 req/s sustained.
_BATCH_CONCURRENCY = 2
_PER_REQUEST_DELAY_SECONDS = 1.0
_HTTP_TIMEOUT_SECONDS = 30.0

# A single 429 is noise — Tiingo buckets occasionally. A run of them means we
# hit the hourly cap or key was throttled by an external workload. Abort
# cleanly so the next TTL cycle resumes where we left off.
_CONSECUTIVE_429_CIRCUIT_BREAKER = 30
# Retries on transient network failures (timeouts, connection resets). 429
# does NOT retry — the circuit-breaker is the correct handling.
_TRANSIENT_RETRY_ATTEMPTS = 2
_TRANSIENT_RETRY_BASE_SECONDS = 5.0
_TRANSIENT_RETRY_MAX_SECONDS = 15.0

_TTL_DAYS = 30
# Commit every 50 rows → progress visible at ~25s cadence and a crash mid-run
# loses at most 50 rows. Small enough for responsive ops, large enough to
# amortize commit overhead.
_INCREMENTAL_COMMIT_EVERY = 50

# Windows-1252 smart punctuation and common control/whitespace chars that
# leak into Tiingo descriptions. Map to ASCII equivalents so downstream
# classifiers (regex, embedding tokenizers) see stable input.
_SMART_PUNCTUATION_MAP: dict[str, str] = {
    "\x91": "'",
    "\x92": "'",
    "\x93": '"',
    "\x94": '"',
    "\x95": "*",
    "\x96": "-",
    "\x97": "--",
    "\x85": "...",
    "\xa0": " ",
}


def normalize_description(raw: str | None) -> str:
    """Normalize a Tiingo description to UTF-8 safe, classifier-friendly text."""
    if not raw:
        return ""
    for bad, good in _SMART_PUNCTUATION_MAP.items():
        raw = raw.replace(bad, good)
    raw = unicodedata.normalize("NFC", raw)
    raw = "".join(c for c in raw if c >= " " or c in "\n\t")
    return raw.strip()


class _TiingoFetchOutcome:
    """Tagged result of a single Tiingo meta fetch."""

    OK = "ok"                  # Got a JSON payload (description may still be empty).
    NOT_FOUND = "not_found"    # 401/404 — record empty description and move on.
    RATE_LIMITED = "rate"      # 429 — feeds circuit-breaker, no write.
    TRANSIENT_ERROR = "error"  # Network timeout / 5xx after retries — no write.


class _FetchedMeta:
    """Slim record of the fields we care about from ``/tiingo/daily/{ticker}``."""

    __slots__ = ("description", "start_date", "end_date")

    def __init__(self, description: str = "", start_date: str = "", end_date: str = "") -> None:
        self.description = description
        self.start_date = start_date
        self.end_date = end_date


class _CircuitBreaker:
    """Tracks consecutive 429s across all worker threads.

    Tiingo doesn't expose ``X-RateLimit-*`` headers, so a streak of 429s is
    the only signal that we've exhausted quota. Once the threshold is
    crossed, ``should_abort()`` returns True and the main loop stops
    enqueuing new fetches. Thread-safe via a single lock.
    """

    def __init__(self, threshold: int) -> None:
        self._threshold = threshold
        self._lock = threading.Lock()
        self._consecutive = 0
        self._total = 0

    def record_429(self) -> None:
        with self._lock:
            self._consecutive += 1
            self._total += 1

    def record_success(self) -> None:
        with self._lock:
            self._consecutive = 0

    def should_abort(self) -> bool:
        with self._lock:
            return self._consecutive >= self._threshold

    @property
    def total_429s(self) -> int:
        with self._lock:
            return self._total


def _fetch_meta(
    client: httpx.Client,
    api_key: str,
    ticker: str,
    breaker: _CircuitBreaker,
) -> tuple[str, _FetchedMeta]:
    """Fetch meta for a single ticker. Returns ``(outcome, meta)``.

    ``meta`` is always populated (empty strings when no data) so callers can
    persist a timestamp on NOT_FOUND without juggling None.
    """
    empty = _FetchedMeta()
    ticker_clean = ticker.strip().lower()
    if not ticker_clean:
        return _TiingoFetchOutcome.NOT_FOUND, empty

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Token {api_key}",
    }
    url = f"{TIINGO_BASE_URL}/tiingo/daily/{ticker_clean}"

    for attempt in range(1, _TRANSIENT_RETRY_ATTEMPTS + 1):
        try:
            resp = client.get(url, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt == _TRANSIENT_RETRY_ATTEMPTS:
                logger.warning(
                    "tiingo_enrichment.transient_error",
                    ticker=ticker_clean,
                    error=str(exc),
                )
                return _TiingoFetchOutcome.TRANSIENT_ERROR, empty
            time.sleep(
                min(
                    _TRANSIENT_RETRY_BASE_SECONDS * (2 ** (attempt - 1)),
                    _TRANSIENT_RETRY_MAX_SECONDS,
                )
            )
            continue

        if resp.status_code == 429:
            # Feed the circuit breaker and bail out. We explicitly do NOT
            # retry 429 — a local retry would only widen the breach window
            # and delay the clean abort.
            breaker.record_429()
            return _TiingoFetchOutcome.RATE_LIMITED, empty

        if resp.status_code in (401, 404):
            breaker.record_success()
            return _TiingoFetchOutcome.NOT_FOUND, empty

        if resp.status_code >= 500:
            if attempt == _TRANSIENT_RETRY_ATTEMPTS:
                logger.warning(
                    "tiingo_enrichment.transient_error",
                    ticker=ticker_clean,
                    status=resp.status_code,
                )
                return _TiingoFetchOutcome.TRANSIENT_ERROR, empty
            time.sleep(
                min(
                    _TRANSIENT_RETRY_BASE_SECONDS * (2 ** (attempt - 1)),
                    _TRANSIENT_RETRY_MAX_SECONDS,
                )
            )
            continue

        if resp.status_code != 200:
            logger.warning(
                "tiingo_enrichment.non_200",
                ticker=ticker_clean,
                status=resp.status_code,
            )
            breaker.record_success()
            return _TiingoFetchOutcome.NOT_FOUND, empty

        try:
            payload = resp.json()
        except ValueError:
            breaker.record_success()
            return _TiingoFetchOutcome.NOT_FOUND, empty

        if not isinstance(payload, dict):
            breaker.record_success()
            return _TiingoFetchOutcome.NOT_FOUND, empty

        breaker.record_success()
        return _TiingoFetchOutcome.OK, _FetchedMeta(
            description=str(payload.get("description") or ""),
            start_date=str(payload.get("startDate") or ""),
            end_date=str(payload.get("endDate") or ""),
        )

    return _TiingoFetchOutcome.TRANSIENT_ERROR, empty


def _build_http_client() -> httpx.Client:
    return httpx.Client(
        timeout=_HTTP_TIMEOUT_SECONDS,
        limits=httpx.Limits(
            max_keepalive_connections=_BATCH_CONCURRENCY,
            max_connections=_BATCH_CONCURRENCY * 2,
        ),
    )


async def run_tiingo_enrichment() -> dict[str, Any]:
    """Populate ``instruments_universe.attributes.tiingo_description``."""
    started = time.monotonic()
    logger.info("tiingo_enrichment.start")

    if not settings.tiingo_api_key:
        logger.warning("tiingo_enrichment.no_api_key")
        return {"status": "skipped", "reason": "no_api_key"}

    async with async_session() as db:
        lock = await db.execute(
            text(f"SELECT pg_try_advisory_lock({TIINGO_ENRICHMENT_LOCK_ID})"),
        )
        if not lock.scalar():
            logger.warning("tiingo_enrichment.lock_held")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            stats = await _enrich(db)
            stats["duration_seconds"] = round(time.monotonic() - started, 2)
            logger.info("tiingo_enrichment_complete", **stats)
            return stats
        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({TIINGO_ENRICHMENT_LOCK_ID})"),
            )


async def _enrich(db: AsyncSession) -> dict[str, Any]:
    """Core fetch-and-write loop. Separated for easier testing.

    Processes candidates in deterministic (``instrument_id``) order so an
    aborted run resumes predictably — the TTL filter naturally skips already-
    processed rows on the next execution.
    """
    candidates = await _load_candidates(db)

    stats: dict[str, Any] = {
        "candidates": len(candidates),
        "processed": 0,
        "with_description": 0,
        "empty_description": 0,
        "not_found": 0,
        "rate_limited": 0,
        "transient_errors": 0,
        "aborted_early": False,
    }

    if not candidates:
        return stats

    api_key = settings.tiingo_api_key
    breaker = _CircuitBreaker(_CONSECUTIVE_429_CIRCUIT_BREAKER)
    loop = asyncio.get_running_loop()

    def _task(item: tuple[str, str]) -> tuple[str, str, _FetchedMeta]:
        iid, ticker = item
        with _build_http_client() as client:
            outcome, meta = _fetch_meta(client, api_key, ticker, breaker)
        # Per-thread pacing: combined with concurrency=2, this yields the
        # ~2 req/s sustained throughput we need to fit inside the 10k/hour cap.
        time.sleep(_PER_REQUEST_DELAY_SECONDS)
        meta.description = normalize_description(meta.description)
        return iid, outcome, meta

    def _fetch_chunk(chunk: list[tuple[str, str]]) -> list[tuple[str, str, _FetchedMeta]]:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=_BATCH_CONCURRENCY,
            thread_name_prefix="tiingo-enrich",
        ) as pool:
            return list(pool.map(_task, chunk))

    for chunk_start in range(0, len(candidates), _INCREMENTAL_COMMIT_EVERY):
        if breaker.should_abort():
            logger.warning(
                "tiingo_enrichment.circuit_breaker_abort",
                total_429s=breaker.total_429s,
                processed=stats["processed"],
                remaining=len(candidates) - chunk_start,
            )
            stats["aborted_early"] = True
            break

        chunk = candidates[chunk_start : chunk_start + _INCREMENTAL_COMMIT_EVERY]
        results = await loop.run_in_executor(None, _fetch_chunk, chunk)

        writable: list[tuple[str, _FetchedMeta]] = []
        for iid, outcome, meta in results:
            if outcome == _TiingoFetchOutcome.RATE_LIMITED:
                stats["rate_limited"] += 1
                continue
            if outcome == _TiingoFetchOutcome.TRANSIENT_ERROR:
                stats["transient_errors"] += 1
                continue
            if outcome == _TiingoFetchOutcome.NOT_FOUND:
                stats["not_found"] += 1
            if meta.description:
                stats["with_description"] += 1
            else:
                stats["empty_description"] += 1
            writable.append((iid, meta))

        if writable:
            rows = await _persist(db, writable)
            stats["processed"] += rows

        logger.info("tiingo_enrichment.progress", total_429s=breaker.total_429s, **stats)

    return stats


async def _load_candidates(db: AsyncSession) -> list[tuple[str, str]]:
    """Return ``[(instrument_id, ticker), ...]`` sorted by ``instrument_id``.

    Excludes rows with a fresh ``tiingo_description_updated_at`` (within TTL),
    which doubles as the checkpoint mechanism: a partial run that aborted
    early leaves unprocessed rows with NULL/stale timestamps, picked up on
    the next execution.
    """
    rows = await db.execute(
        text(
            f"""
            SELECT instrument_id, ticker
            FROM instruments_universe
            WHERE is_active = true
              AND ticker IS NOT NULL
              AND ticker !~ '^\\s*$'
              AND (
                (attributes->>'tiingo_description') IS NULL
                OR (attributes->>'tiingo_description_updated_at')::timestamptz
                   < now() - interval '{_TTL_DAYS} days'
              )
            ORDER BY instrument_id
            """,
        ),
    )
    return [(str(r["instrument_id"]), str(r["ticker"])) for r in rows.mappings().all()]


async def _persist(
    db: AsyncSession,
    writable: list[tuple[str, _FetchedMeta]],
) -> int:
    """One UPDATE per instrument. Preserves other JSONB keys via ``||`` merge.

    Serial UPDATEs trade raw throughput for simplicity — with commits every
    50 rows, the DB cost is negligible relative to the ~1s-per-fetch wall time.
    """
    if not writable:
        return 0

    ts_iso = datetime.now(timezone.utc).isoformat()
    rows_affected = 0

    for iid, meta in writable:
        # Every ``:name`` placeholder is wrapped in ``CAST(... AS text)``
        # because ``jsonb_build_object`` is variadic — asyncpg otherwise
        # raises ``IndeterminateDatatypeError`` when it tries to prepare the
        # statement and can't infer the parameter types.
        result = await db.execute(
            text(
                """
                UPDATE instruments_universe iu
                SET attributes = COALESCE(iu.attributes, '{}'::jsonb)
                                 || jsonb_build_object(
                                        'tiingo_description', CAST(:desc AS text),
                                        'tiingo_description_updated_at', CAST(:ts AS text),
                                        'tiingo_start_date', CAST(:start_date AS text),
                                        'tiingo_end_date', CAST(:end_date AS text)
                                    ),
                    updated_at = now()
                WHERE iu.instrument_id = CAST(:iid AS uuid)
                """,
            ),
            {
                "iid": iid,
                "desc": meta.description,
                "ts": ts_iso,
                "start_date": meta.start_date,
                "end_date": meta.end_date,
            },
        )
        await db.commit()
        rows_affected += result.rowcount or 0

    return rows_affected


if __name__ == "__main__":  # pragma: no cover - manual verification entry point
    asyncio.run(run_tiingo_enrichment())
