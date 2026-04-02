"""FE fundinfo low-level API client.

Async client wrapping all 7 FE fundinfo REST APIs with OAuth2 token management,
rate limiting, batching (max 10 ISINs per request), and retry logic.

Base URLs:
- Static:              https://api.fefundinfo.com/funds/Static/1.0.0
- Static Key Facts:    https://api.fefundinfo.com/funds/StaticKeyFacts/1.0.0
- Dynamic:             https://api.fefundinfo.com/funds/Dynamic/1.0.0
- Dynamic Data Series: https://api.fefundinfo.com/funds/DynamicDataSeries/1.0.0
- Dynamic Performance: https://api.fefundinfo.com/funds/DynamicPerformance/1.0.0
- Ratios & Exposures:  https://api.fefundinfo.com/funds/RatiosAndExposures/1.0.0

Auth: OAuth2 client_credentials → Bearer token + Fefi-Apim-Subscription-Key header.

Lifecycle: Instantiate ONCE in FastAPI lifespan() or provider factory.
Config is injected as parameter — no module-level settings reads.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import httpx
import structlog

logging.getLogger("httpx").setLevel(logging.WARNING)

logger = structlog.get_logger()

# Max identifiers per FE fundinfo API request.
_MAX_BATCH_SIZE = 10

# OAuth2 scopes required across all 7 APIs.
_OAUTH_SCOPES = (
    "static-data-read "
    "static-key-facts-read "
    "sdr-read "
    "dynamic-data-read "
    "dynamic-data-series-read "
    "dynamic-data-performance-read "
    "fund-ratios-exposure-read"
)


# ---------------------------------------------------------------------------
#  Async rate limiter
# ---------------------------------------------------------------------------


@dataclass
class _AsyncTokenBucket:
    """Async token bucket rate limiter. Lock created lazily."""

    max_tokens: float = 10.0
    refill_rate: float = 10.0
    _tokens: float = field(init=False, repr=False)
    _last_refill: float = field(init=False, repr=False)
    _lock: asyncio.Lock | None = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        self._tokens = self.max_tokens
        self._last_refill = time.monotonic()

    async def acquire(self) -> None:
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
#  Error classification
# ---------------------------------------------------------------------------


def _classify_error(status_code: int) -> str:
    if status_code == 429:
        return "retry"
    if status_code in (408, 503):
        return "retry"
    if status_code == 400:
        return "skip"
    if status_code in (401, 403):
        return "fail"
    if status_code >= 500:
        return "retry"
    return "skip"


# ---------------------------------------------------------------------------
#  OAuth2 Token Manager
# ---------------------------------------------------------------------------


class FEFundInfoTokenManager:
    """OAuth2 client_credentials token manager with auto-refresh.

    Caches token in memory, refreshes 60 seconds before expiry.

    Args:
        client_id: OAuth2 client ID.
        client_secret: OAuth2 client secret.
        token_url: Token endpoint URL.

    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_url: str = "https://auth.fefundinfo.com/connect/token",
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_url = token_url
        self._access_token: str | None = None
        self._expires_at: float = 0.0
        self._lock: asyncio.Lock | None = None

    async def get_token(self) -> str:
        """Return valid access token, refreshing if expired (with 60s margin)."""
        if self._lock is None:
            self._lock = asyncio.Lock()

        # Fast path: token still valid
        if self._access_token and time.monotonic() < self._expires_at:
            return self._access_token

        async with self._lock:
            # Double-check after acquiring lock
            if self._access_token and time.monotonic() < self._expires_at:
                return self._access_token

            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    self._token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "scope": _OAUTH_SCOPES,
                    },
                )
                response.raise_for_status()
                body = response.json()

            self._access_token = body["access_token"]
            expires_in = int(body.get("expires_in", 3600))
            # Refresh 60 seconds before actual expiry
            self._expires_at = time.monotonic() + max(expires_in - 60, 30)

            logger.info("fefundinfo token refreshed", expires_in=expires_in)
            return self._access_token


# ---------------------------------------------------------------------------
#  FEFundInfoClient
# ---------------------------------------------------------------------------


class FEFundInfoClient:
    """Low-level async client for all 7 FE fundinfo APIs.

    Args:
        token_manager: OAuth2 token manager instance.
        subscription_key: Fefi-Apim-Subscription-Key header value.
        http_client: Optional injected httpx.AsyncClient (for testing).
        rate_limiter: Optional rate limiter. Defaults to 10 req/s.

    """

    # Base URLs for the 7 APIs
    URL_STATIC = "https://api.fefundinfo.com/funds/Static/1.0.0"
    URL_KEY_FACTS = "https://api.fefundinfo.com/funds/StaticKeyFacts/1.0.0"
    URL_DYNAMIC = "https://api.fefundinfo.com/funds/Dynamic/1.0.0"
    URL_SERIES = "https://api.fefundinfo.com/funds/DynamicDataSeries/1.0.0"
    URL_PERFORMANCE = "https://api.fefundinfo.com/funds/DynamicPerformance/1.0.0"
    URL_RATIOS = "https://api.fefundinfo.com/funds/RatiosAndExposures/1.0.0"

    def __init__(
        self,
        token_manager: FEFundInfoTokenManager,
        subscription_key: str,
        http_client: httpx.AsyncClient | None = None,
        rate_limiter: _AsyncTokenBucket | None = None,
    ):
        self._token_manager = token_manager
        self._subscription_key = subscription_key
        self._client = http_client
        self._owns_client = http_client is None
        self._rate_limiter = rate_limiter or _AsyncTokenBucket()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
            self._owns_client = True
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── Internal request helpers ────────────────────────────────

    async def _headers(self) -> dict[str, str]:
        token = await self._token_manager.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Fefi-Apim-Subscription-Key": self._subscription_key,
            "x-correlation-id": str(uuid4()),
            "Accept": "application/json",
        }

    async def _get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """Execute GET with rate limiting, retry, and error handling. Never raises."""
        await self._rate_limiter.acquire()
        headers = await self._headers()
        client = self._get_client()

        for attempt in range(max_retries):
            try:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                return dict(response.json())

            except httpx.HTTPStatusError as e:
                action = _classify_error(e.response.status_code)
                if action == "fail":
                    logger.error("fefundinfo auth failure", url=url, status=e.response.status_code)
                    return {}
                if action == "skip":
                    logger.warning("fefundinfo request error", url=url, status=e.response.status_code)
                    return {}
                wait = min(2**attempt * 2, 30)
                logger.warning(
                    "fefundinfo retrying", url=url, attempt=attempt + 1, wait=wait,
                )
                await asyncio.sleep(wait)

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                wait = min(2**attempt * 2, 30)
                logger.warning(
                    "fefundinfo connection error", url=url, error=str(e), wait=wait,
                )
                await asyncio.sleep(wait)

        logger.error("fefundinfo exhausted retries", url=url, max_retries=max_retries)
        return {}

    def _extract_result(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract Result array from standard FE fundinfo response envelope."""
        if not body:
            return []
        if not body.get("IsSuccess", False):
            msg = body.get("Message", "unknown")
            logger.warning("fefundinfo response not successful", message=msg)
            return []
        result = body.get("Result", [])
        if isinstance(result, list):
            return result
        return []

    @staticmethod
    def _chunk_isins(isins: list[str]) -> list[list[str]]:
        """Split ISINs into chunks of _MAX_BATCH_SIZE."""
        return [isins[i : i + _MAX_BATCH_SIZE] for i in range(0, len(isins), _MAX_BATCH_SIZE)]

    # ── Static API ──────────────────────────────────────────────

    async def _static_get(
        self, endpoint: str, isins: list[str],
    ) -> list[dict[str, Any]]:
        """Helper for Static API GET requests."""
        results: list[dict[str, Any]] = []
        for chunk in self._chunk_isins(isins):
            body = await self._get(
                f"{self.URL_STATIC}/{endpoint}",
                params={
                    "identifierType": "isins",
                    "identifierValue": chunk,
                },
            )
            results.extend(self._extract_result(body))
        return results

    async def get_fees(self, isins: list[str]) -> list[dict[str, Any]]:
        """Fetch static fees data."""
        return await self._static_get("Fees", isins)

    async def get_portfolio_managers(self, isins: list[str]) -> list[dict[str, Any]]:
        """Fetch portfolio manager data."""
        return await self._static_get("PortfolioManager", isins)

    async def get_country_registration(self, isins: list[str]) -> list[dict[str, Any]]:
        """Fetch country registration data."""
        return await self._static_get("CountryRegistration", isins)

    # ── Static Key Facts API ──────────────────────────────────

    async def _key_facts_get(
        self, endpoint: str, isins: list[str],
    ) -> list[dict[str, Any]]:
        """Helper for Static Key Facts API GET requests."""
        results: list[dict[str, Any]] = []
        for chunk in self._chunk_isins(isins):
            body = await self._get(
                f"{self.URL_KEY_FACTS}/{endpoint}",
                params={
                    "identifierType": "isins",
                    "identifierValue": chunk,
                },
            )
            results.extend(self._extract_result(body))
        return results

    async def get_listing(self, isins: list[str]) -> list[dict[str, Any]]:
        """Fetch listing data (Bloomberg/Reuters codes, exchange, launch price)."""
        return await self._key_facts_get("Listing", isins)

    async def get_classification(self, isins: list[str]) -> list[dict[str, Any]]:
        """Fetch classification data (MiFID, EFAMA, Sharia compliance)."""
        return await self._key_facts_get("Classification", isins)

    async def get_fund_information(self, isins: list[str]) -> list[dict[str, Any]]:
        """Fetch fund information (structure, domicile, objectives, benchmark)."""
        return await self._key_facts_get("FundInformation", isins)

    async def get_company(self, isins: list[str]) -> list[dict[str, Any]]:
        """Fetch management company data (name, address, country)."""
        return await self._key_facts_get("Company", isins)

    async def get_umbrella(self, isins: list[str]) -> list[dict[str, Any]]:
        """Fetch umbrella/fund family data (name, domicile, legal structure)."""
        return await self._key_facts_get("Umbrella", isins)

    async def get_share_class(self, isins: list[str]) -> list[dict[str, Any]]:
        """Fetch share class data (distribution type, hedging, minimum investment, target market)."""
        return await self._key_facts_get("ShareClass", isins)

    async def get_sdr(self, isins: list[str]) -> list[dict[str, Any]]:
        """Fetch SDR data (Sustainability Disclosure Requirements, ESG labels)."""
        return await self._key_facts_get("SDR", isins)

    # ── Dynamic API ─────────────────────────────────────────────

    async def _dynamic_get(
        self,
        endpoint: str,
        isins: list[str],
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        currencies: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Helper for Dynamic API GET requests."""
        results: list[dict[str, Any]] = []
        for chunk in self._chunk_isins(isins):
            params: dict[str, Any] = {
                "identifierType": "isins",
                "identifierValue": chunk,
            }
            if date_from:
                params["DateFrom"] = date_from
            if date_to:
                params["DateTo"] = date_to
            if currencies:
                params["Currencies"] = currencies
            body = await self._get(f"{self.URL_DYNAMIC}/{endpoint}", params=params)
            results.extend(self._extract_result(body))
        return results

    async def get_pricing(
        self, isins: list[str], date_from: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch current and historical fund pricing."""
        return await self._dynamic_get("Pricing", isins, date_from=date_from)

    async def get_aum(
        self, isins: list[str], date_from: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch assets under management data."""
        return await self._dynamic_get("Aum", isins, date_from=date_from)

    async def get_dividends(
        self, isins: list[str], date_from: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch dividend and yield data."""
        return await self._dynamic_get("Dividends", isins, date_from=date_from)

    async def get_analytics(
        self, isins: list[str], date_from: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch analytics data."""
        return await self._dynamic_get("Analytics", isins, date_from=date_from)

    async def get_ratings(
        self, isins: list[str], date_from: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch fund ratings data."""
        return await self._dynamic_get("Ratings", isins, date_from=date_from)

    # ── Dynamic Data Series API ─────────────────────────────────

    async def get_nav_series(
        self,
        isins: list[str],
        series_type: int = 2,
        period: str = "Daily",
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        fill_forward: bool = True,
    ) -> list[dict[str, Any]]:
        """Fetch NAV time series.

        Args:
            series_type: 1=Bid, 2=BidTr, 3=BidGtr, 7=NavPublished, etc.
            period: Daily, Weekly, Monthly, Quarterly, Yearly.

        """
        results: list[dict[str, Any]] = []
        for chunk in self._chunk_isins(isins):
            params: dict[str, Any] = {
                "identifierType": "isins",
                "identifierValue": chunk,
                "seriesType": series_type,
                "period": period,
                "endType": 1,  # DayEnd
                "fillForward": str(fill_forward).lower(),
            }
            if start_date:
                params["dateFrom"] = start_date
            if end_date:
                params["dateTo"] = end_date
            body = await self._get(f"{self.URL_SERIES}/Series", params=params)
            results.extend(self._extract_result(body))
        return results

    async def get_series_delta(
        self,
        isins: list[str],
        series_type: int = 2,
        *,
        from_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch delta updates for a series since a given date."""
        results: list[dict[str, Any]] = []
        for chunk in self._chunk_isins(isins):
            params: dict[str, Any] = {
                "identifierType": "isins",
                "identifierValue": chunk,
                "seriesType": series_type,
            }
            if from_date:
                params["deltaFrom"] = from_date
            body = await self._get(f"{self.URL_SERIES}/Delta", params=params)
            results.extend(self._extract_result(body))
        return results

    # ── Dynamic Performance API ─────────────────────────────────

    async def get_cumulative_performance_v2(
        self,
        isins: list[str],
        currency: str = "USD",
        period_end: int = 3,
    ) -> list[dict[str, Any]]:
        """Fetch cumulative performance (v2 API with rankings).

        Args:
            period_end: 1=DayEnd, 2=MonthEnd, 3=QuarterEnd, 4=YearEnd.

        """
        results: list[dict[str, Any]] = []
        for chunk in self._chunk_isins(isins):
            body = await self._get(
                f"{self.URL_PERFORMANCE}/CumulativePerformance",
                params={
                    "identifierType": "isins",
                    "identifierValue": chunk,
                    "Currency": currency,
                    "PerformanceEndType": period_end,
                    "MethodType": 1,  # BidToBid
                    "PriceType": 1,  # NetTotalReturn
                },
            )
            results.extend(self._extract_result(body))
        return results

    async def get_annualised_performance(
        self, isins: list[str], currency: str = "USD",
    ) -> list[dict[str, Any]]:
        """Fetch annualised performance data."""
        results: list[dict[str, Any]] = []
        for chunk in self._chunk_isins(isins):
            body = await self._get(
                f"{self.URL_PERFORMANCE}/AnnualisedPerformance",
                params={
                    "identifierType": "isins",
                    "identifierValue": chunk,
                    "Currency": currency,
                    "PerformanceEndType": 3,
                    "MethodType": 1,
                    "PriceType": 1,
                },
            )
            results.extend(self._extract_result(body))
        return results

    # ── Ratios & Exposures API ──────────────────────────────────

    async def get_holdings_breakdown(
        self, isins: list[str],
    ) -> list[dict[str, Any]]:
        """Fetch top holdings breakdown (FE fundinfo format)."""
        results: list[dict[str, Any]] = []
        for chunk in self._chunk_isins(isins):
            body = await self._get(
                f"{self.URL_RATIOS}/FEFIExposuresBreakdowns",
                params={
                    "identifierType": "isins",
                    "identifierValue": chunk,
                    "BreakdownTypes": ["FH"],
                },
            )
            results.extend(self._extract_result(body))
        return results

    async def get_exposures_breakdown(
        self,
        isins: list[str],
        breakdown_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch portfolio exposure breakdowns.

        Args:
            breakdown_types: AS=AssetClass, AR=Region, SC=Sector, CU=Currency,
                            CR=CreditRating, HD=Top10Holdings (default).

        """
        if breakdown_types is None:
            breakdown_types = ["AS", "AR", "SC", "CU", "HD"]
        results: list[dict[str, Any]] = []
        for chunk in self._chunk_isins(isins):
            body = await self._get(
                f"{self.URL_RATIOS}/ExposuresBreakdowns",
                params={
                    "identifierType": "isins",
                    "identifierValue": chunk,
                    "BreakdownTypes": breakdown_types,
                },
            )
            results.extend(self._extract_result(body))
        return results
