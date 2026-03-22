"""Tests for ESMA data provider — register service, ticker resolver, shared utilities.

Covers:
- EsmaManager / EsmaFund / IsinResolution frozen dataclass creation
- RegisterService Solr page fetching and UCITS fund iteration
- _parse_fund_doc() validation (ISIN length, required fields, host states)
- parse_manager_from_doc() parsing
- TickerResolver batch + chunked resolution
- OpenFIGI → Yahoo Finance ticker conversion
- Rate limiter fallback (local token bucket)
- Entity name sanitization
- Error handling (HTTP errors, malformed responses)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from data_providers.esma.models import EsmaFund, EsmaManager, IsinResolution
from data_providers.esma.register_service import (
    RegisterService,
    _parse_fund_doc,
    _str_or_none,
    parse_manager_from_doc,
)
from data_providers.esma.shared import (
    EXCHANGE_SUFFIX_MAP,
    OPENFIGI_BATCH_SIZE,
    TRADEABLE_EXCHANGES,
    _openfigi_to_yahoo_ticker,
    resolve_isin_to_ticker_batch,
    sanitize_entity_name,
)
from data_providers.esma.ticker_resolver import TickerResolver

# ── EsmaManager Dataclass ────────────────────────────────────────────


class TestEsmaManager:
    def test_creation(self):
        m = EsmaManager(
            esma_id="MGR001",
            lei="529900ABCDEF1234",
            company_name="Test Asset Management",
            country="LU",
            authorization_status="Authorised",
            fund_count=15,
        )
        assert m.esma_id == "MGR001"
        assert m.fund_count == 15

    def test_frozen_immutability(self):
        m = EsmaManager(
            esma_id="MGR001",
            lei=None,
            company_name="Test",
            country=None,
            authorization_status=None,
            fund_count=None,
        )
        with pytest.raises(AttributeError):
            m.company_name = "Changed"  # type: ignore[misc]

    def test_optional_sec_crd(self):
        m = EsmaManager(
            esma_id="MGR001",
            lei=None,
            company_name="Test",
            country=None,
            authorization_status=None,
            fund_count=None,
            sec_crd_number="123456",
        )
        assert m.sec_crd_number == "123456"


# ── EsmaFund Dataclass ───────────────────────────────────────────────


class TestEsmaFund:
    def test_creation(self):
        f = EsmaFund(
            isin="IE00B4L5Y983",
            fund_name="iShares Core MSCI World",
            esma_manager_id="MGR001",
            domicile="IE",
            fund_type="UCITS",
            host_member_states=["DE", "FR", "NL"],
        )
        assert f.isin == "IE00B4L5Y983"
        assert len(f.host_member_states) == 3

    def test_default_host_states(self):
        f = EsmaFund(
            isin="IE00B4L5Y983",
            fund_name="Test Fund",
            esma_manager_id="MGR001",
            domicile=None,
            fund_type=None,
        )
        assert f.host_member_states == []

    def test_optional_ticker(self):
        f = EsmaFund(
            isin="IE00B4L5Y983",
            fund_name="Test Fund",
            esma_manager_id="MGR001",
            domicile=None,
            fund_type=None,
            yahoo_ticker="IWDA.AS",
        )
        assert f.yahoo_ticker == "IWDA.AS"


# ── IsinResolution Dataclass ─────────────────────────────────────────


class TestIsinResolution:
    def test_resolved(self):
        r = IsinResolution(
            isin="IE00B4L5Y983",
            yahoo_ticker="IWDA.AS",
            exchange="NA",
            resolved_via="openfigi",
            is_tradeable=True,
        )
        assert r.is_tradeable is True
        assert r.resolved_via == "openfigi"

    def test_unresolved(self):
        r = IsinResolution(
            isin="XX0000000000",
            yahoo_ticker=None,
            exchange=None,
            resolved_via="unresolved",
            is_tradeable=False,
        )
        assert r.is_tradeable is False

    def test_frozen_immutability(self):
        r = IsinResolution(
            isin="IE00B4L5Y983",
            yahoo_ticker="IWDA.AS",
            exchange="NA",
            resolved_via="openfigi",
            is_tradeable=True,
        )
        with pytest.raises(AttributeError):
            r.yahoo_ticker = "CHANGED"  # type: ignore[misc]


# ── _parse_fund_doc ──────────────────────────────────────────────────


class TestParseFundDoc:
    def test_valid_doc(self):
        doc = {
            "funds_lei": "529900KQKMU0OADYYE46",
            "funds_national_name": "iShares Core MSCI World",
            "funds_manager_nat_code": "MGR001",
            "funds_domicile_cou_code": "IE",
            "funds_legal_framework_name": "UCITS",
            "funds_host_country_codes": ["DE", "FR"],
        }
        fund = _parse_fund_doc(doc)
        assert fund is not None
        assert fund.isin == "529900KQKMU0OADYYE46"
        assert fund.fund_name == "iShares Core MSCI World"
        assert fund.host_member_states == ["DE", "FR"]

    def test_missing_lei_returns_none(self):
        doc = {
            "funds_national_name": "Test Fund",
            "funds_manager_nat_code": "MGR001",
        }
        assert _parse_fund_doc(doc) is None

    def test_missing_fund_name_returns_none(self):
        doc = {
            "funds_lei": "529900KQKMU0OADYYE46",
            "funds_manager_nat_code": "MGR001",
        }
        assert _parse_fund_doc(doc) is None

    def test_missing_manager_id_returns_none(self):
        doc = {
            "funds_lei": "529900KQKMU0OADYYE46",
            "funds_national_name": "Test Fund",
        }
        assert _parse_fund_doc(doc) is None

    def test_empty_lei_returns_none(self):
        doc = {
            "funds_lei": "   ",
            "funds_national_name": "Test Fund",
            "funds_manager_nat_code": "MGR001",
        }
        assert _parse_fund_doc(doc) is None

    def test_lei_whitespace_trimmed(self):
        doc = {
            "funds_lei": "  529900kqkmu0oadyye46  ",
            "funds_national_name": "Test",
            "funds_manager_nat_code": "MGR001",
        }
        fund = _parse_fund_doc(doc)
        assert fund is not None
        assert fund.isin == "529900KQKMU0OADYYE46"

    def test_host_states_as_string(self):
        doc = {
            "funds_lei": "529900KQKMU0OADYYE46",
            "funds_national_name": "Test Fund",
            "funds_manager_nat_code": "MGR001",
            "funds_host_country_codes": "DE, FR, NL",
        }
        fund = _parse_fund_doc(doc)
        assert fund is not None
        assert fund.host_member_states == ["DE", "FR", "NL"]

    def test_host_states_empty(self):
        doc = {
            "funds_lei": "529900KQKMU0OADYYE46",
            "funds_national_name": "Test Fund",
            "funds_manager_nat_code": "MGR001",
        }
        fund = _parse_fund_doc(doc)
        assert fund is not None
        assert fund.host_member_states == []

    def test_optional_fields_none(self):
        doc = {
            "funds_lei": "529900KQKMU0OADYYE46",
            "funds_national_name": "Test Fund",
            "funds_manager_nat_code": "MGR001",
        }
        fund = _parse_fund_doc(doc)
        assert fund is not None
        assert fund.domicile is None
        assert fund.fund_type is None


# ── parse_manager_from_doc ───────────────────────────────────────────


class TestParseManagerFromDoc:
    def test_valid_doc(self):
        doc = {
            "funds_manager_nat_code": "MGR001",
            "funds_manager_nat_name": "Test Asset Management",
            "funds_manager_lei": "529900ABC",
            "funds_ca_cou_code": "LU",
            "funds_status_code_name": "Active",
        }
        mgr = parse_manager_from_doc(doc)
        assert mgr is not None
        assert mgr.esma_id == "MGR001"
        assert mgr.company_name == "Test Asset Management"
        assert mgr.country == "LU"

    def test_missing_manager_id_returns_none(self):
        doc = {"funds_manager_nat_name": "Test"}
        assert parse_manager_from_doc(doc) is None

    def test_missing_company_name_returns_none(self):
        doc = {"funds_manager_nat_code": "MGR001"}
        assert parse_manager_from_doc(doc) is None


# ── _str_or_none ─────────────────────────────────────────────────────


class TestStrOrNone:
    def test_string_value(self):
        assert _str_or_none("hello") == "hello"

    def test_string_with_whitespace(self):
        assert _str_or_none("  hello  ") == "hello"

    def test_none_value(self):
        assert _str_or_none(None) is None

    def test_empty_string(self):
        assert _str_or_none("") is None

    def test_whitespace_only(self):
        assert _str_or_none("   ") is None

    def test_numeric_value(self):
        assert _str_or_none(42) == "42"


# ── OpenFIGI → Yahoo Finance Ticker Conversion ───────────────────────


class TestOpenfigi2Yahoo:
    def test_london_exchange(self):
        assert _openfigi_to_yahoo_ticker("VOD", "LN") == "VOD.L"

    def test_german_exchange(self):
        assert _openfigi_to_yahoo_ticker("SAP", "GY") == "SAP.DE"

    def test_us_exchange_no_suffix(self):
        assert _openfigi_to_yahoo_ticker("AAPL", "US") == "AAPL"

    def test_paris_exchange(self):
        assert _openfigi_to_yahoo_ticker("OR", "FP") == "OR.PA"

    def test_amsterdam_exchange(self):
        assert _openfigi_to_yahoo_ticker("ASML", "NA") == "ASML.AS"

    def test_no_ticker(self):
        assert _openfigi_to_yahoo_ticker(None, "LN") is None

    def test_no_exchange(self):
        assert _openfigi_to_yahoo_ticker("AAPL", None) == "AAPL"

    def test_unknown_exchange(self):
        assert _openfigi_to_yahoo_ticker("XYZ", "ZZ") == "XYZ"


# ── Exchange Suffix Map Constants ─────────────────────────────────────


class TestExchangeConstants:
    def test_tradeable_exchanges_match_map(self):
        assert frozenset(EXCHANGE_SUFFIX_MAP.keys()) == TRADEABLE_EXCHANGES

    def test_key_exchanges_present(self):
        assert "LN" in EXCHANGE_SUFFIX_MAP
        assert "GY" in EXCHANGE_SUFFIX_MAP
        assert "FP" in EXCHANGE_SUFFIX_MAP
        assert "NA" in EXCHANGE_SUFFIX_MAP
        assert "IM" in EXCHANGE_SUFFIX_MAP
        assert "US" in EXCHANGE_SUFFIX_MAP


# ── sanitize_entity_name ─────────────────────────────────────────────


class TestSanitizeEntityName:
    def test_valid_name(self):
        assert sanitize_entity_name("BlackRock Asset Management") == "BlackRock Asset Management"

    def test_trimmed(self):
        assert sanitize_entity_name("  Test  ") == "Test"

    def test_empty_string(self):
        assert sanitize_entity_name("") is None

    def test_too_long(self):
        assert sanitize_entity_name("A" * 201) is None

    def test_max_length_ok(self):
        assert sanitize_entity_name("A" * 200) == "A" * 200

    def test_unsafe_chars(self):
        assert sanitize_entity_name("Test<script>") is None

    def test_allowed_punctuation(self):
        assert sanitize_entity_name("O'Brien & Co., Inc.") == "O'Brien & Co., Inc."

    def test_parentheses_allowed(self):
        assert sanitize_entity_name("Test (UK) Ltd") == "Test (UK) Ltd"

    def test_hyphen_allowed(self):
        assert sanitize_entity_name("Well-Known Fund") == "Well-Known Fund"


# ── resolve_isin_to_ticker_batch ─────────────────────────────────────


class TestResolveIsinBatch:
    async def test_successful_resolution(self):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"data": [{"ticker": "IWDA", "exchCode": "NA"}]},
            {"data": [{"ticker": "VWRL", "exchCode": "LN"}]},
        ]
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock()
        client.post = AsyncMock(return_value=mock_response)

        results = await resolve_isin_to_ticker_batch(
            ["IE00B4L5Y983", "IE00B3RBWM25"],
            http_client=client,
        )

        assert len(results) == 2
        assert results[0].yahoo_ticker == "IWDA.AS"
        assert results[0].is_tradeable is True
        assert results[1].yahoo_ticker == "VWRL.L"
        assert results[1].is_tradeable is True

    async def test_unresolved_isin(self):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"data": [{"ticker": "IWDA", "exchCode": "NA"}]},
            {"warning": "No match found"},  # no data key
        ]
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock()
        client.post = AsyncMock(return_value=mock_response)

        results = await resolve_isin_to_ticker_batch(
            ["IE00B4L5Y983", "XX0000000000"],
            http_client=client,
        )

        assert results[0].is_tradeable is True
        assert results[1].is_tradeable is False
        assert results[1].resolved_via == "unresolved"

    async def test_http_error_returns_all_unresolved(self):
        client = AsyncMock()
        client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        results = await resolve_isin_to_ticker_batch(
            ["IE00B4L5Y983"],
            http_client=client,
        )

        assert len(results) == 1
        assert results[0].is_tradeable is False
        assert results[0].resolved_via == "unresolved"

    async def test_mismatched_response_length(self):
        mock_response = MagicMock()
        mock_response.json.return_value = [{"data": [{"ticker": "IWDA", "exchCode": "NA"}]}]
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock()
        client.post = AsyncMock(return_value=mock_response)

        results = await resolve_isin_to_ticker_batch(
            ["IE00B4L5Y983", "IE00B3RBWM25"],  # 2 ISINs
            http_client=client,
        )

        # Mismatched length → all unresolved
        assert len(results) == 2
        assert all(r.resolved_via == "unresolved" for r in results)

    async def test_batch_size_exceeded_raises(self):
        client = AsyncMock()
        with pytest.raises(ValueError, match="exceeds limit"):
            await resolve_isin_to_ticker_batch(
                ["ISIN"] * (OPENFIGI_BATCH_SIZE + 1),
                http_client=client,
            )

    async def test_api_key_sent_in_header(self):
        mock_response = MagicMock()
        mock_response.json.return_value = [{"data": [{"ticker": "T", "exchCode": "US"}]}]
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock()
        client.post = AsyncMock(return_value=mock_response)

        await resolve_isin_to_ticker_batch(
            ["IE00B4L5Y983"],
            http_client=client,
            api_key="test-key-123",
        )

        call_kwargs = client.post.call_args
        headers = call_kwargs[1].get("headers") or call_kwargs.kwargs.get("headers", {})
        assert headers.get("X-OPENFIGI-APIKEY") == "test-key-123"

    async def test_empty_data_array(self):
        mock_response = MagicMock()
        mock_response.json.return_value = [{"data": []}]
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock()
        client.post = AsyncMock(return_value=mock_response)

        results = await resolve_isin_to_ticker_batch(
            ["IE00B4L5Y983"],
            http_client=client,
        )

        assert results[0].is_tradeable is False
        assert results[0].resolved_via == "unresolved"


# ── TickerResolver ───────────────────────────────────────────────────


class TestTickerResolver:
    async def test_resolve_batch_delegates(self):
        mock_results = [
            IsinResolution("IE00B4L5Y983", "IWDA.AS", "NA", "openfigi", True),
        ]

        with patch(
            "data_providers.esma.ticker_resolver.resolve_isin_to_ticker_batch",
            return_value=mock_results,
        ):
            with patch("data_providers.esma.ticker_resolver.check_openfigi_rate"):
                async with TickerResolver(api_key="test") as resolver:
                    results = await resolver.resolve_batch(["IE00B4L5Y983"])
                    assert results == mock_results

    async def test_resolve_all_chunks_batches(self):
        """resolve_all splits ISINs into OPENFIGI_BATCH_SIZE chunks."""
        single_result = IsinResolution("X" * 12, None, None, "unresolved", False)

        batch_count = 0

        async def mock_resolve_batch(isins):
            nonlocal batch_count
            batch_count += 1
            return [single_result] * len(isins)

        with patch("data_providers.esma.ticker_resolver.check_openfigi_rate"):
            async with TickerResolver() as resolver:
                resolver.resolve_batch = mock_resolve_batch  # type: ignore[assignment]

                isins = ["X" * 12] * (OPENFIGI_BATCH_SIZE + 10)
                results = await resolver.resolve_all(isins)

                assert len(results) == OPENFIGI_BATCH_SIZE + 10
                assert batch_count == 2  # split into 2 batches


# ── RegisterService ──────────────────────────────────────────────────


class TestRegisterService:
    async def test_get_total_count(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "response": {"numFound": 42000, "docs": []},
        }
        mock_resp.raise_for_status = MagicMock()

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        with patch("data_providers.esma.register_service.check_esma_rate"):
            svc = RegisterService(http_client=client)
            count = await svc.get_total_count()
            assert count == 42000

    async def test_iter_ucits_funds_single_page(self):
        doc = {
            "funds_lei": "529900KQKMU0OADYYE46",
            "funds_national_name": "Test Fund",
            "funds_manager_nat_code": "MGR001",
            "funds_domicile_cou_code": "IE",
            "funds_legal_framework_name": "UCITS",
        }

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "response": {"numFound": 1, "docs": [doc]},
        }
        mock_resp.raise_for_status = MagicMock()

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        with patch("data_providers.esma.register_service.check_esma_rate"):
            svc = RegisterService(http_client=client, page_size=100)
            funds = []
            async for fund in svc.iter_ucits_funds():
                funds.append(fund)

            assert len(funds) == 1
            assert funds[0].isin == "529900KQKMU0OADYYE46"

    async def test_iter_ucits_funds_max_pages(self):
        doc = {
            "funds_lei": "529900KQKMU0OADYYE46",
            "funds_national_name": "Test Fund",
            "funds_manager_nat_code": "MGR001",
        }

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "response": {"numFound": 10000, "docs": [doc]},
        }
        mock_resp.raise_for_status = MagicMock()

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        with patch("data_providers.esma.register_service.check_esma_rate"):
            svc = RegisterService(http_client=client, page_size=100)
            funds = []
            async for fund in svc.iter_ucits_funds(max_pages=2):
                funds.append(fund)

            # max_pages=2 limits iteration
            assert client.get.call_count == 2

    async def test_iter_stops_on_empty_docs(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "response": {"numFound": 0, "docs": []},
        }
        mock_resp.raise_for_status = MagicMock()

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=mock_resp)

        with patch("data_providers.esma.register_service.check_esma_rate"):
            svc = RegisterService(http_client=client)
            funds = []
            async for fund in svc.iter_ucits_funds():
                funds.append(fund)

            assert len(funds) == 0

    async def test_iter_handles_fetch_error(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        with patch("data_providers.esma.register_service.check_esma_rate"):
            svc = RegisterService(http_client=client)
            funds = []
            async for fund in svc.iter_ucits_funds():
                funds.append(fund)

            assert len(funds) == 0

    async def test_context_manager_external_client_not_closed(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        async with RegisterService(http_client=client) as svc:
            pass  # use and exit

        # External client should NOT be closed
        client.aclose.assert_not_called()

    async def test_context_manager_internal_client_closed(self):
        with patch("data_providers.esma.register_service.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance

            async with RegisterService() as svc:
                pass

            mock_instance.aclose.assert_called_once()
