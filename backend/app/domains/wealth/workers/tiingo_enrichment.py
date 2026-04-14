"""Worker: tiingo_enrichment — populate tiingo_description on instruments_universe.attributes.

Advisory lock: 900_061 (deterministic literal)
Frequency: weekly, 30 minutes after universe_sync
Idempotent: updates rows with NULL `tiingo_description` or stale (> 30 days).

Writes two keys into the JSONB `attributes` column:
    - `tiingo_description` (str, normalized UTF-8; "" if Tiingo returns empty)
    - `tiingo_description_updated_at` (ISO8601 UTC timestamp)

Rationale
---------
Tiingo's ``/tiingo/daily/{ticker}`` meta endpoint returns a rich textual
``description`` for ~98% of the fund universe (5,000+ tickers). That field
is the only reliable seed signal for the upcoming strategy-label classifier
rewrite (Fase 2). This worker isolates the fetch + normalization pass so it
can run on its own cadence, independent of universe_sync's catalog refresh.

Design notes
------------
- Tiingo is called via a blocking ``httpx.Client`` inside a
  ``ThreadPoolExecutor`` (``concurrent.futures``) so we honor the provider's
  sync contract without the async reentrancy traps documented in
  ``tiingo_instrument_provider.py``.
- We bypass ``TiingoInstrumentProvider.fetch_instrument`` because it maps all
  failures to ``None``; this worker needs to distinguish legitimate empty
  descriptions (OK, still record the timestamp) from transient 429/503/timeouts
  (must retry).
- Writes use ``attributes || jsonb_build_object(...)`` to preserve every
  other attribute key (strategy_label, sec_cik, domicile, etc.).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
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
_BATCH_CONCURRENCY = 50
_HTTP_TIMEOUT_SECONDS = 30.0
_RETRY_ATTEMPTS = 3
_RETRY_BASE_SECONDS = 2.0
_TTL_DAYS = 30
_UPDATE_BATCH_SIZE = 500

# Windows-1252 smart punctuation and common control/whitespace chars that
# leak into Tiingo descriptions. Map to ASCII equivalents to keep downstream
# classifiers (regex keyword matchers, embedding tokenizers) stable.
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
    """Normalize a Tiingo description to UTF-8 safe, classifier-friendly text.

    - Replaces Windows-1252 smart quotes/bullets with ASCII equivalents.
    - Applies NFC Unicode normalization (accented chars stay intact but in
      canonical composed form).
    - Strips C0 control chars except newline and tab.
    - Collapses leading/trailing whitespace.
    """
    if not raw:
        return ""
    for bad, good in _SMART_PUNCTUATION_MAP.items():
        raw = raw.replace(bad, good)
    raw = unicodedata.normalize("NFC", raw)
    raw = "".join(c for c in raw if c >= " " or c in "\n\t")
    return raw.strip()


class _TiingoFetchOutcome:
    """Tagged result of a single Tiingo meta fetch.

    Using constants instead of an enum keeps the worker self-contained and
    trivially picklable if we ever need to cross process boundaries.
    """

    OK = "ok"                    # Got a JSON payload (description may still be empty).
    NOT_FOUND = "not_found"      # 401/404 — record empty description and move on.
    RETRY_EXHAUSTED = "retry"    # 429/503/timeout after all retries — skip this cycle.


def _fetch_description(
    client: httpx.Client,
    api_key: str,
    ticker: str,
) -> tuple[str, str]:
    """Fetch raw description for a single ticker. Returns (outcome, description).

    The worker treats NOT_FOUND and OK-with-empty identically (both persist an
    empty description so the row isn't retried every week) but keeps the tags
    separate for metrics.
    """
    ticker_clean = ticker.strip().lower()
    if not ticker_clean:
        return _TiingoFetchOutcome.NOT_FOUND, ""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Token {api_key}",
    }
    url = f"{TIINGO_BASE_URL}/tiingo/daily/{ticker_clean}"

    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            resp = client.get(url, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt == _RETRY_ATTEMPTS:
                logger.warning(
                    "tiingo_enrichment.retry_exhausted",
                    ticker=ticker_clean,
                    error=str(exc),
                )
                return _TiingoFetchOutcome.RETRY_EXHAUSTED, ""
            time.sleep(_RETRY_BASE_SECONDS * (2 ** (attempt - 1)))
            continue

        if resp.status_code in (401, 404):
            return _TiingoFetchOutcome.NOT_FOUND, ""

        if resp.status_code in (429, 503):
            if attempt == _RETRY_ATTEMPTS:
                logger.warning(
                    "tiingo_enrichment.retry_exhausted",
                    ticker=ticker_clean,
                    status=resp.status_code,
                )
                return _TiingoFetchOutcome.RETRY_EXHAUSTED, ""
            time.sleep(_RETRY_BASE_SECONDS * (2 ** (attempt - 1)))
            continue

        if resp.status_code != 200:
            logger.warning(
                "tiingo_enrichment.non_200",
                ticker=ticker_clean,
                status=resp.status_code,
            )
            return _TiingoFetchOutcome.NOT_FOUND, ""

        try:
            payload = resp.json()
        except ValueError:
            return _TiingoFetchOutcome.NOT_FOUND, ""

        if not isinstance(payload, dict):
            return _TiingoFetchOutcome.NOT_FOUND, ""

        return _TiingoFetchOutcome.OK, str(payload.get("description") or "")

    # Unreachable — loop either returns or exhausts. Kept for type checkers.
    return _TiingoFetchOutcome.RETRY_EXHAUSTED, ""


def _build_http_client() -> httpx.Client:
    return httpx.Client(
        timeout=_HTTP_TIMEOUT_SECONDS,
        limits=httpx.Limits(
            max_keepalive_connections=_BATCH_CONCURRENCY,
            max_connections=_BATCH_CONCURRENCY * 2,
        ),
    )


async def run_tiingo_enrichment() -> dict[str, Any]:
    """Populate instruments_universe.attributes.tiingo_description.

    Returns a stats dict suitable for structured logging and admin responses.
    """
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
    """Core fetch-and-write loop. Separated for easier testing."""
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
            """,
        ),
    )
    candidates = [(str(r["instrument_id"]), r["ticker"]) for r in rows.mappings().all()]

    if not candidates:
        return {
            "candidates": 0,
            "processed": 0,
            "with_description": 0,
            "empty_description": 0,
            "http_errors": 0,
            "retry_exhausted": 0,
        }

    api_key = settings.tiingo_api_key
    fetched: list[tuple[str, str, str]] = []  # (iid, outcome, normalized_desc)

    loop = asyncio.get_running_loop()
    with _build_http_client() as client:

        def _task(item: tuple[str, str]) -> tuple[str, str, str]:
            iid, ticker = item
            outcome, raw_desc = _fetch_description(client, api_key, ticker)
            return iid, outcome, normalize_description(raw_desc)

        def _run_pool() -> list[tuple[str, str, str]]:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=_BATCH_CONCURRENCY,
                thread_name_prefix="tiingo-enrich",
            ) as pool:
                return list(pool.map(_task, candidates))

        fetched = await loop.run_in_executor(None, _run_pool)

    with_desc = 0
    empty_desc = 0
    retry_exhausted = 0
    writable: list[tuple[str, str]] = []  # (iid, normalized_desc)

    for iid, outcome, desc in fetched:
        if outcome == _TiingoFetchOutcome.RETRY_EXHAUSTED:
            retry_exhausted += 1
            continue
        if desc:
            with_desc += 1
        else:
            empty_desc += 1
        writable.append((iid, desc))

    processed = await _persist(db, writable)

    return {
        "candidates": len(candidates),
        "processed": processed,
        "with_description": with_desc,
        "empty_description": empty_desc,
        "http_errors": 0,  # Non-retryable non-2xx collapse into NOT_FOUND (empty_description).
        "retry_exhausted": retry_exhausted,
    }


async def _persist(db: AsyncSession, writable: list[tuple[str, str]]) -> int:
    """Batch-update attributes JSONB. Preserves other keys via ``||`` merge."""
    if not writable:
        return 0

    ts_iso = datetime.now(timezone.utc).isoformat()
    processed = 0

    for i in range(0, len(writable), _UPDATE_BATCH_SIZE):
        batch = writable[i : i + _UPDATE_BATCH_SIZE]
        params: dict[str, Any] = {"ts": ts_iso}
        values_parts: list[str] = []
        for j, (iid, desc) in enumerate(batch):
            params[f"id_{j}"] = iid
            params[f"desc_{j}"] = desc
            values_parts.append(f"(:id_{j}::uuid, :desc_{j})")

        values_sql = ", ".join(values_parts)
        # ``description`` is used as the VALUES column alias rather than
        # ``desc`` — the latter collides with the PostgreSQL sort keyword.
        await db.execute(
            text(
                f"""
                UPDATE instruments_universe iu
                SET attributes = COALESCE(iu.attributes, '{{}}'::jsonb)
                                 || jsonb_build_object(
                                        'tiingo_description', v.description,
                                        'tiingo_description_updated_at', :ts
                                    ),
                    updated_at = now()
                FROM (VALUES {values_sql}) AS v(id, description)
                WHERE iu.instrument_id = v.id
                """,
            ),
            params,
        )
        await db.commit()
        processed += len(batch)

    return processed


if __name__ == "__main__":  # pragma: no cover - manual verification entry point
    asyncio.run(run_tiingo_enrichment())
