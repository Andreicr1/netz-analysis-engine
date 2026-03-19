"""Tests for quant_engine.ofr_hedge_fund_service — OFR Hedge Fund Monitor API client."""

from __future__ import annotations

import httpx
import pytest

from quant_engine.fiscal_data_service import AsyncTokenBucketRateLimiter
from quant_engine.ofr_hedge_fund_service import (
    CounterpartySnapshot,
    IndustrySizeSnapshot,
    LeverageSnapshot,
    OFRHedgeFundService,
    RepoVolumeSnapshot,
    RiskScenarioSnapshot,
    SeriesMetadata,
    StrategySnapshot,
    _parse_value,
)

# ---------------------------------------------------------------------------
#  _parse_value
# ---------------------------------------------------------------------------


class TestParseValue:
    def test_valid(self) -> None:
        assert _parse_value(3.14) == 3.14

    def test_string_number(self) -> None:
        assert _parse_value("2.5") == 2.5

    def test_none(self) -> None:
        assert _parse_value(None) is None

    def test_non_finite(self) -> None:
        assert _parse_value(float("inf")) is None

    def test_unparseable(self) -> None:
        assert _parse_value("abc") is None


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _mock_transport(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _json_response(data, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=data)


def _timeseries_response(pairs: list[list]) -> httpx.Response:
    """Build a standard OFR timeseries response."""
    return _json_response(pairs)


# ---------------------------------------------------------------------------
#  fetch_timeseries
# ---------------------------------------------------------------------------


class TestFetchTimeseries:
    @pytest.mark.asyncio
    async def test_parses_pairs(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _timeseries_response([
                ["2026-03-31", 1.85],
                ["2025-12-31", 1.78],
            ])

        client = _mock_transport(handler)
        svc = OFRHedgeFundService(client, rate_limiter=AsyncTokenBucketRateLimiter())
        result = await svc.fetch_timeseries("FPF-ALLQHF_LEVERAGERATIO_GAVWMEAN", "2025-01-01")

        assert len(result) == 2
        assert result[0] == ("2026-03-31", 1.85)
        assert result[1] == ("2025-12-31", 1.78)

    @pytest.mark.asyncio
    async def test_skips_null_values(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _timeseries_response([
                ["2026-03-31", 1.85],
                ["2025-12-31", None],
            ])

        client = _mock_transport(handler)
        svc = OFRHedgeFundService(client, rate_limiter=AsyncTokenBucketRateLimiter())
        result = await svc.fetch_timeseries("FPF-TEST", "2025-01-01")

        # remove_nulls=true is in params, but we also filter locally
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "fail"})

        client = _mock_transport(handler)
        svc = OFRHedgeFundService(client, rate_limiter=AsyncTokenBucketRateLimiter())
        result = await svc.fetch_timeseries("FPF-TEST", "2025-01-01")

        assert result == []


# ---------------------------------------------------------------------------
#  fetch_industry_leverage
# ---------------------------------------------------------------------------


class TestFetchIndustryLeverage:
    @pytest.mark.asyncio
    async def test_merges_leverage_metrics(self) -> None:
        responses = {
            "FPF-ALLQHF_GAVN10_LEVERAGERATIO_AVERAGE": [["2026-03-31", 18.16]],
            "FPF-ALLQHF_GAVN11TO50_LEVERAGERATIO_AVERAGE": [["2026-03-31", 12.11]],
            "FPF-ALLQHF_GAVN51_LEVERAGERATIO_AVERAGE": [["2026-03-31", 1.81]],
        }

        async def handler(request: httpx.Request) -> httpx.Response:
            mne = str(request.url.params.get("mnemonic", ""))
            return _timeseries_response(responses.get(mne, []))

        client = _mock_transport(handler)
        svc = OFRHedgeFundService(client, rate_limiter=AsyncTokenBucketRateLimiter())
        result = await svc.fetch_industry_leverage("2025-01-01")

        assert len(result) == 1
        assert isinstance(result[0], LeverageSnapshot)
        assert result[0].gav_weighted_mean == 18.16  # top10
        assert result[0].p50 == 12.11  # mid (11-50)
        assert result[0].p5 == 1.81  # rest (51+)


# ---------------------------------------------------------------------------
#  fetch_industry_size
# ---------------------------------------------------------------------------


class TestFetchIndustrySize:
    @pytest.mark.asyncio
    async def test_merges_size_metrics(self) -> None:
        responses = {
            "FPF-ALLQHF_GAV_SUM": [["2026-03-31", 5_000_000]],
            "FPF-ALLQHF_NAV_SUM": [["2026-03-31", 4_200_000]],
            "FPF-ALLQHF_COUNT": [["2026-03-31", 1500]],
        }

        async def handler(request: httpx.Request) -> httpx.Response:
            mne = str(request.url.params.get("mnemonic", ""))
            return _timeseries_response(responses.get(mne, []))

        client = _mock_transport(handler)
        svc = OFRHedgeFundService(client, rate_limiter=AsyncTokenBucketRateLimiter())
        result = await svc.fetch_industry_size("2025-01-01")

        assert len(result) == 1
        assert isinstance(result[0], IndustrySizeSnapshot)
        assert result[0].gav_sum == 5_000_000
        assert result[0].nav_sum == 4_200_000
        assert result[0].fund_count == 1500


# ---------------------------------------------------------------------------
#  fetch_strategy_breakdown
# ---------------------------------------------------------------------------


class TestFetchStrategyBreakdown:
    @pytest.mark.asyncio
    async def test_fetches_all_strategies(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _timeseries_response([["2026-03-31", 1_000_000]])

        client = _mock_transport(handler)
        svc = OFRHedgeFundService(client, rate_limiter=AsyncTokenBucketRateLimiter())
        result = await svc.fetch_strategy_breakdown("2025-01-01")

        assert len(result) == 9  # 9 strategies
        assert all(isinstance(r, StrategySnapshot) for r in result)
        strategies = {r.strategy for r in result}
        assert "equity" in strategies
        assert "credit" in strategies
        assert "rv" in strategies


# ---------------------------------------------------------------------------
#  fetch_repo_volumes
# ---------------------------------------------------------------------------


class TestFetchRepoVolumes:
    @pytest.mark.asyncio
    async def test_parses_volumes(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _timeseries_response([
                ["2026-02-28", 850_000],
                ["2026-01-31", 820_000],
            ])

        client = _mock_transport(handler)
        svc = OFRHedgeFundService(client, rate_limiter=AsyncTokenBucketRateLimiter())
        result = await svc.fetch_repo_volumes("2025-01-01")

        assert len(result) == 2
        assert isinstance(result[0], RepoVolumeSnapshot)
        assert result[0].volume == 850_000


# ---------------------------------------------------------------------------
#  fetch_risk_scenarios
# ---------------------------------------------------------------------------


class TestFetchRiskScenarios:
    @pytest.mark.asyncio
    async def test_fetches_scenarios(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _timeseries_response([["2026-03-31", -2.5]])

        client = _mock_transport(handler)
        svc = OFRHedgeFundService(client, rate_limiter=AsyncTokenBucketRateLimiter())
        result = await svc.fetch_risk_scenarios("2025-01-01")

        assert len(result) == 4  # 4 scenarios
        assert all(isinstance(r, RiskScenarioSnapshot) for r in result)
        scenarios = {r.scenario for r in result}
        assert "cds_up_250bps_p5" in scenarios
        assert "cds_down_250bps_p50" in scenarios


# ---------------------------------------------------------------------------
#  search_series
# ---------------------------------------------------------------------------


class TestSearchSeries:
    @pytest.mark.asyncio
    async def test_parses_metadata(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response([
                {
                    "mnemonic": "FPF-ALLQHF_NAV_SUM",
                    "field": "mnemonic",
                    "value": "FPF-ALLQHF_NAV_SUM",
                    "dataset": "fpf",
                    "type": "str",
                },
                {
                    "mnemonic": "FPF-ALLQHF_NAV_SUM",
                    "field": "description/name",
                    "value": "Total NAV",
                    "dataset": "fpf",
                    "type": "str",
                },
            ])

        client = _mock_transport(handler)
        svc = OFRHedgeFundService(client, rate_limiter=AsyncTokenBucketRateLimiter())
        result = await svc.search_series("NAV")

        assert len(result) == 1
        assert isinstance(result[0], SeriesMetadata)
        assert result[0].mnemonic == "FPF-ALLQHF_NAV_SUM"
        assert result[0].description == "Total NAV"

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "fail"})

        client = _mock_transport(handler)
        svc = OFRHedgeFundService(client, rate_limiter=AsyncTokenBucketRateLimiter())
        result = await svc.search_series("leverage")

        assert result == []


# ---------------------------------------------------------------------------
#  fetch_counterparty_concentration
# ---------------------------------------------------------------------------


class TestFetchCounterpartyConcentration:
    @pytest.mark.asyncio
    async def test_fetches_counterparty(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _timeseries_response([["2026-03-31", 0.65]])

        client = _mock_transport(handler)
        svc = OFRHedgeFundService(client, rate_limiter=AsyncTokenBucketRateLimiter())
        result = await svc.fetch_counterparty_concentration("2025-01-01")

        assert len(result) == 2  # 2 mnemonics
        assert all(isinstance(r, CounterpartySnapshot) for r in result)
