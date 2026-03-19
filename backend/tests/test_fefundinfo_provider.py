"""Tests for FE fundinfo provider — OAuth2 token manager, API client, and provider.

All HTTP calls are mocked — no real FE fundinfo API calls in tests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.providers.fefundinfo_client import (
    FEFundInfoClient,
    FEFundInfoTokenManager,
    _AsyncTokenBucket,
)
from app.services.providers.fefundinfo_provider import FEFundInfoProvider
from app.services.providers.protocol import RawInstrumentData

# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _mock_transport(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _json_response(data, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=data)


def _success_envelope(result: list) -> dict:
    """Build a standard FE fundinfo success response envelope."""
    return {"Message": "OK", "IsSuccess": True, "Request": {}, "Result": result}


def _make_client(handler) -> FEFundInfoClient:
    """Create an FEFundInfoClient with mocked token manager and HTTP transport."""
    token_mgr = MagicMock(spec=FEFundInfoTokenManager)
    token_mgr.get_token = AsyncMock(return_value="test-token-123")
    http_client = _mock_transport(handler)
    return FEFundInfoClient(
        token_manager=token_mgr,
        subscription_key="test-sub-key",
        http_client=http_client,
        rate_limiter=_AsyncTokenBucket(max_tokens=100.0, refill_rate=100.0),
    )


# ---------------------------------------------------------------------------
#  FEFundInfoTokenManager
# ---------------------------------------------------------------------------


class TestTokenManager:
    @pytest.mark.asyncio
    async def test_caches_token(self) -> None:
        """Second call reuses cached token without hitting the token endpoint."""
        mgr = FEFundInfoTokenManager(
            client_id="cid", client_secret="csec", token_url="https://test/token"
        )
        # Directly set cached token to avoid HTTP calls
        mgr._access_token = "tok-abc"
        mgr._expires_at = float("inf")  # Never expires

        t1 = await mgr.get_token()
        t2 = await mgr.get_token()

        assert t1 == "tok-abc"
        assert t2 == "tok-abc"

    @pytest.mark.asyncio
    async def test_refreshes_expired_token(self) -> None:
        """Token is refreshed when near expiry."""
        call_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return _json_response({"access_token": "new-token", "expires_in": 3600})

        mgr = FEFundInfoTokenManager(
            client_id="cid", client_secret="csec", token_url="https://test/token"
        )
        mgr._access_token = "old-token"
        mgr._expires_at = 0.0  # Already expired

        mock_client = _mock_transport(handler)
        # Patch AsyncClient as context manager returning our mock
        with patch("app.services.providers.fefundinfo_client.httpx.AsyncClient") as mock_cls:
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_client)
            ctx.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = ctx

            token = await mgr.get_token()

        assert token == "new-token"
        assert call_count == 1


# ---------------------------------------------------------------------------
#  FEFundInfoClient — API methods
# ---------------------------------------------------------------------------


class TestGetAnalytics:
    @pytest.mark.asyncio
    async def test_parses_response(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(_success_envelope([
                {
                    "Isin": "IE00B4L5Y983",
                    "Volatility3Y": 12.5,
                    "SharpeRatio3Y": 0.85,
                    "MaxDrawdown": -15.2,
                }
            ]))

        client = _make_client(handler)
        result = await client.get_analytics(["IE00B4L5Y983"])

        assert len(result) == 1
        assert result[0]["Isin"] == "IE00B4L5Y983"
        assert result[0]["Volatility3Y"] == 12.5


class TestGetCumulativePerformanceV2:
    @pytest.mark.asyncio
    async def test_parses_response(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(_success_envelope([
                {
                    "Isin": "IE00B4L5Y983",
                    "Performance1Y": 8.5,
                    "Performance3Y": 25.3,
                    "Rank1Y": 15,
                }
            ]))

        client = _make_client(handler)
        result = await client.get_cumulative_performance_v2(["IE00B4L5Y983"])

        assert len(result) == 1
        assert result[0]["Performance1Y"] == 8.5


class TestGetFees:
    @pytest.mark.asyncio
    async def test_parses_response(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(_success_envelope([
                {
                    "Isin": "IE00B4L5Y983",
                    "OngoingChargeFigure": 0.22,
                    "ManagementFee": 0.20,
                }
            ]))

        client = _make_client(handler)
        result = await client.get_fees(["IE00B4L5Y983"])

        assert len(result) == 1
        assert result[0]["OngoingChargeFigure"] == 0.22


class TestGetKeyFacts:
    @pytest.mark.asyncio
    async def test_listing(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(_success_envelope([
                {"Isin": "IE00TEST", "CitiCode": "QXR5", "OFST060000": "IWDA LN"}
            ]))

        client = _make_client(handler)
        result = await client.get_listing(["IE00TEST"])
        assert len(result) == 1
        assert result[0]["OFST060000"] == "IWDA LN"

    @pytest.mark.asyncio
    async def test_classification(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(_success_envelope([
                {"Isin": "IE00TEST", "OFST350000": "Non-complex"}
            ]))

        client = _make_client(handler)
        result = await client.get_classification(["IE00TEST"])
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_fund_information(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(_success_envelope([
                {"Isin": "IE00TEST", "ShareClassName": "Test Fund", "CurrencyCode": "USD"}
            ]))

        client = _make_client(handler)
        result = await client.get_fund_information(["IE00TEST"])
        assert len(result) == 1
        assert result[0]["ShareClassName"] == "Test Fund"

    @pytest.mark.asyncio
    async def test_share_class(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(_success_envelope([
                {"Isin": "IE00TEST", "DistributionType": "Accumulation"}
            ]))

        client = _make_client(handler)
        result = await client.get_share_class(["IE00TEST"])
        assert len(result) == 1


# ---------------------------------------------------------------------------
#  FEFundInfoClient — batching and error handling
# ---------------------------------------------------------------------------


class TestBatching:
    @pytest.mark.asyncio
    async def test_chunks_by_10(self) -> None:
        """ISINs are batched in groups of 10."""
        request_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            return _json_response(_success_envelope([{"Isin": "test"}]))

        client = _make_client(handler)
        isins = [f"ISIN{i:010d}" for i in range(25)]
        await client.get_fund_information(isins)

        assert request_count == 3  # 10 + 10 + 5


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_returns_empty_on_api_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "Bad Request"})

        client = _make_client(handler)
        result = await client.get_analytics(["INVALID"])

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_unsuccessful(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"IsSuccess": False, "Message": "Not found", "Result": []})

        client = _make_client(handler)
        result = await client.get_fees(["UNKNOWN"])

        assert result == []

    @pytest.mark.asyncio
    async def test_retries_on_500(self) -> None:
        attempt_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempt_count
            attempt_count += 1
            return httpx.Response(500, json={"error": "Internal Server Error"})

        client = _make_client(handler)
        result = await client.get_pricing(["IE00B4L5Y983"])

        assert result == []
        assert attempt_count == 3  # default max_retries


# ---------------------------------------------------------------------------
#  FEFundInfoClient — auth headers
# ---------------------------------------------------------------------------


class TestAuthHeaders:
    @pytest.mark.asyncio
    async def test_sends_auth_headers(self) -> None:
        captured_headers: dict[str, str] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return _json_response(_success_envelope([]))

        client = _make_client(handler)
        await client.get_fund_information(["IE00TEST"])

        assert captured_headers.get("authorization") == "Bearer test-token-123"
        assert captured_headers.get("fefi-apim-subscription-key") == "test-sub-key"
        assert "x-correlation-id" in captured_headers


# ---------------------------------------------------------------------------
#  FEFundInfoProvider — protocol compliance
# ---------------------------------------------------------------------------


class TestProviderFetchInstrument:
    def test_returns_raw_instrument_data(self) -> None:
        client = MagicMock(spec=FEFundInfoClient)
        client.get_fund_information = AsyncMock(return_value=[
            {
                "Isin": "IE00B4L5Y983",
                "ShareClassName": "iShares Core MSCI World UCITS ETF",
                "CurrencyCode": "USD",
                "DomicileCountry": "Ireland",
                "SectorName": "Global Equity Large Cap",
                "InstrumentTypeName": "ETF",
                "CitiCode": "QXR5",
            }
        ])

        provider = FEFundInfoProvider(client)
        result = provider.fetch_instrument("IE00B4L5Y983")

        assert result is not None
        assert isinstance(result, RawInstrumentData)
        assert result.isin == "IE00B4L5Y983"
        assert result.name == "iShares Core MSCI World UCITS ETF"
        assert result.instrument_type == "fund"
        assert result.source == "fefundinfo"
        assert result.currency == "USD"
        assert result.geography == "Ireland"
        assert result.asset_class == "equity"

    def test_returns_none_on_not_found(self) -> None:
        client = MagicMock(spec=FEFundInfoClient)
        client.get_fund_information = AsyncMock(return_value=[])

        provider = FEFundInfoProvider(client)
        result = provider.fetch_instrument("INVALID_ISIN")

        assert result is None


class TestProviderFetchBatch:
    def test_returns_list_of_raw_instrument_data(self) -> None:
        client = MagicMock(spec=FEFundInfoClient)
        client.get_fund_information = AsyncMock(return_value=[
            {
                "Isin": "IE00B4L5Y983",
                "ShareClassName": "Fund A",
                "CurrencyCode": "USD",
                "DomicileCountry": "Ireland",
                "SectorName": "Global Equity Large Cap",
            },
            {
                "Isin": "LU0996182563",
                "ShareClassName": "Fund B",
                "CurrencyCode": "EUR",
                "DomicileCountry": "Luxembourg",
                "SectorName": "Global Bond",
            },
        ])

        provider = FEFundInfoProvider(client)
        result = provider.fetch_batch(["IE00B4L5Y983", "LU0996182563"])

        assert len(result) == 2
        assert result[0].asset_class == "equity"
        assert result[1].asset_class == "fixed_income"  # "bond" in sector name

    def test_returns_empty_on_error(self) -> None:
        client = MagicMock(spec=FEFundInfoClient)
        client.get_fund_information = AsyncMock(side_effect=Exception("API down"))

        provider = FEFundInfoProvider(client)
        result = provider.fetch_batch(["IE00B4L5Y983"])

        assert result == []


class TestProviderFetchBatchHistory:
    def test_returns_dataframes(self) -> None:
        client = MagicMock(spec=FEFundInfoClient)
        client.get_nav_series = AsyncMock(return_value=[
            {
                "HistoryData": {
                    "Instrument": [
                        {
                            "Isin": "IE00B4L5Y983",
                            "CitiCode": "QXR5",
                            "InstrumentCode": "123",
                            "InstrumentTypeCode": "ETF",
                            "SeriesList": [
                                {
                                    "SeriesType": "BidTr",
                                    "SeriesCurrency": "USD",
                                    "SeriesData": [
                                        {"seriesData": "2026-01-01", "seriesValue": "100.0"},
                                        {"seriesData": "2026-01-02", "seriesValue": "101.5"},
                                        {"seriesData": "2026-01-03", "seriesValue": "102.3"},
                                    ],
                                }
                            ],
                        }
                    ]
                }
            }
        ])

        provider = FEFundInfoProvider(client)
        result = provider.fetch_batch_history(["IE00B4L5Y983"])

        assert "IE00B4L5Y983" in result
        df = result["IE00B4L5Y983"]
        assert len(df) == 3
        assert "Close" in df.columns
        assert df["Close"].iloc[0] == 100.0


# ---------------------------------------------------------------------------
#  FEFundInfoProvider — extended async methods
# ---------------------------------------------------------------------------


class TestProviderExtendedMethods:
    @pytest.mark.asyncio
    async def test_fetch_risk_profile(self) -> None:
        client = MagicMock(spec=FEFundInfoClient)
        client.get_analytics = AsyncMock(return_value=[
            {"Isin": "IE00TEST", "Volatility3Y": 12.5}
        ])

        provider = FEFundInfoProvider(client)
        result = await provider.fetch_risk_profile("IE00TEST")

        assert result["Volatility3Y"] == 12.5

    @pytest.mark.asyncio
    async def test_fetch_risk_profile_returns_empty_on_error(self) -> None:
        client = MagicMock(spec=FEFundInfoClient)
        client.get_analytics = AsyncMock(side_effect=Exception("fail"))

        provider = FEFundInfoProvider(client)
        result = await provider.fetch_risk_profile("IE00TEST")

        assert result == {}

    @pytest.mark.asyncio
    async def test_fetch_fund_snapshot(self) -> None:
        client = MagicMock(spec=FEFundInfoClient)
        client.get_fund_information = AsyncMock(return_value=[{"Isin": "IE00TEST"}])
        client.get_analytics = AsyncMock(return_value=[{"Volatility": 10}])
        client.get_cumulative_performance_v2 = AsyncMock(return_value=[{"Perf1Y": 5}])
        client.get_fees = AsyncMock(return_value=[{"OCF": 0.22}])
        client.get_aum = AsyncMock(return_value=[{"Aum": 1_000_000}])

        provider = FEFundInfoProvider(client)
        result = await provider.fetch_fund_snapshot("IE00TEST")

        assert result["instrument"]["Isin"] == "IE00TEST"
        assert result["risk"]["Volatility"] == 10
        assert result["fees"]["OCF"] == 0.22


# ---------------------------------------------------------------------------
#  FEFundInfoProvider — asset class inference
# ---------------------------------------------------------------------------


class TestAssetClassInference:
    def test_bond_sector(self) -> None:
        client = MagicMock(spec=FEFundInfoClient)
        client.get_fund_information = AsyncMock(return_value=[
            {"Isin": "TEST", "ShareClassName": "Bond Fund", "SectorName": "USD Corporate Bond"}
        ])
        provider = FEFundInfoProvider(client)
        result = provider.fetch_instrument("TEST")
        assert result is not None
        assert result.asset_class == "fixed_income"

    def test_money_market_sector(self) -> None:
        client = MagicMock(spec=FEFundInfoClient)
        client.get_fund_information = AsyncMock(return_value=[
            {"Isin": "TEST", "ShareClassName": "MM Fund", "SectorName": "USD Money Market"}
        ])
        provider = FEFundInfoProvider(client)
        result = provider.fetch_instrument("TEST")
        assert result is not None
        assert result.asset_class == "money_market"

    def test_multi_asset_sector(self) -> None:
        client = MagicMock(spec=FEFundInfoClient)
        client.get_fund_information = AsyncMock(return_value=[
            {"Isin": "TEST", "ShareClassName": "MA Fund", "SectorName": "Multi Asset Balanced"}
        ])
        provider = FEFundInfoProvider(client)
        result = provider.fetch_instrument("TEST")
        assert result is not None
        assert result.asset_class == "multi_asset"


# ---------------------------------------------------------------------------
#  Provider factory
# ---------------------------------------------------------------------------


class TestProviderFactory:
    def test_returns_yahoo_when_disabled(self) -> None:
        from app.services.providers import get_instrument_provider
        from app.services.providers.yahoo_finance_provider import YahooFinanceProvider

        with patch("app.core.config.settings.settings") as mock_settings:
            mock_settings.feature_fefundinfo_enabled = False
            provider = get_instrument_provider()

        assert isinstance(provider, YahooFinanceProvider)

    def test_returns_fefundinfo_when_enabled(self) -> None:
        from app.services.providers import get_instrument_provider
        from app.services.providers.fefundinfo_provider import FEFundInfoProvider

        with patch("app.core.config.settings.settings") as mock_settings:
            mock_settings.feature_fefundinfo_enabled = True
            mock_settings.fefundinfo_client_id = "cid"
            mock_settings.fefundinfo_client_secret = "csec"
            mock_settings.fefundinfo_subscription_key = "subkey"
            mock_settings.fefundinfo_token_url = "https://test/token"
            provider = get_instrument_provider()

        assert isinstance(provider, FEFundInfoProvider)


# ---------------------------------------------------------------------------
#  Rate limiter
# ---------------------------------------------------------------------------


class TestAsyncTokenBucket:
    @pytest.mark.asyncio
    async def test_acquire_does_not_raise(self) -> None:
        limiter = _AsyncTokenBucket(max_tokens=5.0, refill_rate=100.0)
        for _ in range(10):
            await limiter.acquire()
