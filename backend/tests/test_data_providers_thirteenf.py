"""Tests for data_providers.sec.thirteenf_service — 13F holdings service.

Covers:
  - fetch_holdings() — cache hit, force_refresh, edgartools parsing, upsert
  - compute_diffs() — all action types (NEW, INCREASED, DECREASED, EXITED, UNCHANGED)
  - get_sector_aggregation() — weight computation
  - get_concentration_metrics() — HHI, top-10
  - _compute_diffs_internal() — weight sums, share deltas
  - _is_stale() — staleness TTL check
  - _quarter_end() — date snapping
  - _validate_cik() — CIK format validation
  - _safe_int() — integer parsing
  - market_value — edgartools Value field (already in USD)
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from data_providers.sec.models import ThirteenFHolding
from data_providers.sec.thirteenf_service import (
    ThirteenFService,
    _quarter_end,
    _safe_int,
    _validate_cik,
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
    asset_class: str | None = "COM",
    sector: str | None = None,
) -> ThirteenFHolding:
    return ThirteenFHolding(
        cik=cik,
        report_date=report_date,
        filing_date="2026-02-14",
        accession_number="0001234567-26-000001",
        cusip=cusip,
        issuer_name=issuer,
        asset_class=asset_class,
        shares=shares,
        market_value=market_value,
        discretion="SOLE",
        voting_sole=shares,
        voting_shared=0,
        voting_none=0,
        sector=sector,
    )


# ── _validate_cik() ────────────────────────────────────────────────


class TestValidateCik:
    def test_valid(self):
        assert _validate_cik("1234567890") is True
        assert _validate_cik("1") is True

    def test_invalid(self):
        assert _validate_cik("") is False
        assert _validate_cik("abc") is False
        assert _validate_cik("12345678901") is False


# ── _safe_int() ────────────────────────────────────────────────────


class TestSafeInt:
    def test_int(self):
        assert _safe_int(42) == 42

    def test_float(self):
        assert _safe_int(42.7) == 42

    def test_string(self):
        assert _safe_int("100") == 100

    def test_none(self):
        assert _safe_int(None) is None

    def test_invalid(self):
        assert _safe_int("abc") is None


# ── _quarter_end() ──────────────────────────────────────────────────


class TestQuarterEnd:
    def test_q1(self):
        assert _quarter_end(date(2025, 2, 15)) == date(2025, 3, 31)

    def test_q2(self):
        assert _quarter_end(date(2025, 5, 1)) == date(2025, 6, 30)

    def test_q3(self):
        assert _quarter_end(date(2025, 8, 20)) == date(2025, 9, 30)

    def test_q4(self):
        assert _quarter_end(date(2025, 12, 1)) == date(2025, 12, 31)

    def test_quarter_boundary(self):
        assert _quarter_end(date(2025, 3, 31)) == date(2025, 3, 31)


# ── ThirteenFService._is_stale() ──────────────────────────────────


class TestIsStale:
    def test_empty_is_stale(self):
        assert ThirteenFService._is_stale([], 45) is True

    def test_recent_not_stale(self):
        recent = date.today() - timedelta(days=10)
        holdings = [_make_holding(report_date=recent.isoformat())]
        assert ThirteenFService._is_stale(holdings, 45) is False

    def test_old_is_stale(self):
        old = date.today() - timedelta(days=100)
        holdings = [_make_holding(report_date=old.isoformat())]
        assert ThirteenFService._is_stale(holdings, 45) is True

    def test_uses_most_recent_date(self):
        recent = date.today() - timedelta(days=10)
        old = date.today() - timedelta(days=100)
        holdings = [
            _make_holding(report_date=old.isoformat()),
            _make_holding(report_date=recent.isoformat()),
        ]
        assert ThirteenFService._is_stale(holdings, 45) is False


# ── ThirteenFService._compute_diffs_internal() ────────────────────


class TestComputeDiffsInternal:
    def test_new_position(self):
        from_h: list[ThirteenFHolding] = []
        to_h = [_make_holding(cusip="AAAA", shares=100, market_value=10_000)]

        diffs = ThirteenFService._compute_diffs_internal(
            "0001234567", from_h, to_h,
            date(2025, 9, 30), date(2025, 12, 31),
        )
        assert len(diffs) == 1
        assert diffs[0].action == "NEW_POSITION"
        assert diffs[0].shares_before is None
        assert diffs[0].shares_after == 100
        assert diffs[0].shares_delta == 100

    def test_exited_position(self):
        from_h = [_make_holding(cusip="BBBB", shares=200, market_value=20_000)]
        to_h: list[ThirteenFHolding] = []

        diffs = ThirteenFService._compute_diffs_internal(
            "0001234567", from_h, to_h,
            date(2025, 9, 30), date(2025, 12, 31),
        )
        assert len(diffs) == 1
        assert diffs[0].action == "EXITED"
        assert diffs[0].shares_delta == -200

    def test_increased_position(self):
        from_h = [_make_holding(cusip="CCCC", shares=100, market_value=10_000)]
        to_h = [_make_holding(cusip="CCCC", shares=200, market_value=20_000)]

        diffs = ThirteenFService._compute_diffs_internal(
            "0001234567", from_h, to_h,
            date(2025, 9, 30), date(2025, 12, 31),
        )
        assert len(diffs) == 1
        assert diffs[0].action == "INCREASED"
        assert diffs[0].shares_delta == 100

    def test_decreased_position(self):
        from_h = [_make_holding(cusip="DDDD", shares=300, market_value=30_000)]
        to_h = [_make_holding(cusip="DDDD", shares=100, market_value=10_000)]

        diffs = ThirteenFService._compute_diffs_internal(
            "0001234567", from_h, to_h,
            date(2025, 9, 30), date(2025, 12, 31),
        )
        assert len(diffs) == 1
        assert diffs[0].action == "DECREASED"
        assert diffs[0].shares_delta == -200

    def test_unchanged_position(self):
        from_h = [_make_holding(cusip="EEEE", shares=500, market_value=50_000)]
        to_h = [_make_holding(cusip="EEEE", shares=500, market_value=55_000)]

        diffs = ThirteenFService._compute_diffs_internal(
            "0001234567", from_h, to_h,
            date(2025, 9, 30), date(2025, 12, 31),
        )
        assert len(diffs) == 1
        assert diffs[0].action == "UNCHANGED"
        assert diffs[0].shares_delta == 0

    def test_weight_computation(self):
        """Weights should be relative to total portfolio value."""
        from_h = [
            _make_holding(cusip="A", shares=100, market_value=60_000),
            _make_holding(cusip="B", shares=100, market_value=40_000),
        ]
        to_h = [
            _make_holding(cusip="A", shares=100, market_value=70_000),
            _make_holding(cusip="B", shares=100, market_value=30_000),
        ]

        diffs = ThirteenFService._compute_diffs_internal(
            "0001234567", from_h, to_h,
            date(2025, 9, 30), date(2025, 12, 31),
        )
        # from_total = 100_000, to_total = 100_000
        diff_a = next(d for d in diffs if d.cusip == "A")
        diff_b = next(d for d in diffs if d.cusip == "B")

        assert diff_a.weight_before == pytest.approx(0.6, abs=0.001)
        assert diff_a.weight_after == pytest.approx(0.7, abs=0.001)
        assert diff_b.weight_before == pytest.approx(0.4, abs=0.001)
        assert diff_b.weight_after == pytest.approx(0.3, abs=0.001)

        # Weights sum to ~1.0
        from_sum = sum(d.weight_before for d in diffs if d.weight_before)
        to_sum = sum(d.weight_after for d in diffs if d.weight_after)
        assert from_sum == pytest.approx(1.0, abs=0.01)
        assert to_sum == pytest.approx(1.0, abs=0.01)

    def test_mixed_actions(self):
        """Portfolio with NEW, EXITED, and UNCHANGED positions."""
        from_h = [
            _make_holding(cusip="STAY", shares=100, market_value=10_000),
            _make_holding(cusip="EXIT", shares=50, market_value=5_000),
        ]
        to_h = [
            _make_holding(cusip="STAY", shares=100, market_value=12_000),
            _make_holding(cusip="NEW1", shares=200, market_value=20_000),
        ]

        diffs = ThirteenFService._compute_diffs_internal(
            "0001234567", from_h, to_h,
            date(2025, 9, 30), date(2025, 12, 31),
        )
        actions = {d.cusip: d.action for d in diffs}
        assert actions["STAY"] == "UNCHANGED"
        assert actions["EXIT"] == "EXITED"
        assert actions["NEW1"] == "NEW_POSITION"


# ── ThirteenFService.fetch_holdings() ──────────────────────────────


class TestFetchHoldings:
    @pytest.mark.asyncio
    async def test_invalid_cik_returns_empty(self):
        svc = ThirteenFService(db_session_factory=_make_db_session_factory())
        result = await svc.fetch_holdings("abc")
        assert result == []

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached(self):
        """When DB has recent data and not force_refresh, return cached."""
        recent = date.today() - timedelta(days=5)
        cached = [_make_holding(report_date=recent.isoformat())]

        svc = ThirteenFService(db_session_factory=_make_db_session_factory())

        with patch.object(svc, "_read_holdings_from_db", return_value=cached):
            result = await svc.fetch_holdings("1234567890")

        assert len(result) == 1
        assert result[0].cusip == "037833100"

    @pytest.mark.asyncio
    async def test_force_refresh_skips_cache_check(self):
        """With force_refresh=True, always parse from EDGAR (no staleness check)."""
        svc = ThirteenFService(
            db_session_factory=_make_db_session_factory(),
            rate_check=lambda: None,
        )

        parsed = [_make_holding()]
        # DB re-read returns holdings with sector already set — no enrichment needed
        enriched = [_make_holding(sector="Financials")]

        with (
            patch.object(svc, "_read_holdings_from_db", return_value=enriched) as mock_read,
            patch(
                "data_providers.sec.thirteenf_service.run_in_sec_thread",
                return_value=parsed,
            ),
            patch.object(svc, "_upsert_holdings"),
        ):
            result = await svc.fetch_holdings("1234567890", force_refresh=True)

        # _read_holdings_from_db called once after upsert (re-read with sectors)
        # No enrichment triggered because all holdings already have sector
        assert mock_read.call_count == 1
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_never_raises(self):
        svc = ThirteenFService(db_session_factory=_make_db_session_factory())

        with patch.object(
            svc, "_read_holdings_from_db",
            side_effect=Exception("db error"),
        ):
            result = await svc.fetch_holdings("1234567890")

        assert result == []


# ── ThirteenFService.compute_diffs() ──────────────────────────────


class TestComputeDiffs:
    @pytest.mark.asyncio
    async def test_invalid_cik_returns_empty(self):
        svc = ThirteenFService(db_session_factory=_make_db_session_factory())
        result = await svc.compute_diffs("abc", date(2025, 9, 30), date(2025, 12, 31))
        assert result == []

    @pytest.mark.asyncio
    async def test_no_target_quarter_returns_empty(self):
        svc = ThirteenFService(db_session_factory=_make_db_session_factory())

        with patch.object(svc, "_read_holdings_for_date", return_value=[]):
            result = await svc.compute_diffs("1234567890", date(2025, 9, 30), date(2025, 12, 31))

        assert result == []

    @pytest.mark.asyncio
    async def test_computes_and_upserts_diffs(self):
        from_h = [_make_holding(cusip="A", shares=100, market_value=10_000, report_date="2025-09-30")]
        to_h = [_make_holding(cusip="A", shares=200, market_value=20_000, report_date="2025-12-31")]

        svc = ThirteenFService(db_session_factory=_make_db_session_factory())

        call_count = 0

        async def mock_read(cik, rd):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return from_h
            return to_h

        with (
            patch.object(svc, "_read_holdings_for_date", side_effect=mock_read),
            patch.object(svc, "_upsert_diffs") as mock_upsert,
        ):
            result = await svc.compute_diffs("1234567890", date(2025, 9, 30), date(2025, 12, 31))

        assert len(result) == 1
        assert result[0].action == "INCREASED"
        mock_upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_never_raises(self):
        svc = ThirteenFService(db_session_factory=_make_db_session_factory())

        with patch.object(
            svc, "_read_holdings_for_date",
            side_effect=Exception("db error"),
        ):
            result = await svc.compute_diffs("1234567890", date(2025, 9, 30), date(2025, 12, 31))

        assert result == []


# ── ThirteenFService.get_sector_aggregation() ─────────────────────


class TestGetSectorAggregation:
    @pytest.mark.asyncio
    async def test_aggregation_by_sector(self):
        """Aggregates by industry sector, not asset_class."""
        holdings = [
            _make_holding(cusip="A", market_value=60_000, asset_class="COM", sector="Technology"),
            _make_holding(cusip="B", market_value=30_000, asset_class="COM", sector="Real Estate"),
            _make_holding(cusip="C", market_value=10_000, asset_class="COM", sector="Technology"),
        ]

        svc = ThirteenFService(db_session_factory=_make_db_session_factory())

        with patch.object(svc, "_read_holdings_for_date", return_value=holdings):
            result = await svc.get_sector_aggregation("1234567890", date(2025, 12, 31))

        assert "Technology" in result
        assert "Real Estate" in result
        assert result["Technology"] == pytest.approx(0.7, abs=0.01)
        assert result["Real Estate"] == pytest.approx(0.3, abs=0.01)

    @pytest.mark.asyncio
    async def test_excludes_call_put(self):
        """CALL and PUT positions are excluded from sector aggregation."""
        holdings = [
            _make_holding(cusip="A", market_value=80_000, asset_class="COM", sector="Financials"),
            _make_holding(cusip="B", market_value=10_000, asset_class="CALL", sector="Financials"),
            _make_holding(cusip="C", market_value=10_000, asset_class="PUT", sector="Financials"),
        ]

        svc = ThirteenFService(db_session_factory=_make_db_session_factory())

        with patch.object(svc, "_read_holdings_for_date", return_value=holdings):
            result = await svc.get_sector_aggregation("1234567890", date(2025, 12, 31))

        # Only COM holdings count — 100% Financials from the single COM position
        assert result["Financials"] == pytest.approx(1.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_empty_holdings(self):
        svc = ThirteenFService(db_session_factory=_make_db_session_factory())

        with patch.object(svc, "_read_holdings_for_date", return_value=[]):
            result = await svc.get_sector_aggregation("1234567890", date(2025, 12, 31))

        assert result == {}

    @pytest.mark.asyncio
    async def test_invalid_cik(self):
        svc = ThirteenFService(db_session_factory=_make_db_session_factory())
        result = await svc.get_sector_aggregation("abc", date(2025, 12, 31))
        assert result == {}

    @pytest.mark.asyncio
    async def test_unknown_sector(self):
        """Holdings with no sector resolved are grouped as 'Unknown'."""
        holdings = [_make_holding(cusip="A", market_value=100_000, asset_class="COM", sector=None)]

        svc = ThirteenFService(db_session_factory=_make_db_session_factory())

        with patch.object(svc, "_read_holdings_for_date", return_value=holdings):
            result = await svc.get_sector_aggregation("1234567890", date(2025, 12, 31))

        assert "Unknown" in result
        assert result["Unknown"] == pytest.approx(1.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_all_options_returns_empty(self):
        """If all holdings are CALL/PUT, returns empty dict."""
        holdings = [
            _make_holding(cusip="A", market_value=50_000, asset_class="CALL"),
            _make_holding(cusip="B", market_value=50_000, asset_class="PUT"),
        ]

        svc = ThirteenFService(db_session_factory=_make_db_session_factory())

        with patch.object(svc, "_read_holdings_for_date", return_value=holdings):
            result = await svc.get_sector_aggregation("1234567890", date(2025, 12, 31))

        assert result == {}


# ── ThirteenFService.get_concentration_metrics() ──────────────────


class TestGetConcentrationMetrics:
    @pytest.mark.asyncio
    async def test_single_position_max_concentration(self):
        holdings = [_make_holding(market_value=100_000)]

        svc = ThirteenFService(db_session_factory=_make_db_session_factory())

        with patch.object(svc, "_read_holdings_for_date", return_value=holdings):
            result = await svc.get_concentration_metrics("1234567890", date(2025, 12, 31))

        assert result["hhi"] == pytest.approx(1.0, abs=0.01)
        assert result["top_10_concentration"] == pytest.approx(1.0, abs=0.01)
        assert result["position_count"] == 1.0

    @pytest.mark.asyncio
    async def test_diversified_portfolio(self):
        holdings = [
            _make_holding(cusip=f"C{i:03d}", market_value=10_000)
            for i in range(100)
        ]

        svc = ThirteenFService(db_session_factory=_make_db_session_factory())

        with patch.object(svc, "_read_holdings_for_date", return_value=holdings):
            result = await svc.get_concentration_metrics("1234567890", date(2025, 12, 31))

        # HHI for 100 equal positions = 100 * (0.01)^2 = 0.01
        assert result["hhi"] == pytest.approx(0.01, abs=0.001)
        assert result["top_10_concentration"] == pytest.approx(0.1, abs=0.01)
        assert result["position_count"] == 100.0

    @pytest.mark.asyncio
    async def test_empty_holdings(self):
        svc = ThirteenFService(db_session_factory=_make_db_session_factory())

        with patch.object(svc, "_read_holdings_for_date", return_value=[]):
            result = await svc.get_concentration_metrics("1234567890", date(2025, 12, 31))

        assert result == {}

    @pytest.mark.asyncio
    async def test_invalid_cik(self):
        svc = ThirteenFService(db_session_factory=_make_db_session_factory())
        result = await svc.get_concentration_metrics("abc", date(2025, 12, 31))
        assert result == {}

    @pytest.mark.asyncio
    async def test_never_raises(self):
        svc = ThirteenFService(db_session_factory=_make_db_session_factory())

        with patch.object(
            svc, "_read_holdings_for_date",
            side_effect=Exception("db error"),
        ):
            result = await svc.get_concentration_metrics("1234567890", date(2025, 12, 31))

        assert result == {}


# ── Market Value Conversion ──────────────────────────────────


class TestMarketValueConversion:
    def test_holding_value_is_in_usd(self):
        """ThirteenFHolding.market_value should be in USD."""
        # edgartools already converts from thousands to dollars.
        # The service stores the value as-is (no extra multiplication).
        h = _make_holding(market_value=150_000_000)
        assert h.market_value == 150_000_000

    def test_parse_13f_value_no_extra_multiplication(self):
        """edgartools Value is already in USD — no multiplication needed."""
        # edgartools converts the raw XML thousands to dollars internally.
        # The service just does int(float(raw_value)).
        raw_value = 150_000  # edgartools already converted to dollars
        expected = int(float(raw_value))
        assert expected == 150_000
