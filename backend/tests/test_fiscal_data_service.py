"""Tests for quant_engine.fiscal_data_service — U.S. Treasury Fiscal Data API client."""

from __future__ import annotations

import httpx
import pytest

from quant_engine.fiscal_data_service import (
    AsyncTokenBucketRateLimiter,
    AuctionResult,
    DebtSnapshot,
    ExchangeRate,
    FiscalDataService,
    InterestExpense,
    TreasuryRate,
    _parse_float,
)

# ---------------------------------------------------------------------------
#  _parse_float
# ---------------------------------------------------------------------------


class TestParseFloat:
    def test_valid_number(self) -> None:
        assert _parse_float("3.14") == 3.14

    def test_comma_separated(self) -> None:
        assert _parse_float("1,234.56") == 1234.56

    def test_missing_values(self) -> None:
        for v in (".", "#N/A", "", "NaN", "nan", "null", "None", None):
            assert _parse_float(v) is None

    def test_non_finite(self) -> None:
        assert _parse_float("inf") is None
        assert _parse_float("-inf") is None

    def test_unparseable(self) -> None:
        assert _parse_float("abc") is None


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _mock_transport(handler):
    """Create an httpx.AsyncClient with a mock transport."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _json_response(data: dict | list, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=data)


# ---------------------------------------------------------------------------
#  FiscalDataService.fetch_treasury_rates
# ---------------------------------------------------------------------------


class TestFetchTreasuryRates:
    @pytest.mark.asyncio
    async def test_parses_rates(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({
                "data": [
                    {
                        "record_date": "2026-01-31",
                        "security_desc": "Treasury Notes",
                        "avg_interest_rate_amt": "2.875",
                    },
                    {
                        "record_date": "2026-01-31",
                        "security_desc": "Treasury Bonds",
                        "avg_interest_rate_amt": "3.125",
                    },
                ],
                "meta": {"total-pages": 1},
            })

        client = _mock_transport(handler)
        svc = FiscalDataService(client, rate_limiter=AsyncTokenBucketRateLimiter())
        result = await svc.fetch_treasury_rates("2026-01-01")

        assert len(result) == 2
        assert isinstance(result[0], TreasuryRate)
        assert result[0].avg_interest_rate_amt == 2.875
        assert result[1].security_desc == "Treasury Bonds"

    @pytest.mark.asyncio
    async def test_skips_missing_rates(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({
                "data": [
                    {
                        "record_date": "2026-01-31",
                        "security_desc": "T-Bills",
                        "avg_interest_rate_amt": "null",
                    },
                ],
                "meta": {"total-pages": 1},
            })

        client = _mock_transport(handler)
        svc = FiscalDataService(client, rate_limiter=AsyncTokenBucketRateLimiter())
        result = await svc.fetch_treasury_rates("2026-01-01")

        assert len(result) == 0


# ---------------------------------------------------------------------------
#  FiscalDataService.fetch_debt_to_penny
# ---------------------------------------------------------------------------


class TestFetchDebtToPenny:
    @pytest.mark.asyncio
    async def test_parses_debt(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({
                "data": [
                    {
                        "record_date": "2026-03-18",
                        "tot_pub_debt_out_amt": "36000000000000.00",
                        "intragov_hold_amt": "7000000000000.00",
                        "debt_held_public_amt": "29000000000000.00",
                    },
                ],
                "meta": {"total-pages": 1},
            })

        client = _mock_transport(handler)
        svc = FiscalDataService(client, rate_limiter=AsyncTokenBucketRateLimiter())
        result = await svc.fetch_debt_to_penny("2026-03-01")

        assert len(result) == 1
        assert isinstance(result[0], DebtSnapshot)
        assert result[0].tot_pub_debt_out_amt == 36_000_000_000_000.0


# ---------------------------------------------------------------------------
#  FiscalDataService.fetch_treasury_auctions
# ---------------------------------------------------------------------------


class TestFetchTreasuryAuctions:
    @pytest.mark.asyncio
    async def test_parses_auctions(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({
                "data": [
                    {
                        "auction_date": "2026-03-15",
                        "security_type": "Note",
                        "security_term": "10-Year",
                        "high_yield": "4.250",
                        "bid_to_cover_ratio": "2.45",
                    },
                ],
                "meta": {"total-pages": 1},
            })

        client = _mock_transport(handler)
        svc = FiscalDataService(client, rate_limiter=AsyncTokenBucketRateLimiter())
        result = await svc.fetch_treasury_auctions("2026-03-01")

        assert len(result) == 1
        assert isinstance(result[0], AuctionResult)
        assert result[0].high_yield == 4.25
        assert result[0].bid_to_cover_ratio == 2.45

    @pytest.mark.asyncio
    async def test_nullable_fields(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({
                "data": [
                    {
                        "auction_date": "2026-03-10",
                        "security_type": "Bill",
                        "security_term": "4-Week",
                        "high_yield": "",
                        "bid_to_cover_ratio": "3.10",
                    },
                ],
                "meta": {"total-pages": 1},
            })

        client = _mock_transport(handler)
        svc = FiscalDataService(client, rate_limiter=AsyncTokenBucketRateLimiter())
        result = await svc.fetch_treasury_auctions("2026-03-01")

        assert result[0].high_yield is None
        assert result[0].bid_to_cover_ratio == 3.1


# ---------------------------------------------------------------------------
#  FiscalDataService.fetch_exchange_rates
# ---------------------------------------------------------------------------


class TestFetchExchangeRates:
    @pytest.mark.asyncio
    async def test_parses_exchange_rates(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({
                "data": [
                    {
                        "record_date": "2026-03-31",
                        "country_currency_desc": "Brazil-Real",
                        "exchange_rate": "5.15",
                    },
                ],
                "meta": {"total-pages": 1},
            })

        client = _mock_transport(handler)
        svc = FiscalDataService(client, rate_limiter=AsyncTokenBucketRateLimiter())
        result = await svc.fetch_exchange_rates("2026-01-01")

        assert len(result) == 1
        assert isinstance(result[0], ExchangeRate)
        assert result[0].exchange_rate == 5.15


# ---------------------------------------------------------------------------
#  FiscalDataService.fetch_interest_expense
# ---------------------------------------------------------------------------


class TestFetchInterestExpense:
    @pytest.mark.asyncio
    async def test_parses_expense(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({
                "data": [
                    {
                        "record_date": "2026-02-28",
                        "expense_catg_desc": "Treasury Notes",
                        "month_expense_amt": "45000000000.00",
                        "fytd_expense_amt": "250000000000.00",
                    },
                ],
                "meta": {"total-pages": 1},
            })

        client = _mock_transport(handler)
        svc = FiscalDataService(client, rate_limiter=AsyncTokenBucketRateLimiter())
        result = await svc.fetch_interest_expense("2026-01-01")

        assert len(result) == 1
        assert isinstance(result[0], InterestExpense)
        assert result[0].month_expense_amt == 45_000_000_000.0


# ---------------------------------------------------------------------------
#  Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_returns_empty_on_500(self) -> None:
        attempt_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempt_count
            attempt_count += 1
            return httpx.Response(500, json={"error": "Internal Server Error"})

        client = _mock_transport(handler)
        svc = FiscalDataService(client, rate_limiter=AsyncTokenBucketRateLimiter())
        result = await svc.fetch_treasury_rates("2026-01-01")

        assert result == []
        assert attempt_count == 3  # default max_retries

    @pytest.mark.asyncio
    async def test_returns_empty_on_400(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "Bad Request"})

        client = _mock_transport(handler)
        svc = FiscalDataService(client, rate_limiter=AsyncTokenBucketRateLimiter())
        result = await svc.fetch_debt_to_penny("2026-01-01")

        assert result == []


# ---------------------------------------------------------------------------
#  Pagination
# ---------------------------------------------------------------------------


class TestPagination:
    @pytest.mark.asyncio
    async def test_handles_multi_page(self) -> None:
        call_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _json_response({
                    "data": [{"record_date": "2026-01-31", "security_desc": "A", "avg_interest_rate_amt": "2.5"}],
                    "meta": {"total-pages": 2},
                })
            return _json_response({
                "data": [{"record_date": "2026-02-28", "security_desc": "B", "avg_interest_rate_amt": "2.6"}],
                "meta": {"total-pages": 2},
            })

        client = _mock_transport(handler)
        svc = FiscalDataService(client, rate_limiter=AsyncTokenBucketRateLimiter())
        result = await svc.fetch_treasury_rates("2026-01-01")

        assert len(result) == 2
        assert call_count == 2


# ---------------------------------------------------------------------------
#  AsyncTokenBucketRateLimiter
# ---------------------------------------------------------------------------


class TestAsyncRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire_does_not_raise(self) -> None:
        limiter = AsyncTokenBucketRateLimiter(max_tokens=2.0, refill_rate=10.0)
        await limiter.acquire()
        await limiter.acquire()
        # Third acquire should still work (refills fast)
        await limiter.acquire()
