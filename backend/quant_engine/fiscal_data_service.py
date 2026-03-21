"""U.S. Treasury Fiscal Data API client.

Async service — called directly from async route handlers or workers.

Base URL: https://api.fiscaldata.treasury.gov/services/api/fiscal_service
Auth: None required (fully open).

Lifecycle: Instantiate ONCE in FastAPI lifespan() or at worker startup.
Store as app.state.fiscal_data_service and inject via dependency.

Config is injected as parameter — no module-level settings reads.

DB reader functions (get_treasury_*_from_db) read from the treasury_data
hypertable instead of calling the external API.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Suppress httpx DEBUG logs
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = structlog.get_logger()

_MISSING_VALUES = frozenset((".", "#N/A", "", "NaN", "nan", "null", "None"))


# ---------------------------------------------------------------------------
#  Async rate limiter (shared by fiscal_data + OFR services)
# ---------------------------------------------------------------------------


@dataclass
class AsyncTokenBucketRateLimiter:
    """Async token bucket: allows short bursts while respecting sustained rate.

    Default: max_tokens=5 (burst), refill_rate=5.0 tokens/s (sustained).
    Lock is created lazily to avoid module-level asyncio primitives.
    """

    max_tokens: float = 5.0
    refill_rate: float = 5.0
    _tokens: float = field(init=False, repr=False)
    _last_refill: float = field(init=False, repr=False)
    _lock: asyncio.Lock | None = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        self._tokens = self.max_tokens
        self._last_refill = time.monotonic()

    async def acquire(self) -> None:
        """Wait until a token is available. Creates lock lazily."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.max_tokens, self._tokens + elapsed * self.refill_rate)
            self._last_refill = now

            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self.refill_rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
                self._last_refill = time.monotonic()
            else:
                self._tokens -= 1.0


# ---------------------------------------------------------------------------
#  Data types (frozen dataclasses)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TreasuryRate:
    """Average interest rate on a Treasury security."""

    record_date: str
    security_desc: str
    avg_interest_rate_amt: float


@dataclass(frozen=True)
class DebtSnapshot:
    """Daily national debt outstanding."""

    record_date: str
    tot_pub_debt_out_amt: float
    intragov_hold_amt: float
    debt_held_public_amt: float


@dataclass(frozen=True)
class AuctionResult:
    """Treasury securities auction result."""

    auction_date: str
    security_type: str
    security_term: str
    high_yield: float | None
    bid_to_cover_ratio: float | None


@dataclass(frozen=True)
class ExchangeRate:
    """Treasury reporting rate of exchange."""

    record_date: str
    country_currency_desc: str
    exchange_rate: float


@dataclass(frozen=True)
class InterestExpense:
    """Monthly interest expense on the public debt."""

    record_date: str
    expense_catg_desc: str
    month_expense_amt: float
    fytd_expense_amt: float


# ---------------------------------------------------------------------------
#  Value parsing
# ---------------------------------------------------------------------------


def _parse_float(raw: Any, label: str = "", date: str = "") -> float | None:
    """Parse a string/number to float. Returns None on failure."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s in _MISSING_VALUES:
        return None
    try:
        val = float(s.replace(",", ""))
    except (ValueError, TypeError):
        logger.warning("fiscal_data unparseable value", label=label, date=date, raw=raw)
        return None
    if not math.isfinite(val):
        return None
    return val


def _classify_error(status_code: int) -> str:
    """Classify HTTP error into action: 'retry', 'skip', 'fail'."""
    if status_code == 429:
        return "retry"
    if status_code == 503:
        return "retry"
    if status_code == 400:
        return "skip"
    if status_code in (401, 403):
        return "fail"
    if status_code >= 500:
        return "retry"
    return "skip"


# ---------------------------------------------------------------------------
#  FiscalDataService
# ---------------------------------------------------------------------------


class FiscalDataService:
    """U.S. Treasury Fiscal Data API client with rate limiting and error handling.

    Args:
        http_client: Injected httpx.AsyncClient (allows test mocking).
        rate_limiter: Shared async rate limiter. If None, creates default (5 req/s).
        base_url: Treasury Fiscal Data API base URL.
    """

    BASE_URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        rate_limiter: AsyncTokenBucketRateLimiter | None = None,
        base_url: str | None = None,
    ):
        self._client = http_client
        self._rate_limiter = rate_limiter or AsyncTokenBucketRateLimiter()
        self._base_url = base_url or self.BASE_URL

    async def _fetch_paginated(
        self,
        endpoint: str,
        *,
        fields: str,
        filters: str | None = None,
        sort: str = "-record_date",
        page_size: int = 10000,
        max_retries: int = 3,
    ) -> list[dict[str, Any]]:
        """Fetch all pages from a Fiscal Data endpoint. Never raises."""
        all_data: list[dict[str, Any]] = []
        page = 1

        while True:
            await self._rate_limiter.acquire()

            params: dict[str, Any] = {
                "fields": fields,
                "sort": sort,
                "page[size]": page_size,
                "page[number]": page,
                "format": "json",
            }
            if filters:
                params["filter"] = filters

            url = f"{self._base_url}/{endpoint}"

            for attempt in range(max_retries):
                try:
                    response = await self._client.get(url, params=params)
                    response.raise_for_status()
                    body = response.json()

                    data = body.get("data", [])
                    all_data.extend(data)

                    meta = body.get("meta", {})
                    total_pages = meta.get("total-pages", 1)
                    if page >= total_pages:
                        return all_data

                    page += 1
                    break  # success, move to next page

                except httpx.HTTPStatusError as e:
                    action = _classify_error(e.response.status_code)
                    if action == "fail":
                        logger.error(
                            "fiscal_data auth failure",
                            endpoint=endpoint,
                            status=e.response.status_code,
                        )
                        return all_data
                    if action == "skip":
                        logger.warning(
                            "fiscal_data endpoint error, skipping",
                            endpoint=endpoint,
                            status=e.response.status_code,
                        )
                        return all_data
                    wait = min(2**attempt * 2, 30)
                    logger.warning(
                        "fiscal_data retrying",
                        endpoint=endpoint,
                        attempt=attempt + 1,
                        wait=wait,
                    )
                    await asyncio.sleep(wait)

                except (httpx.TimeoutException, httpx.ConnectError) as e:
                    wait = min(2**attempt * 2, 30)
                    logger.warning(
                        "fiscal_data connection error, retrying",
                        endpoint=endpoint,
                        error=str(e),
                        wait=wait,
                    )
                    await asyncio.sleep(wait)
            else:
                logger.error(
                    "fiscal_data exhausted retries",
                    endpoint=endpoint,
                    max_retries=max_retries,
                )
                return all_data

        return all_data  # pragma: no cover

    # ── Public fetch methods ──────────────────────────────────────

    async def fetch_treasury_rates(self, start_date: str) -> list[TreasuryRate]:
        """Average interest rates on Treasury securities.

        Endpoint: /v2/accounting/od/avg_interest_rates
        """
        raw = await self._fetch_paginated(
            "v2/accounting/od/avg_interest_rates",
            fields="record_date,security_desc,avg_interest_rate_amt",
            filters=f"record_date:gte:{start_date}",
        )
        results: list[TreasuryRate] = []
        for row in raw:
            rate = _parse_float(row.get("avg_interest_rate_amt"), "avg_interest_rate_amt")
            if rate is not None:
                results.append(
                    TreasuryRate(
                        record_date=row.get("record_date", ""),
                        security_desc=row.get("security_desc", ""),
                        avg_interest_rate_amt=rate,
                    )
                )
        return results

    async def fetch_debt_to_penny(self, start_date: str) -> list[DebtSnapshot]:
        """Daily national debt outstanding.

        Endpoint: /v2/accounting/od/debt_to_penny
        """
        raw = await self._fetch_paginated(
            "v2/accounting/od/debt_to_penny",
            fields="record_date,tot_pub_debt_out_amt,intragov_hold_amt,debt_held_public_amt",
            filters=f"record_date:gte:{start_date}",
        )
        results: list[DebtSnapshot] = []
        for row in raw:
            total = _parse_float(row.get("tot_pub_debt_out_amt"), "tot_pub_debt_out_amt")
            intragov = _parse_float(row.get("intragov_hold_amt"), "intragov_hold_amt")
            public = _parse_float(row.get("debt_held_public_amt"), "debt_held_public_amt")
            if total is not None and intragov is not None and public is not None:
                results.append(
                    DebtSnapshot(
                        record_date=row.get("record_date", ""),
                        tot_pub_debt_out_amt=total,
                        intragov_hold_amt=intragov,
                        debt_held_public_amt=public,
                    )
                )
        return results

    async def fetch_treasury_auctions(self, start_date: str) -> list[AuctionResult]:
        """Recent Treasury securities auction results.

        Endpoint: /v1/accounting/od/auctions_query
        """
        raw = await self._fetch_paginated(
            "v1/accounting/od/auctions_query",
            fields="auction_date,security_type,security_term,high_yield,bid_to_cover_ratio",
            filters=f"auction_date:gte:{start_date}",
            sort="-auction_date",
        )
        results: list[AuctionResult] = []
        for row in raw:
            results.append(
                AuctionResult(
                    auction_date=row.get("auction_date", ""),
                    security_type=row.get("security_type", ""),
                    security_term=row.get("security_term", ""),
                    high_yield=_parse_float(row.get("high_yield"), "high_yield"),
                    bid_to_cover_ratio=_parse_float(
                        row.get("bid_to_cover_ratio"), "bid_to_cover_ratio"
                    ),
                )
            )
        return results

    async def fetch_exchange_rates(self, start_date: str) -> list[ExchangeRate]:
        """Treasury reporting rates of exchange.

        Endpoint: /v1/accounting/od/rates_of_exchange
        """
        raw = await self._fetch_paginated(
            "v1/accounting/od/rates_of_exchange",
            fields="country_currency_desc,exchange_rate,record_date",
            filters=f"record_date:gte:{start_date}",
        )
        results: list[ExchangeRate] = []
        for row in raw:
            rate = _parse_float(row.get("exchange_rate"), "exchange_rate")
            if rate is not None:
                results.append(
                    ExchangeRate(
                        record_date=row.get("record_date", ""),
                        country_currency_desc=row.get("country_currency_desc", ""),
                        exchange_rate=rate,
                    )
                )
        return results

    async def fetch_interest_expense(self, start_date: str) -> list[InterestExpense]:
        """Monthly interest expense on the public debt.

        Endpoint: /v2/accounting/od/interest_expense
        """
        raw = await self._fetch_paginated(
            "v2/accounting/od/interest_expense",
            fields="record_date,expense_catg_desc,month_expense_amt,fytd_expense_amt",
            filters=f"record_date:gte:{start_date}",
        )
        results: list[InterestExpense] = []
        for row in raw:
            month_amt = _parse_float(row.get("month_expense_amt"), "month_expense_amt")
            fytd_amt = _parse_float(row.get("fytd_expense_amt"), "fytd_expense_amt")
            if month_amt is not None and fytd_amt is not None:
                results.append(
                    InterestExpense(
                        record_date=row.get("record_date", ""),
                        expense_catg_desc=row.get("expense_catg_desc", ""),
                        month_expense_amt=month_amt,
                        fytd_expense_amt=fytd_amt,
                    )
                )
        return results


# ---------------------------------------------------------------------------
#  DB reader functions — read from treasury_data hypertable
# ---------------------------------------------------------------------------


async def get_treasury_rates_from_db(
    db: AsyncSession,
    series_id_prefix: str = "RATE_",
    lookback_days: int = 252,
) -> list[dict[str, Any]]:
    """Read treasury rates from the treasury_data hypertable.

    Returns list of dicts with keys: date, series_id, value.
    """
    from app.shared.models import TreasuryData

    cutoff = date.today() - timedelta(days=lookback_days)
    stmt = (
        select(TreasuryData.obs_date, TreasuryData.series_id, TreasuryData.value)
        .where(
            TreasuryData.series_id.startswith(series_id_prefix),
            TreasuryData.obs_date >= cutoff,
        )
        .order_by(TreasuryData.obs_date.desc())
    )
    result = await db.execute(stmt)
    return [
        {"date": str(r.obs_date), "series_id": r.series_id, "value": float(r.value)}
        for r in result.all()
        if r.value is not None
    ]


async def get_treasury_debt_from_db(
    db: AsyncSession,
    lookback_days: int = 252,
) -> list[dict[str, Any]]:
    """Read debt snapshots from the treasury_data hypertable."""
    from app.shared.models import TreasuryData

    cutoff = date.today() - timedelta(days=lookback_days)
    stmt = (
        select(TreasuryData.obs_date, TreasuryData.series_id, TreasuryData.value)
        .where(
            TreasuryData.series_id.startswith("DEBT_"),
            TreasuryData.obs_date >= cutoff,
        )
        .order_by(TreasuryData.obs_date.desc())
    )
    result = await db.execute(stmt)
    return [
        {"date": str(r.obs_date), "series_id": r.series_id, "value": float(r.value)}
        for r in result.all()
        if r.value is not None
    ]


async def get_treasury_auctions_from_db(
    db: AsyncSession,
    lookback_days: int = 365,
) -> list[dict[str, Any]]:
    """Read auction results from the treasury_data hypertable."""
    from app.shared.models import TreasuryData

    cutoff = date.today() - timedelta(days=lookback_days)
    stmt = (
        select(
            TreasuryData.obs_date, TreasuryData.series_id,
            TreasuryData.value, TreasuryData.metadata_json,
        )
        .where(
            TreasuryData.series_id.startswith("AUCTION_"),
            TreasuryData.obs_date >= cutoff,
        )
        .order_by(TreasuryData.obs_date.desc())
    )
    result = await db.execute(stmt)
    return [
        {
            "date": str(r.obs_date),
            "series_id": r.series_id,
            "value": float(r.value),
            "metadata": r.metadata_json,
        }
        for r in result.all()
        if r.value is not None
    ]
