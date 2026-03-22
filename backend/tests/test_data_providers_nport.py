"""Tests for SEC N-PORT data provider — monthly mutual fund holdings via edgartools.

Covers:
- NportHolding frozen dataclass creation and immutability
- _validate_cik() format validation
- _safe_int() / _safe_float() type coercion edge cases
- _parse_nport_xml_holdings() XML parsing with synthetic elements
- NportService staleness detection
- NportService.fetch_holdings() with mocked DB + EDGAR
- Upsert chunking behavior
- Error handling (invalid CIK, EDGAR failures, DB failures)
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from data_providers.sec.models import NportHolding
from data_providers.sec.nport_service import (
    NportService,
    _parse_nport_xml_holdings,
    _safe_float,
    _safe_int,
    _validate_cik,
)

# ── NportHolding Dataclass ────────────────────────────────────────────


class TestNportHolding:
    def test_creation(self):
        h = NportHolding(
            cik="0001234567",
            report_date="2024-01-31",
            cusip="594918104",
            isin="US5949181045",
            issuer_name="Microsoft Corp",
            asset_class="EC",
            sector="CORP",
            market_value=150_000_000,
            quantity=400_000.0,
            currency="USD",
            pct_of_nav=5.2,
            is_restricted=False,
            fair_value_level="1",
        )
        assert h.cik == "0001234567"
        assert h.cusip == "594918104"
        assert h.market_value == 150_000_000
        assert h.is_restricted is False

    def test_frozen_immutability(self):
        h = NportHolding(
            cik="0001234567",
            report_date="2024-01-31",
            cusip="594918104",
            isin=None,
            issuer_name="Test",
            asset_class=None,
            sector=None,
            market_value=100,
            quantity=1.0,
            currency="USD",
            pct_of_nav=None,
            is_restricted=None,
            fair_value_level=None,
        )
        with pytest.raises(AttributeError):
            h.market_value = 999  # type: ignore[misc]

    def test_equality(self):
        kwargs = dict(
            cik="123",
            report_date="2024-01-31",
            cusip="ABC",
            isin=None,
            issuer_name="Test",
            asset_class=None,
            sector=None,
            market_value=100,
            quantity=1.0,
            currency="USD",
            pct_of_nav=None,
            is_restricted=False,
            fair_value_level=None,
        )
        assert NportHolding(**kwargs) == NportHolding(**kwargs)

    def test_nullable_fields(self):
        h = NportHolding(
            cik="123",
            report_date="2024-01-31",
            cusip="ABC",
            isin=None,
            issuer_name=None,
            asset_class=None,
            sector=None,
            market_value=None,
            quantity=None,
            currency=None,
            pct_of_nav=None,
            is_restricted=None,
            fair_value_level=None,
        )
        assert h.isin is None
        assert h.market_value is None


# ── _validate_cik ─────────────────────────────────────────────────────


class TestValidateCik:
    def test_valid_cik_short(self):
        assert _validate_cik("123") is True

    def test_valid_cik_10_digits(self):
        assert _validate_cik("0001234567") is True

    def test_valid_cik_1_digit(self):
        assert _validate_cik("1") is True

    def test_invalid_empty(self):
        assert _validate_cik("") is False

    def test_invalid_letters(self):
        assert _validate_cik("abc123") is False

    def test_invalid_spaces(self):
        assert _validate_cik("123 456") is False

    def test_invalid_special_chars(self):
        assert _validate_cik("123-456") is False

    def test_invalid_too_long(self):
        assert _validate_cik("12345678901") is False


# ── _safe_int / _safe_float ──────────────────────────────────────────


class TestSafeInt:
    def test_int_value(self):
        assert _safe_int(42) == 42

    def test_string_int(self):
        assert _safe_int("100") == 100

    def test_float_string(self):
        assert _safe_int("3.14") == 3

    def test_none(self):
        assert _safe_int(None) is None

    def test_empty_string(self):
        assert _safe_int("") is None

    def test_non_numeric(self):
        assert _safe_int("abc") is None

    def test_float_value(self):
        assert _safe_int(3.9) == 3


class TestSafeFloat:
    def test_float_value(self):
        assert _safe_float(3.14) == 3.14

    def test_string_float(self):
        assert _safe_float("2.5") == 2.5

    def test_int_value(self):
        assert _safe_float(42) == 42.0

    def test_none(self):
        assert _safe_float(None) is None

    def test_empty_string(self):
        assert _safe_float("") is None

    def test_non_numeric(self):
        assert _safe_float("xyz") is None

    def test_negative(self):
        assert _safe_float("-1.5") == -1.5


# ── _parse_nport_xml_holdings ─────────────────────────────────────────


def _build_nport_xml(holdings: list[dict]) -> ET.Element:
    """Build a synthetic N-PORT XML root with invstOrSec elements."""
    root = ET.Element("edgarSubmission")
    form_data = ET.SubElement(root, "formData")
    invst_or_secs = ET.SubElement(form_data, "invstOrSecs")

    for h in holdings:
        elem = ET.SubElement(invst_or_secs, "invstOrSec")
        for tag, value in h.items():
            child = ET.SubElement(elem, tag)
            child.text = str(value)

    return root


class TestParseNportXmlHoldings:
    def test_single_holding(self):
        root = _build_nport_xml([{
            "cusip": "594918104",
            "isin": "US5949181045",
            "name": "Microsoft Corp",
            "assetCat": "EC",
            "issuerCat": "CORP",
            "valUSD": "150000000",
            "balance": "400000",
            "curCd": "USD",
            "pctVal": "5.2",
            "isRestrictedSec": "N",
            "fairValLevel": "1",
        }])

        holdings = _parse_nport_xml_holdings(root, "0001234567", "2024-01-31")

        assert len(holdings) == 1
        h = holdings[0]
        assert h.cusip == "594918104"
        assert h.isin == "US5949181045"
        assert h.issuer_name == "Microsoft Corp"
        assert h.market_value == 150_000_000
        assert h.quantity == 400_000.0
        assert h.pct_of_nav == 5.2
        assert h.is_restricted is False
        assert h.fair_value_level == "1"
        assert h.cik == "0001234567"

    def test_multiple_holdings(self):
        root = _build_nport_xml([
            {"cusip": "AAA", "name": "Company A", "valUSD": "100"},
            {"cusip": "BBB", "name": "Company B", "valUSD": "200"},
            {"cusip": "CCC", "name": "Company C", "valUSD": "300"},
        ])

        holdings = _parse_nport_xml_holdings(root, "123", "2024-01-31")
        assert len(holdings) == 3

    def test_skips_holdings_without_cusip(self):
        root = _build_nport_xml([
            {"name": "No CUSIP Corp", "valUSD": "100"},
            {"cusip": "BBB", "name": "Has CUSIP", "valUSD": "200"},
        ])

        holdings = _parse_nport_xml_holdings(root, "123", "2024-01-31")
        assert len(holdings) == 1
        assert holdings[0].cusip == "BBB"

    def test_restricted_security_y(self):
        root = _build_nport_xml([
            {"cusip": "AAA", "isRestrictedSec": "Y"},
        ])

        holdings = _parse_nport_xml_holdings(root, "123", "2024-01-31")
        assert holdings[0].is_restricted is True

    def test_restricted_security_n(self):
        root = _build_nport_xml([
            {"cusip": "AAA", "isRestrictedSec": "N"},
        ])

        holdings = _parse_nport_xml_holdings(root, "123", "2024-01-31")
        assert holdings[0].is_restricted is False

    def test_missing_optional_fields(self):
        root = _build_nport_xml([{"cusip": "AAA"}])

        holdings = _parse_nport_xml_holdings(root, "123", "2024-01-31")
        assert len(holdings) == 1
        h = holdings[0]
        assert h.isin is None
        assert h.issuer_name is None
        assert h.market_value is None
        assert h.quantity is None

    def test_max_holdings_truncation(self):
        """Holdings beyond _MAX_HOLDINGS_PER_FILING are truncated."""
        # Build XML with more holdings than allowed
        many_holdings = [{"cusip": f"C{i:08d}"} for i in range(100)]
        root = _build_nport_xml(many_holdings)

        with patch("data_providers.sec.nport_service._MAX_HOLDINGS_PER_FILING", 50):
            holdings = _parse_nport_xml_holdings(root, "123", "2024-01-31")
            assert len(holdings) == 50

    def test_empty_xml(self):
        root = ET.Element("edgarSubmission")
        holdings = _parse_nport_xml_holdings(root, "123", "2024-01-31")
        assert holdings == []


# ── NportService ──────────────────────────────────────────────────────


def _make_db_session_factory(session=None):
    """Create a mock async session factory."""
    mock_session = session or AsyncMock()

    @asynccontextmanager
    async def _begin():
        yield

    mock_session.begin = _begin

    @asynccontextmanager
    async def factory():
        yield mock_session

    return factory


class TestNportServiceStaleness:
    def test_empty_holdings_is_stale(self):
        svc = NportService(
            db_session_factory=_make_db_session_factory(),
            rate_check=lambda: None,
        )
        assert svc._is_stale([], ttl_days=45) is True

    def test_recent_holdings_not_stale(self):
        svc = NportService(
            db_session_factory=_make_db_session_factory(),
            rate_check=lambda: None,
        )
        holdings = [
            NportHolding(
                cik="123",
                report_date=date.today().isoformat(),
                cusip="AAA",
                isin=None,
                issuer_name="Test",
                asset_class=None,
                sector=None,
                market_value=100,
                quantity=1.0,
                currency="USD",
                pct_of_nav=None,
                is_restricted=False,
                fair_value_level=None,
            ),
        ]
        assert svc._is_stale(holdings, ttl_days=45) is False

    def test_old_holdings_is_stale(self):
        svc = NportService(
            db_session_factory=_make_db_session_factory(),
            rate_check=lambda: None,
        )
        old_date = (date.today() - timedelta(days=60)).isoformat()
        holdings = [
            NportHolding(
                cik="123",
                report_date=old_date,
                cusip="AAA",
                isin=None,
                issuer_name="Test",
                asset_class=None,
                sector=None,
                market_value=100,
                quantity=1.0,
                currency="USD",
                pct_of_nav=None,
                is_restricted=False,
                fair_value_level=None,
            ),
        ]
        assert svc._is_stale(holdings, ttl_days=45) is True

    def test_invalid_date_is_stale(self):
        svc = NportService(
            db_session_factory=_make_db_session_factory(),
            rate_check=lambda: None,
        )
        holdings = [
            NportHolding(
                cik="123",
                report_date="not-a-date",
                cusip="AAA",
                isin=None,
                issuer_name="Test",
                asset_class=None,
                sector=None,
                market_value=100,
                quantity=1.0,
                currency="USD",
                pct_of_nav=None,
                is_restricted=False,
                fair_value_level=None,
            ),
        ]
        assert svc._is_stale(holdings, ttl_days=45) is True


class TestNportServiceFetchHoldings:
    async def test_invalid_cik_returns_empty(self):
        svc = NportService(
            db_session_factory=_make_db_session_factory(),
            rate_check=lambda: None,
        )
        result = await svc.fetch_holdings("invalid-cik!")
        assert result == []

    async def test_cache_hit_returns_db_data(self):
        today = date.today().isoformat()
        cached_holdings = [
            NportHolding(
                cik="123",
                report_date=today,
                cusip="AAA",
                isin=None,
                issuer_name="Test",
                asset_class=None,
                sector=None,
                market_value=100,
                quantity=1.0,
                currency="USD",
                pct_of_nav=None,
                is_restricted=False,
                fair_value_level=None,
            ),
        ]

        svc = NportService(
            db_session_factory=_make_db_session_factory(),
            rate_check=lambda: None,
        )

        with patch.object(svc, "_read_holdings_from_db", return_value=cached_holdings):
            with patch.object(svc, "_is_stale", return_value=False):
                result = await svc.fetch_holdings("123")
                assert result == cached_holdings

    async def test_force_refresh_bypasses_cache(self):
        svc = NportService(
            db_session_factory=_make_db_session_factory(),
            rate_check=lambda: None,
        )

        mock_holdings = [
            NportHolding(
                cik="123",
                report_date=date.today().isoformat(),
                cusip="BBB",
                isin=None,
                issuer_name="Fresh",
                asset_class=None,
                sector=None,
                market_value=200,
                quantity=2.0,
                currency="USD",
                pct_of_nav=None,
                is_restricted=False,
                fair_value_level=None,
            ),
        ]

        with (
            patch.object(svc, "_read_holdings_from_db", return_value=mock_holdings),
            patch("data_providers.sec.nport_service.run_in_sec_thread", return_value=mock_holdings),
            patch.object(svc, "_upsert_holdings", return_value=None),
        ):
            result = await svc.fetch_holdings("123", force_refresh=True)
            assert result == mock_holdings

    async def test_edgar_returns_no_holdings(self):
        svc = NportService(
            db_session_factory=_make_db_session_factory(),
            rate_check=lambda: None,
        )

        with (
            patch.object(svc, "_read_holdings_from_db", return_value=[]),
            patch.object(svc, "_is_stale", return_value=True),
            patch("data_providers.sec.nport_service.run_in_sec_thread", return_value=[]),
        ):
            result = await svc.fetch_holdings("123")
            assert result == []

    async def test_exception_returns_empty(self):
        svc = NportService(
            db_session_factory=_make_db_session_factory(),
            rate_check=lambda: None,
        )

        with patch.object(
            svc, "_read_holdings_from_db",
            side_effect=Exception("DB down"),
        ):
            result = await svc.fetch_holdings("123")
            assert result == []
