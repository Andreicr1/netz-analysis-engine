"""Shared ESMA infrastructure — rate limiting, exchange mapping, constants.

Fully standalone: zero imports from ``app.*``.
All external library imports (redis, httpx) are lazy.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

import httpx
import structlog

from data_providers.esma.models import IsinResolution

logger = structlog.get_logger()

T = TypeVar("T")

# ── Constants ────────────────────────────────────────────────────

ESMA_SOLR_BASE = (
    "https://registers.esma.europa.eu/solr/esma_registers_funds_cbdif/select"
)
ESMA_RATE_LIMIT = 4  # req/s (conservative — no documented rate limit)

OPENFIGI_BATCH_URL = "https://api.openfigi.com/v3/mapping"
OPENFIGI_BATCH_SIZE = 50  # conservative — 100 can trigger 413 with extra fields

# OpenFIGI exchange code → Yahoo Finance suffix mapping for European exchanges.
EXCHANGE_SUFFIX_MAP: dict[str, str] = {
    # UK
    "LN": ".L",
    "LS": ".L",
    # Germany
    "GY": ".DE",
    "GF": ".F",
    "GM": ".MU",
    "GS": ".SG",
    "GD": ".DU",
    "GH": ".HA",
    "GB": ".BE",
    # France
    "FP": ".PA",
    # Netherlands
    "NA": ".AS",
    # Italy
    "IM": ".MI",
    # Spain
    "SM": ".MC",
    # Switzerland
    "SE": ".SW",
    "SW": ".SW",
    # Belgium
    "BB": ".BR",
    # Portugal
    "PL": ".LS",
    # Ireland
    "ID": ".IR",
    # Austria
    "AV": ".VI",
    # Sweden
    "SS": ".ST",
    # Norway
    "NO": ".OL",
    # Denmark
    "DC": ".CO",
    # Finland
    "FH": ".HE",
    # Luxembourg
    "LX": ".LU",
    # US (for dual-listed)
    "US": "",
    "UN": "",
    "UW": "",
    "UA": "",
}

# Exchanges where a resolved ticker is tradeable on Yahoo Finance.
TRADEABLE_EXCHANGES = frozenset(EXCHANGE_SUFFIX_MAP.keys())

_MAX_ENTITY_NAME_LENGTH = 200
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9\s.,'\-&()]+$")


# ── Rate Limiting ────────────────────────────────────────────────

_local_buckets: dict[str, tuple[float, float]] = {}
_fallback_warned: set[str] = set()


def _check_rate(key_prefix: str, max_per_second: int) -> None:
    """Redis sliding window rate limiter with local token bucket fallback."""
    try:
        import redis as redis_lib

        redis_url = os.environ.get("REDIS_URL")
        if not redis_url:
            _check_rate_local(key_prefix, max_per_second)
            return

        r = redis_lib.from_url(redis_url, decode_responses=True)
        key = f"{key_prefix}:rate:{int(time.time())}"
        count: int = r.incr(key)  # type: ignore[assignment]
        if count == 1:
            r.expire(key, 2)
        if count > max_per_second:
            time.sleep(1.0)
    except Exception:
        _check_rate_local(key_prefix, max_per_second)


def _check_rate_local(key_prefix: str, max_per_second: int) -> None:
    """In-process token bucket fallback at rate/4 req/s."""
    if key_prefix not in _fallback_warned:
        _fallback_warned.add(key_prefix)
        logger.warning(
            "rate_limiter_redis_unavailable",
            key_prefix=key_prefix,
            fallback="local_token_bucket",
        )

    now = time.monotonic()
    local_rate = max(max_per_second / 4, 1.0)

    tokens, last_refill = _local_buckets.get(key_prefix, (local_rate, now))
    elapsed = now - last_refill
    tokens = min(local_rate, tokens + elapsed * local_rate)
    last_refill = now

    if tokens < 1.0:
        sleep_time = (1.0 - tokens) / local_rate
        time.sleep(sleep_time)
        tokens = 0.0
    else:
        tokens -= 1.0

    _local_buckets[key_prefix] = (tokens, last_refill)


def check_esma_rate() -> None:
    """Rate-limit ESMA Solr API requests."""
    _check_rate("esma", ESMA_RATE_LIMIT)


def check_openfigi_rate(has_api_key: bool = False) -> None:
    """Rate-limit OpenFIGI API requests (25 req/min free, 250 req/min with key).

    Without key: enforce ~20 req/min (0.33 req/s) to stay safely under 25/min.
    With key: ~200 req/min (3 req/s) to stay safely under 250/min.
    """
    if has_api_key:
        _check_rate("openfigi_esma", 3)
    else:
        # 25 req/min = 0.42/s — use blocking sleep to enforce ~3s gap
        _check_rate_local("openfigi_esma_nokey", 1)
        time.sleep(2.5)  # ensures ~3s between requests → ~20 req/min


# ── ISIN → Ticker Resolution (OpenFIGI batch) ───────────────────


def _make_unresolved(isin: str) -> IsinResolution:
    return IsinResolution(
        isin=isin,
        yahoo_ticker=None,
        exchange=None,
        resolved_via="unresolved",
        is_tradeable=False,
    )


def _openfigi_to_yahoo_ticker(ticker: str | None, exchange: str | None) -> str | None:
    """Convert OpenFIGI ticker + exchange to Yahoo Finance symbol."""
    if not ticker:
        return None
    if not exchange:
        return ticker
    suffix = EXCHANGE_SUFFIX_MAP.get(exchange, "")
    return f"{ticker}{suffix}" if suffix else ticker


async def resolve_isin_to_ticker_batch(
    isins: list[str],
    *,
    http_client: Any,
    api_key: str | None = None,
) -> list[IsinResolution]:
    """Resolve up to 100 ISINs to Yahoo Finance tickers via OpenFIGI batch API.

    Returns one IsinResolution per input ISIN (same order).
    Never raises — failed/unresolved ISINs return resolved_via='unresolved'.
    """
    if len(isins) > OPENFIGI_BATCH_SIZE:
        raise ValueError(f"Batch size {len(isins)} exceeds limit {OPENFIGI_BATCH_SIZE}")

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["X-OPENFIGI-APIKEY"] = api_key

    payload = [
        {"idType": "ID_ISIN", "idValue": isin, "includeUnlistedEquities": True}
        for isin in isins
    ]

    max_retries = 5
    results: list[Any] | None = None
    for attempt in range(max_retries):
        try:
            response = await http_client.post(
                OPENFIGI_BATCH_URL,
                json=payload,
                headers=headers,
                timeout=30.0,
            )
            if response.status_code == 429:
                wait = min(2 ** attempt * 3, 60)  # 3s, 6s, 12s, 24s, 48s
                logger.warning(
                    "openfigi.rate_limited",
                    attempt=attempt + 1,
                    wait_seconds=wait,
                    count=len(isins),
                )
                await asyncio.sleep(wait)
                continue
            if response.status_code == 413:
                logger.warning(
                    "openfigi.payload_too_large",
                    count=len(isins),
                )
                return [_make_unresolved(i) for i in isins]
            response.raise_for_status()
            results = response.json()
            break
        except httpx.HTTPStatusError:
            raise
        except Exception as exc:
            logger.warning("openfigi.isin_batch_failed", error=str(exc), count=len(isins))
            return [_make_unresolved(i) for i in isins]

    if results is None:
        logger.warning("openfigi.max_retries_exhausted", count=len(isins))
        return [_make_unresolved(i) for i in isins]

    if not isinstance(results, list) or len(results) != len(isins):
        logger.warning(
            "openfigi.unexpected_response_length",
            expected=len(isins),
            got=len(results) if isinstance(results, list) else type(results).__name__,
        )
        return [_make_unresolved(i) for i in isins]

    output: list[IsinResolution] = []
    for isin, result in zip(isins, results, strict=True):
        if "data" not in result or not result["data"]:
            output.append(_make_unresolved(isin))
            continue

        best = result["data"][0]
        raw_ticker = best.get("ticker")
        exchange = best.get("exchCode")
        yahoo_ticker = _openfigi_to_yahoo_ticker(raw_ticker, exchange)
        output.append(IsinResolution(
            isin=isin,
            yahoo_ticker=yahoo_ticker,
            exchange=exchange,
            resolved_via="openfigi",
            is_tradeable=bool(yahoo_ticker and exchange in TRADEABLE_EXCHANGES),
        ))

    return output


# ── Entity Name Sanitization ────────────────────────────────────


def sanitize_entity_name(name: str) -> str | None:
    """Sanitize a company/fund name for safe use in queries.

    Returns None if the name is too long or contains unsafe characters.
    """
    name = name.strip()
    if not name or len(name) > _MAX_ENTITY_NAME_LENGTH:
        return None
    if not _SAFE_NAME_RE.match(name):
        return None
    return name


# ── Dedicated ESMA Thread Pool ───────────────────────────────────

_esma_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="esma-data")


async def run_in_esma_thread(fn: Callable[..., T], *args: Any) -> T:
    """Run a sync function in the dedicated ESMA thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_esma_executor, fn, *args)
