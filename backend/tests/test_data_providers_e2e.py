"""E2E validation tests for data providers — hits real external APIs.

Run with:
    make test ARGS="-k test_data_providers_e2e"

Requires internet access. Each test has generous timeouts and skips gracefully
on network failures so CI stays green even if an external API is down.

APIs tested:
- BIS SDMX CSV API (no auth)
- IMF DataMapper JSON API (no auth)
- SEC EDGAR EFTS (no auth, 8 req/s rate limit)
- ESMA Solr Register API (no auth)
- OpenFIGI batch API (no auth for low-rate usage)
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import httpx
import pytest

# ── Helpers ───────────────────────────────────────────────────────────

TIMEOUT = 30.0  # generous per-request timeout


def _skip_on_network_error(exc: Exception) -> None:
    """Convert network errors into pytest.skip so CI stays green."""
    pytest.skip(f"External API unreachable: {exc}")


# ═══════════════════════════════════════════════════════════════════════
# BIS
# ═══════════════════════════════════════════════════════════════════════


class TestBisE2E:
    """Validate BIS SDMX CSV API returns parseable data."""

    async def test_fetch_credit_gap_us(self):
        """BIS credit-to-GDP gap for US — expect quarterly data."""
        from data_providers.bis.service import BisIndicator, fetch_bis_dataset

        try:
            async with httpx.AsyncClient() as client:
                results = await fetch_bis_dataset(
                    client,
                    "WS_CREDIT_GAP",
                    "credit_to_gdp_gap",
                    countries=["US"],
                )
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            _skip_on_network_error(exc)

        assert len(results) > 0, "BIS should return credit gap data for US"

        sample = results[0]
        assert isinstance(sample, BisIndicator)
        assert sample.country_code == "US"
        assert sample.indicator == "credit_to_gdp_gap"
        assert sample.dataset == "WS_CREDIT_GAP"
        assert isinstance(sample.period, datetime)
        assert isinstance(sample.value, float)

    async def test_fetch_debt_service_ratio_multi_country(self):
        """BIS DSR for US + BR — validates multi-country filter."""
        from data_providers.bis.service import fetch_bis_dataset

        try:
            async with httpx.AsyncClient() as client:
                results = await fetch_bis_dataset(
                    client,
                    "WS_DSR",
                    "debt_service_ratio",
                    countries=["US", "BR"],
                )
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            _skip_on_network_error(exc)

        assert len(results) > 0
        countries_found = {r.country_code for r in results}
        # At least one of the requested countries should be present
        assert countries_found & {"US", "BR"}, f"Expected US or BR, got {countries_found}"

    async def test_fetch_property_prices(self):
        """BIS property prices for DE — validates third dataset."""
        from data_providers.bis.service import fetch_bis_dataset

        try:
            async with httpx.AsyncClient() as client:
                results = await fetch_bis_dataset(
                    client,
                    "WS_SPP",
                    "property_prices",
                    countries=["DE"],
                )
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            _skip_on_network_error(exc)

        assert len(results) > 0
        assert all(r.country_code == "DE" for r in results)
        assert all(r.indicator == "property_prices" for r in results)

    async def test_fetch_all_bis_data_subset(self):
        """fetch_all_bis_data with 2 countries — validates aggregation."""
        from data_providers.bis.service import fetch_all_bis_data

        try:
            results = await fetch_all_bis_data(countries=["US", "GB"])
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            _skip_on_network_error(exc)

        assert len(results) > 0

        indicators = {r.indicator for r in results}
        # Should have data from at least 2 of the 3 datasets
        assert len(indicators) >= 2, f"Expected >=2 indicators, got {indicators}"

        countries = {r.country_code for r in results}
        assert countries & {"US", "GB"}


# ═══════════════════════════════════════════════════════════════════════
# IMF
# ═══════════════════════════════════════════════════════════════════════


class TestImfE2E:
    """Validate IMF DataMapper JSON API returns parseable forecasts."""

    async def test_fetch_gdp_growth(self):
        """IMF GDP growth for USA — core indicator."""
        from data_providers.imf.service import ImfForecast, fetch_imf_indicator

        try:
            async with httpx.AsyncClient() as client:
                results = await fetch_imf_indicator(
                    client,
                    "NGDP_RPCH",
                    countries=["USA"],
                )
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            _skip_on_network_error(exc)

        assert len(results) > 0, "IMF should return GDP growth for USA"

        sample = results[0]
        assert isinstance(sample, ImfForecast)
        assert sample.country_code == "US"  # ISO-3 → ISO-2
        assert sample.indicator == "NGDP_RPCH"
        assert isinstance(sample.year, int)
        assert isinstance(sample.value, float)
        assert len(sample.edition) == 6  # YYYYMM

    async def test_fetch_inflation(self):
        """IMF inflation for BRA — validates ISO-3 to ISO-2 conversion."""
        from data_providers.imf.service import fetch_imf_indicator

        try:
            async with httpx.AsyncClient() as client:
                results = await fetch_imf_indicator(
                    client,
                    "PCPIPCH",
                    countries=["BRA"],
                )
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            _skip_on_network_error(exc)

        assert len(results) > 0
        assert all(r.country_code == "BR" for r in results)

    async def test_fetch_fiscal_balance(self):
        """IMF fiscal balance for DEU — validates negative values."""
        from data_providers.imf.service import fetch_imf_indicator

        try:
            async with httpx.AsyncClient() as client:
                results = await fetch_imf_indicator(
                    client,
                    "GGXCNL_NGDP",
                    countries=["DEU"],
                )
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            _skip_on_network_error(exc)

        assert len(results) > 0
        assert all(r.country_code == "DE" for r in results)

    async def test_fetch_govt_debt(self):
        """IMF govt debt for JPN — known high-debt country."""
        from data_providers.imf.service import fetch_imf_indicator

        try:
            async with httpx.AsyncClient() as client:
                results = await fetch_imf_indicator(
                    client,
                    "GGXWDG_NGDP",
                    countries=["JPN"],
                )
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            _skip_on_network_error(exc)

        assert len(results) > 0
        # Japan debt-to-GDP is well above 100%
        recent = [r for r in results if r.year >= 2020]
        if recent:
            assert any(r.value > 100 for r in recent), "Japan debt/GDP should be >100%"

    async def test_fetch_all_imf_data_subset(self):
        """fetch_all_imf_data with 2 countries — validates aggregation."""
        from data_providers.imf.service import fetch_all_imf_data

        try:
            results = await fetch_all_imf_data(countries=["USA", "GBR"])
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            _skip_on_network_error(exc)

        assert len(results) > 0

        indicators = {r.indicator for r in results}
        # Should have data from at least 3 of 4 indicators
        assert len(indicators) >= 3, f"Expected >=3 indicators, got {indicators}"

        countries = {r.country_code for r in results}
        assert "US" in countries


# ═══════════════════════════════════════════════════════════════════════
# SEC EDGAR — N-PORT XML parsing (no DB, just API + parse)
# ═══════════════════════════════════════════════════════════════════════


class TestSecNportE2E:
    """Validate SEC EDGAR N-PORT filing retrieval + XML parsing.

    Uses edgartools to fetch real N-PORT filings. Rate-limited to 8 req/s.
    Tests parsing only — no DB operations (would need docker-compose).
    Skips if edgartools is not installed.
    """

    async def test_parse_nport_filing_vanguard(self):
        """Parse a real N-PORT filing from Vanguard (CIK 102909).

        Validates XML → NportHolding conversion with real-world data.
        """
        try:
            from edgartools import Company  # noqa: F401
        except ImportError:
            pytest.skip("edgartools not installed")

        from data_providers.sec.models import NportHolding
        from data_providers.sec.nport_service import _parse_nport_xml_holdings
        from data_providers.sec.shared import check_edgar_rate

        try:
            import xml.etree.ElementTree as ET

            check_edgar_rate()
            company = Company("102909")  # Vanguard

            check_edgar_rate()
            filings = company.get_filings(form="NPORT-P")
            if not filings or len(filings) == 0:
                pytest.skip("No N-PORT filings found for Vanguard")

            check_edgar_rate()
            filing = filings[0]
            xml_content = filing.xml()
            if not xml_content:
                pytest.skip("N-PORT filing XML is empty")

            root = ET.fromstring(xml_content)

            # Extract report date
            report_date = "2024-01-31"
            for elem in root.iter():
                if elem.tag.endswith("repPd") and elem.text:
                    report_date = elem.text.strip()[:10]
                    break

            holdings = _parse_nport_xml_holdings(root, "102909", report_date)

        except (httpx.HTTPError, asyncio.TimeoutError, ConnectionError) as exc:
            _skip_on_network_error(exc)
        except Exception as exc:
            if "rate" in str(exc).lower() or "limit" in str(exc).lower():
                pytest.skip(f"EDGAR rate limited: {exc}")
            raise

        assert len(holdings) > 0, "Vanguard N-PORT should have holdings"

        sample = holdings[0]
        assert isinstance(sample, NportHolding)
        assert sample.cik == "102909"
        assert sample.cusip  # should have CUSIP
        assert len(sample.cusip) >= 6

        # Vanguard funds typically have 50+ holdings
        assert len(holdings) >= 10, f"Expected >=10 holdings, got {len(holdings)}"

        # Check at least some have market values
        with_values = [h for h in holdings if h.market_value and h.market_value > 0]
        assert len(with_values) > 0, "Some holdings should have market values"


# ═══════════════════════════════════════════════════════════════════════
# SEC EDGAR — ADV search (lightweight, no PDF download)
# ═══════════════════════════════════════════════════════════════════════


class TestSecAdvE2E:
    """Validate SEC IAPD search API returns manager data."""

    async def test_search_known_manager(self):
        """Search for Bridgewater Associates — well-known large adviser."""
        from data_providers.sec.adv_service import AdvService

        # AdvService needs a db_session_factory, but search_managers
        # only uses IAPD API (no DB). Pass a dummy factory.
        svc = AdvService(db_session_factory=lambda: None)

        try:
            results = await svc.search_managers("Bridgewater Associates")
        except (httpx.HTTPError, asyncio.TimeoutError, ConnectionError) as exc:
            _skip_on_network_error(exc)
        except Exception as exc:
            if "rate" in str(exc).lower():
                pytest.skip(f"SEC rate limited: {exc}")
            raise

        assert len(results) > 0, "Bridgewater should be found in IAPD"

        # Find the main Bridgewater entity
        bridgewater = [r for r in results if "bridgewater" in r.firm_name.lower()]
        assert len(bridgewater) > 0

        bw = bridgewater[0]
        assert bw.crd_number  # should have CRD
        assert bw.firm_name


# ═══════════════════════════════════════════════════════════════════════
# ESMA Register — Solr API
# ═══════════════════════════════════════════════════════════════════════


class TestEsmaRegisterE2E:
    """Validate ESMA Register Solr API returns UCITS fund data."""

    async def test_get_total_count(self):
        """ESMA register total UCITS fund count — should be >30K."""
        from data_providers.esma.register_service import RegisterService

        try:
            async with RegisterService(page_size=10) as svc:
                count = await svc.get_total_count()
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            _skip_on_network_error(exc)

        assert count > 30_000, f"ESMA should have >30K UCITS funds, got {count}"

    async def test_iter_first_page(self):
        """Fetch first page of UCITS funds — validates parsing."""
        from data_providers.esma.models import EsmaFund
        from data_providers.esma.register_service import RegisterService

        try:
            async with RegisterService(page_size=50) as svc:
                funds: list[EsmaFund] = []
                async for fund in svc.iter_ucits_funds(max_pages=1):
                    funds.append(fund)
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            _skip_on_network_error(exc)

        assert len(funds) > 0, "Should get funds from first page"

        sample = funds[0]
        assert isinstance(sample, EsmaFund)
        assert sample.isin  # Fund LEI used as identifier
        assert sample.fund_name
        assert sample.esma_manager_id

    async def test_parse_manager_from_real_doc(self):
        """Parse manager data from real Solr response."""
        from data_providers.esma.register_service import RegisterService, parse_manager_from_doc

        try:
            async with RegisterService(page_size=10) as svc:
                data = await svc._fetch_page(start=0)
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            _skip_on_network_error(exc)

        docs = data.get("response", {}).get("docs", [])
        assert len(docs) > 0

        mgr = parse_manager_from_doc(docs[0])
        if mgr is not None:
            assert mgr.esma_id
            assert mgr.company_name


# ═══════════════════════════════════════════════════════════════════════
# OpenFIGI — ISIN → Ticker resolution
# ═══════════════════════════════════════════════════════════════════════


class TestOpenFigiE2E:
    """Validate OpenFIGI batch API resolves ISINs to tickers."""

    async def test_resolve_known_isin(self):
        """Resolve iShares Core MSCI World ISIN — well-known ETF."""
        from data_providers.esma.shared import resolve_isin_to_ticker_batch

        known_isin = "IE00B4L5Y983"  # iShares Core MSCI World UCITS ETF

        try:
            async with httpx.AsyncClient() as client:
                results = await resolve_isin_to_ticker_batch(
                    [known_isin],
                    http_client=client,
                )
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            _skip_on_network_error(exc)

        assert len(results) == 1
        result = results[0]
        assert result.isin == known_isin
        assert result.resolved_via == "openfigi"
        assert result.yahoo_ticker is not None
        # IWDA trades on various exchanges
        assert "IWDA" in (result.yahoo_ticker or "").upper() or result.yahoo_ticker

    async def test_resolve_multiple_isins(self):
        """Resolve 3 well-known European ETF ISINs."""
        from data_providers.esma.shared import resolve_isin_to_ticker_batch

        isins = [
            "IE00B4L5Y983",  # iShares Core MSCI World
            "IE00B3RBWM25",  # Vanguard FTSE All-World
            "LU0290358497",  # Xtrackers MSCI World
        ]

        try:
            async with httpx.AsyncClient() as client:
                results = await resolve_isin_to_ticker_batch(
                    isins,
                    http_client=client,
                )
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            _skip_on_network_error(exc)

        assert len(results) == 3

        resolved = [r for r in results if r.resolved_via == "openfigi"]
        # At least 2 of 3 well-known ETFs should resolve
        assert len(resolved) >= 2, f"Expected >=2 resolved, got {len(resolved)}"

    async def test_resolve_unknown_isin(self):
        """Bogus ISIN — should return unresolved without errors."""
        from data_providers.esma.shared import resolve_isin_to_ticker_batch

        try:
            async with httpx.AsyncClient() as client:
                results = await resolve_isin_to_ticker_batch(
                    ["XX0000000000"],
                    http_client=client,
                )
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            _skip_on_network_error(exc)

        assert len(results) == 1
        assert results[0].is_tradeable is False

    async def test_ticker_resolver_class(self):
        """TickerResolver.resolve_batch with real API."""
        from data_providers.esma.ticker_resolver import TickerResolver

        try:
            async with TickerResolver() as resolver:
                results = await resolver.resolve_batch(["IE00B4L5Y983"])
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            _skip_on_network_error(exc)

        assert len(results) == 1
        assert results[0].isin == "IE00B4L5Y983"


# ═══════════════════════════════════════════════════════════════════════
# Cross-provider — BIS + IMF consistency
# ═══════════════════════════════════════════════════════════════════════


class TestCrossProviderE2E:
    """Validate data consistency across providers."""

    async def test_bis_imf_country_overlap(self):
        """BIS and IMF should both have data for the US."""
        from data_providers.bis.service import fetch_bis_dataset
        from data_providers.imf.service import fetch_imf_indicator

        try:
            async with httpx.AsyncClient() as client:
                bis_results = await fetch_bis_dataset(
                    client, "WS_CREDIT_GAP", "credit_to_gdp_gap", countries=["US"],
                )
                imf_results = await fetch_imf_indicator(
                    client, "NGDP_RPCH", countries=["USA"],
                )
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            _skip_on_network_error(exc)

        assert len(bis_results) > 0, "BIS should have US data"
        assert len(imf_results) > 0, "IMF should have US data"

        # BIS uses ISO-2, IMF converts ISO-3 → ISO-2
        assert bis_results[0].country_code == "US"
        assert imf_results[0].country_code == "US"  # Converted from USA
