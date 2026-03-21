"""Tests for data_providers.sec.institutional_service — 13F reverse lookup.

Covers:
  - discover_institutional_filers() — EFTS search, keyword matching, filer_type classification
  - fetch_allocations() — delegates to ThirteenFService, maps holdings, upsert
  - find_investors_in_manager() — 3-way coverage detection (FOUND, PUBLIC_SECURITIES_NO_HOLDERS, NO_PUBLIC_SECURITIES)
  - feeder→master look-through heuristic
  - _classify_filer_type() — regex patterns, ambiguous warning
  - _validate_cik() — CIK format validation
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data_providers.sec.institutional_service import (
    InstitutionalService,
    _classify_filer_type,
    _validate_cik,
)
from data_providers.sec.models import (
    CikResolution,
    CoverageType,
    InstitutionalAllocation,
    InstitutionalOwnershipResult,
    ThirteenFHolding,
)

# ── Helpers ────────────────────────────────────────────────────────


def _make_db_session_factory(session: AsyncMock | None = None) -> Any:
    mock_session = session or AsyncMock()

    @asynccontextmanager
    async def factory():
        yield mock_session

    return factory


def _make_holding(
    cusip: str = "037833100",
    issuer: str = "Apple Inc",
    shares: int = 1000,
    market_value: int = 150_000,
    cik: str = "0001234567",
    report_date: str = "2025-12-31",
) -> ThirteenFHolding:
    return ThirteenFHolding(
        cik=cik,
        report_date=report_date,
        filing_date="2026-02-14",
        accession_number="0001234567-26-000001",
        cusip=cusip,
        issuer_name=issuer,
        asset_class="COM",
        shares=shares,
        market_value=market_value,
        discretion="SOLE",
        voting_sole=shares,
        voting_shared=0,
        voting_none=0,
    )


def _make_thirteenf_mock() -> AsyncMock:
    """Create a mock ThirteenFService."""
    mock = AsyncMock()
    mock.fetch_holdings = AsyncMock(return_value=[])
    return mock


# ── _validate_cik() ────────────────────────────────────────────────


class TestValidateCik:
    def test_valid(self):
        assert _validate_cik("1234567890") is True
        assert _validate_cik("1") is True

    def test_invalid(self):
        assert _validate_cik("") is False
        assert _validate_cik("abc") is False
        assert _validate_cik("12345678901") is False


# ── _classify_filer_type() ─────────────────────────────────────────


class TestClassifyFilerType:
    def test_endowment(self):
        assert _classify_filer_type("Harvard Endowment Fund") == "endowment"

    def test_pension(self):
        assert _classify_filer_type("California Public Employees Retirement System") == "pension"

    def test_foundation(self):
        assert _classify_filer_type("Bill & Melinda Gates Foundation") == "foundation"

    def test_sovereign(self):
        assert _classify_filer_type("Abu Dhabi Investment Authority") == "sovereign"

    def test_insurance(self):
        assert _classify_filer_type("MetLife Insurance Company") == "insurance"

    def test_no_match(self):
        assert _classify_filer_type("Blackrock Capital Management") is None

    def test_ambiguous_warns(self):
        """Multiple type matches should log WARNING and return first match."""
        # "Insurance Foundation" matches both insurance and foundation
        with patch("data_providers.sec.institutional_service.logger") as mock_logger:
            result = _classify_filer_type("Insurance Foundation Trust")
            assert result is not None  # Returns first match
            mock_logger.warning.assert_called_once()

    def test_case_insensitive(self):
        assert _classify_filer_type("PENSION FUND") == "pension"
        assert _classify_filer_type("endowment") == "endowment"

    def test_life_matches_insurance(self):
        assert _classify_filer_type("New York Life") == "insurance"

    def test_retirement_matches_pension(self):
        assert _classify_filer_type("Teachers Retirement System") == "pension"


# ── InstitutionalService.discover_institutional_filers() ───────────


class TestDiscoverInstitutionalFilers:
    @pytest.mark.asyncio
    async def test_returns_results(self):
        mock_13f = _make_thirteenf_mock()
        svc = InstitutionalService(
            thirteenf_service=mock_13f,
            db_session_factory=_make_db_session_factory(),
        )

        efts_results = [
            {"cik": "0001234567", "filer_name": "State Pension Fund", "filer_type": "pension"},
            {"cik": "0009876543", "filer_name": "University Endowment", "filer_type": "endowment"},
        ]

        with patch(
            "data_providers.sec.institutional_service.run_in_sec_thread",
            return_value=efts_results,
        ):
            results = await svc.discover_institutional_filers()

        assert len(results) == 2
        assert results[0]["filer_type"] == "pension"

    @pytest.mark.asyncio
    async def test_custom_filer_types(self):
        mock_13f = _make_thirteenf_mock()
        svc = InstitutionalService(
            thirteenf_service=mock_13f,
            db_session_factory=_make_db_session_factory(),
        )

        with patch(
            "data_providers.sec.institutional_service.run_in_sec_thread",
            return_value=[],
        ) as mock_thread:
            results = await svc.discover_institutional_filers(
                filer_types=["sovereign"],
            )

        assert results == []
        # Verify custom keywords were passed
        call_args = mock_thread.call_args
        assert call_args[0][1] == ["sovereign"]  # keywords arg

    @pytest.mark.asyncio
    async def test_never_raises(self):
        mock_13f = _make_thirteenf_mock()
        svc = InstitutionalService(
            thirteenf_service=mock_13f,
            db_session_factory=_make_db_session_factory(),
        )

        with patch(
            "data_providers.sec.institutional_service.run_in_sec_thread",
            side_effect=Exception("network error"),
        ):
            results = await svc.discover_institutional_filers()

        assert results == []


# ── InstitutionalService._search_efts_filers() ────────────────────


class TestSearchEftsFilers:
    def test_parses_hits_and_deduplicates(self):
        mock_13f = _make_thirteenf_mock()
        svc = InstitutionalService(
            thirteenf_service=mock_13f,
            db_session_factory=_make_db_session_factory(),
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "hits": {
                "hits": [
                    {"_source": {"ciks": ["123"], "display_names": ["State Pension Fund (CIK 0000000123)"]}},
                    {"_source": {"ciks": ["123"], "display_names": ["State Pension Fund (CIK 0000000123)"]}},  # duplicate
                    {"_source": {"ciks": ["456"], "display_names": ["University Endowment (CIK 0000000456)"]}},
                ],
            },
        }
        mock_response.raise_for_status = MagicMock()

        with (
            patch("httpx.get", return_value=mock_response),
            patch("data_providers.sec.institutional_service.check_edgar_rate"),
        ):
            results = svc._search_efts_filers(["pension", "endowment"], limit=100)

        assert len(results) == 2  # Deduplicated
        ciks = {r["cik"] for r in results}
        assert len(ciks) == 2

    def test_respects_limit(self):
        mock_13f = _make_thirteenf_mock()
        svc = InstitutionalService(
            thirteenf_service=mock_13f,
            db_session_factory=_make_db_session_factory(),
        )

        hits = [
            {"_source": {"ciks": [str(i)], "display_names": [f"Fund {i} (CIK {str(i).zfill(10)})"]}}
            for i in range(10)
        ]

        mock_response = MagicMock()
        mock_response.json.return_value = {"hits": {"hits": hits}}
        mock_response.raise_for_status = MagicMock()

        with (
            patch("httpx.get", return_value=mock_response),
            patch("data_providers.sec.institutional_service.check_edgar_rate"),
        ):
            results = svc._search_efts_filers(["pension"], limit=3)

        assert len(results) == 3

    def test_skips_missing_fields(self):
        mock_13f = _make_thirteenf_mock()
        svc = InstitutionalService(
            thirteenf_service=mock_13f,
            db_session_factory=_make_db_session_factory(),
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "hits": {
                "hits": [
                    {"_source": {"ciks": [], "display_names": ["No CIK"]}},
                    {"_source": {"ciks": ["123"], "display_names": [""]}},
                    {"_source": {"ciks": ["456"], "display_names": ["Valid Fund (CIK 0000000456)"]}},
                ],
            },
        }
        mock_response.raise_for_status = MagicMock()

        with (
            patch("httpx.get", return_value=mock_response),
            patch("data_providers.sec.institutional_service.check_edgar_rate"),
        ):
            results = svc._search_efts_filers(["pension"], limit=100)

        assert len(results) == 1
        assert results[0]["cik"] == "0000000456"

    def test_classifies_filer_type(self):
        mock_13f = _make_thirteenf_mock()
        svc = InstitutionalService(
            thirteenf_service=mock_13f,
            db_session_factory=_make_db_session_factory(),
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "hits": {
                "hits": [
                    {"_source": {"ciks": ["111"], "display_names": ["California Pension Fund (CIK 0000000111)"]}},
                ],
            },
        }
        mock_response.raise_for_status = MagicMock()

        with (
            patch("httpx.get", return_value=mock_response),
            patch("data_providers.sec.institutional_service.check_edgar_rate"),
        ):
            results = svc._search_efts_filers(["pension"], limit=100)

        assert results[0]["filer_type"] == "pension"


# ── InstitutionalService.fetch_allocations() ───────────────────────


class TestFetchAllocations:
    @pytest.mark.asyncio
    async def test_delegates_to_thirteenf(self):
        holdings = [
            _make_holding(cusip="AAAA", issuer="Apple Inc", shares=100, market_value=15_000),
        ]
        mock_13f = _make_thirteenf_mock()
        mock_13f.fetch_holdings.return_value = holdings

        svc = InstitutionalService(
            thirteenf_service=mock_13f,
            db_session_factory=_make_db_session_factory(),
        )

        with patch.object(svc, "_upsert_allocations"):
            result = await svc.fetch_allocations(
                "1234567890", "Pension Fund", "pension",
            )

        assert len(result) == 1
        assert isinstance(result[0], InstitutionalAllocation)
        assert result[0].filer_cik == "1234567890"
        assert result[0].filer_name == "Pension Fund"
        assert result[0].filer_type == "pension"
        assert result[0].target_cusip == "AAAA"

    @pytest.mark.asyncio
    async def test_no_holdings_returns_empty(self):
        mock_13f = _make_thirteenf_mock()
        mock_13f.fetch_holdings.return_value = []

        svc = InstitutionalService(
            thirteenf_service=mock_13f,
            db_session_factory=_make_db_session_factory(),
        )
        result = await svc.fetch_allocations(
            "1234567890", "Pension Fund", "pension",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_invalid_cik_returns_empty(self):
        mock_13f = _make_thirteenf_mock()
        svc = InstitutionalService(
            thirteenf_service=mock_13f,
            db_session_factory=_make_db_session_factory(),
        )
        result = await svc.fetch_allocations("abc", "Fund", "pension")
        assert result == []

    @pytest.mark.asyncio
    async def test_never_raises(self):
        mock_13f = _make_thirteenf_mock()
        mock_13f.fetch_holdings.side_effect = Exception("edgartools error")

        svc = InstitutionalService(
            thirteenf_service=mock_13f,
            db_session_factory=_make_db_session_factory(),
        )
        result = await svc.fetch_allocations(
            "1234567890", "Pension Fund", "pension",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_upserts_allocations(self):
        holdings = [_make_holding()]
        mock_13f = _make_thirteenf_mock()
        mock_13f.fetch_holdings.return_value = holdings

        svc = InstitutionalService(
            thirteenf_service=mock_13f,
            db_session_factory=_make_db_session_factory(),
        )

        with patch.object(svc, "_upsert_allocations") as mock_upsert:
            await svc.fetch_allocations("1234567890", "Pension Fund", "pension")

        mock_upsert.assert_called_once()
        upserted = mock_upsert.call_args[0][0]
        assert len(upserted) == 1


# ── InstitutionalService.find_investors_in_manager() ───────────────


class TestFindInvestorsInManager:
    @pytest.mark.asyncio
    async def test_invalid_cik(self):
        mock_13f = _make_thirteenf_mock()
        svc = InstitutionalService(
            thirteenf_service=mock_13f,
            db_session_factory=_make_db_session_factory(),
        )
        result = await svc.find_investors_in_manager("abc")
        assert result.coverage == CoverageType.NO_PUBLIC_SECURITIES
        assert "Invalid CIK" in (result.note or "")

    @pytest.mark.asyncio
    async def test_no_public_securities(self):
        """Manager has no 13F holdings → NO_PUBLIC_SECURITIES."""
        mock_13f = _make_thirteenf_mock()
        svc = InstitutionalService(
            thirteenf_service=mock_13f,
            db_session_factory=_make_db_session_factory(),
        )

        with (
            patch.object(svc, "_get_manager_cusips", return_value=set()),
            patch.object(svc, "_try_feeder_master_lookthrough", return_value=None),
        ):
            result = await svc.find_investors_in_manager("1234567890")

        assert result.coverage == CoverageType.NO_PUBLIC_SECURITIES
        assert result.investors == []

    @pytest.mark.asyncio
    async def test_public_securities_no_holders(self):
        """Manager has CUSIPs but no institutional holders → PUBLIC_SECURITIES_NO_HOLDERS."""
        mock_13f = _make_thirteenf_mock()
        svc = InstitutionalService(
            thirteenf_service=mock_13f,
            db_session_factory=_make_db_session_factory(),
        )

        with (
            patch.object(svc, "_get_manager_cusips", return_value={"AAAA", "BBBB"}),
            patch.object(svc, "_query_institutional_holders", return_value=[]),
        ):
            result = await svc.find_investors_in_manager("1234567890")

        assert result.coverage == CoverageType.PUBLIC_SECURITIES_NO_HOLDERS
        assert result.investors == []

    @pytest.mark.asyncio
    async def test_found_investors(self):
        """Manager has CUSIPs and institutional holders → FOUND."""
        mock_13f = _make_thirteenf_mock()
        svc = InstitutionalService(
            thirteenf_service=mock_13f,
            db_session_factory=_make_db_session_factory(),
        )

        allocations = [
            InstitutionalAllocation(
                filer_cik="0009876543",
                filer_name="State Pension Fund",
                filer_type="pension",
                report_date="2025-12-31",
                target_cusip="AAAA",
                target_issuer="Target Corp",
                market_value=50_000_000,
                shares=100_000,
            ),
        ]

        with (
            patch.object(svc, "_get_manager_cusips", return_value={"AAAA"}),
            patch.object(svc, "_query_institutional_holders", return_value=allocations),
        ):
            result = await svc.find_investors_in_manager("1234567890")

        assert result.coverage == CoverageType.FOUND
        assert len(result.investors) == 1
        assert result.investors[0].filer_name == "State Pension Fund"

    @pytest.mark.asyncio
    async def test_never_raises(self):
        mock_13f = _make_thirteenf_mock()
        svc = InstitutionalService(
            thirteenf_service=mock_13f,
            db_session_factory=_make_db_session_factory(),
        )

        with patch.object(
            svc, "_find_investors_internal",
            side_effect=Exception("unexpected"),
        ):
            result = await svc.find_investors_in_manager("1234567890")

        assert result.coverage == CoverageType.NO_PUBLIC_SECURITIES
        assert "Lookup failed" in (result.note or "")


# ── Feeder→Master Look-Through ────────────────────────────────────


class TestFeederMasterLookthrough:
    @pytest.mark.asyncio
    async def test_feeder_resolved_to_master(self):
        """When manager name has feeder keywords, attempt master lookup."""
        mock_13f = _make_thirteenf_mock()
        svc = InstitutionalService(
            thirteenf_service=mock_13f,
            db_session_factory=_make_db_session_factory(),
        )

        allocations = [
            InstitutionalAllocation(
                filer_cik="0009999999",
                filer_name="Big Pension",
                filer_type="pension",
                report_date="2025-12-31",
                target_cusip="MASTER1",
                target_issuer="Master Fund",
                market_value=100_000_000,
                shares=500_000,
            ),
        ]

        with (
            patch.object(svc, "_get_manager_cusips", side_effect=[set(), {"MASTER1"}]),
            patch.object(svc, "_query_institutional_holders", return_value=allocations),
            patch(
                "data_providers.sec.institutional_service.run_in_sec_thread",
                return_value="Blue Owl Offshore Cayman Ltd",
            ),
            patch(
                "data_providers.sec.institutional_service.resolve_cik",
                return_value=CikResolution(
                    cik="0005555555",
                    company_name="Blue Owl Master Fund",
                    method="fuzzy",
                    confidence=0.9,
                ),
            ),
        ):
            result = await svc.find_investors_in_manager("1234567890")

        assert result.coverage == CoverageType.FOUND
        assert len(result.investors) == 1
        assert "master" in (result.note or "").lower() or "Feeder" in (result.note or "")

    @pytest.mark.asyncio
    async def test_feeder_no_master_found(self):
        """Feeder keywords present but CIK resolution fails → NO_PUBLIC_SECURITIES."""
        mock_13f = _make_thirteenf_mock()
        svc = InstitutionalService(
            thirteenf_service=mock_13f,
            db_session_factory=_make_db_session_factory(),
        )

        with (
            patch.object(svc, "_get_manager_cusips", return_value=set()),
            patch(
                "data_providers.sec.institutional_service.run_in_sec_thread",
                return_value="Blue Owl Offshore Ltd",
            ),
            patch(
                "data_providers.sec.institutional_service.resolve_cik",
                return_value=CikResolution(
                    cik=None, company_name=None, method="not_found", confidence=0.0,
                ),
            ),
        ):
            result = await svc.find_investors_in_manager("1234567890")

        assert result.coverage == CoverageType.NO_PUBLIC_SECURITIES

    @pytest.mark.asyncio
    async def test_feeder_same_cik_skipped(self):
        """If master resolves to same CIK as manager, skip look-through."""
        mock_13f = _make_thirteenf_mock()
        svc = InstitutionalService(
            thirteenf_service=mock_13f,
            db_session_factory=_make_db_session_factory(),
        )

        with (
            patch.object(svc, "_get_manager_cusips", return_value=set()),
            patch(
                "data_providers.sec.institutional_service.run_in_sec_thread",
                return_value="Fund Offshore Cayman",
            ),
            patch(
                "data_providers.sec.institutional_service.resolve_cik",
                return_value=CikResolution(
                    cik="1234567890",  # Same as manager_cik
                    company_name="Same Fund",
                    method="fuzzy",
                    confidence=0.9,
                ),
            ),
        ):
            result = await svc.find_investors_in_manager("1234567890")

        assert result.coverage == CoverageType.NO_PUBLIC_SECURITIES

    @pytest.mark.asyncio
    async def test_non_feeder_name_skips_lookthrough(self):
        """Names without feeder keywords → skip look-through."""
        mock_13f = _make_thirteenf_mock()
        svc = InstitutionalService(
            thirteenf_service=mock_13f,
            db_session_factory=_make_db_session_factory(),
        )

        with (
            patch.object(svc, "_get_manager_cusips", return_value=set()),
            patch(
                "data_providers.sec.institutional_service.run_in_sec_thread",
                return_value="Blackstone Capital Partners",  # No feeder keywords
            ),
        ):
            result = await svc.find_investors_in_manager("1234567890")

        assert result.coverage == CoverageType.NO_PUBLIC_SECURITIES

    @pytest.mark.asyncio
    async def test_lookthrough_never_raises(self):
        """Look-through is best-effort — exceptions return None (fall through)."""
        mock_13f = _make_thirteenf_mock()
        svc = InstitutionalService(
            thirteenf_service=mock_13f,
            db_session_factory=_make_db_session_factory(),
        )

        with (
            patch.object(svc, "_get_manager_cusips", return_value=set()),
            patch(
                "data_providers.sec.institutional_service.run_in_sec_thread",
                side_effect=Exception("edgartools crash"),
            ),
        ):
            result = await svc.find_investors_in_manager("1234567890")

        # Should fall through to NO_PUBLIC_SECURITIES, not raise
        assert result.coverage == CoverageType.NO_PUBLIC_SECURITIES


# ── Models Integration ─────────────────────────────────────────────


class TestModelsIntegration:
    def test_coverage_type_enum(self):
        assert CoverageType.FOUND.value == "found"
        assert CoverageType.PUBLIC_SECURITIES_NO_HOLDERS.value == "public_securities_no_holders"
        assert CoverageType.NO_PUBLIC_SECURITIES.value == "no_public_securities"

    def test_institutional_ownership_result_defaults(self):
        r = InstitutionalOwnershipResult(
            manager_cik="0001234567",
            coverage=CoverageType.FOUND,
        )
        assert r.investors == []
        assert r.note is None

    def test_institutional_allocation_frozen(self):
        a = InstitutionalAllocation(
            filer_cik="0001234567",
            filer_name="Test",
            filer_type="pension",
            report_date="2025-12-31",
            target_cusip="AAAA",
            target_issuer="Apple",
            market_value=100_000,
            shares=1000,
        )
        with pytest.raises(AttributeError):
            a.filer_cik = "9999999999"  # type: ignore[misc]
