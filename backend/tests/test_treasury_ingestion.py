"""Tests for treasury_ingestion worker and DB reader functions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from quant_engine.fiscal_data_service import (
    AuctionResult,
    DebtSnapshot,
    ExchangeRate,
    InterestExpense,
    TreasuryRate,
    get_treasury_auctions_from_db,
    get_treasury_debt_from_db,
    get_treasury_rates_from_db,
)

# ═══════════════════════════════════════════════════════════════════════════
#  Model tests
# ═══════════════════════════════════════════════════════════════════════════


class TestTreasuryDataModel:
    """Validate ORM model structure."""

    def test_table_name(self) -> None:
        from app.shared.models import TreasuryData
        assert TreasuryData.__tablename__ == "treasury_data"

    def test_primary_key_columns(self) -> None:
        from app.shared.models import TreasuryData
        pk_cols = [c.name for c in TreasuryData.__table__.primary_key.columns]
        assert "obs_date" in pk_cols
        assert "series_id" in pk_cols

    def test_source_default(self) -> None:
        from app.shared.models import TreasuryData
        col = TreasuryData.__table__.c.source
        assert col.server_default is not None


# ═══════════════════════════════════════════════════════════════════════════
#  Worker conversion tests
# ═══════════════════════════════════════════════════════════════════════════


class TestTreasuryRowConversion:
    """Test dataclass → upsert dict conversion helpers."""

    def test_rates_to_rows(self) -> None:
        from app.domains.wealth.workers.treasury_ingestion import _rates_to_rows

        rates = [
            TreasuryRate(
                record_date="2026-03-01",
                security_desc="Treasury Bills",
                avg_interest_rate_amt=4.25,
            ),
            TreasuryRate(
                record_date="2026-03-01",
                security_desc="Treasury Notes",
                avg_interest_rate_amt=3.50,
            ),
        ]
        rows = _rates_to_rows(rates)
        assert len(rows) == 2
        assert rows[0]["series_id"] == "RATE_TREASURY_BILLS"
        assert rows[0]["value"] == Decimal("4.25")
        assert rows[0]["obs_date"] == date(2026, 3, 1)

    def test_rates_skip_none_value(self) -> None:
        from app.domains.wealth.workers.treasury_ingestion import _rates_to_rows

        rates = [
            TreasuryRate(record_date="2026-03-01", security_desc="Bills", avg_interest_rate_amt=float("nan")),
        ]
        rows = _rates_to_rows(rates)
        # NaN → Decimal("NaN") is valid, no crash expected
        assert isinstance(rows, list)

    def test_debt_to_rows(self) -> None:
        from app.domains.wealth.workers.treasury_ingestion import _debt_to_rows

        snapshots = [
            DebtSnapshot(
                record_date="2026-03-15",
                tot_pub_debt_out_amt=35_000_000_000_000.0,
                intragov_hold_amt=7_000_000_000_000.0,
                debt_held_public_amt=28_000_000_000_000.0,
            ),
        ]
        rows = _debt_to_rows(snapshots)
        assert len(rows) == 3
        series_ids = {r["series_id"] for r in rows}
        assert "DEBT_TOTAL_PUBLIC" in series_ids
        assert "DEBT_INTRAGOV" in series_ids
        assert "DEBT_HELD_PUBLIC" in series_ids

    def test_auctions_to_rows(self) -> None:
        from app.domains.wealth.workers.treasury_ingestion import _auctions_to_rows

        auctions = [
            AuctionResult(
                auction_date="2026-03-10",
                security_type="Bill",
                security_term="4-Week",
                high_yield=4.15,
                bid_to_cover_ratio=2.8,
            ),
        ]
        rows = _auctions_to_rows(auctions)
        assert len(rows) == 1
        assert rows[0]["series_id"] == "AUCTION_BILL_4-WEEK"
        assert rows[0]["metadata_json"]["bid_to_cover"] == 2.8

    def test_auctions_skip_none_yield(self) -> None:
        from app.domains.wealth.workers.treasury_ingestion import _auctions_to_rows

        auctions = [
            AuctionResult(
                auction_date="2026-03-10",
                security_type="Bill",
                security_term="4-Week",
                high_yield=None,
                bid_to_cover_ratio=2.8,
            ),
        ]
        rows = _auctions_to_rows(auctions)
        assert len(rows) == 0

    def test_fx_to_rows(self) -> None:
        from app.domains.wealth.workers.treasury_ingestion import _fx_to_rows

        rates = [
            ExchangeRate(record_date="2026-03-01", country_currency_desc="Brazil-Real", exchange_rate=5.45),
        ]
        rows = _fx_to_rows(rates)
        assert len(rows) == 1
        assert rows[0]["series_id"] == "FX_BRAZIL_REAL"

    def test_interest_expense_to_rows(self) -> None:
        from app.domains.wealth.workers.treasury_ingestion import _interest_expense_to_rows

        expenses = [
            InterestExpense(
                record_date="2026-02-01",
                expense_catg_desc="Treasury Notes",
                month_expense_amt=50_000_000.0,
                fytd_expense_amt=250_000_000.0,
            ),
        ]
        rows = _interest_expense_to_rows(expenses)
        assert len(rows) == 2
        series_ids = {r["series_id"] for r in rows}
        assert "INTEREST_TREASURY_NOTES_MONTH" in series_ids
        assert "INTEREST_TREASURY_NOTES_FYTD" in series_ids

    def test_invalid_date_skipped(self) -> None:
        from app.domains.wealth.workers.treasury_ingestion import _rates_to_rows

        rates = [
            TreasuryRate(record_date="not-a-date", security_desc="Bills", avg_interest_rate_amt=4.0),
        ]
        rows = _rates_to_rows(rates)
        assert len(rows) == 0


# ═══════════════════════════════════════════════════════════════════════════
#  Worker integration test (mocked I/O)
# ═══════════════════════════════════════════════════════════════════════════


def _make_mock_session(*, lock_acquired: bool = True):
    """Create a mock async session with proper context manager protocol."""
    mock_db = AsyncMock()
    call_count = 0

    async def mock_execute(stmt_or_text):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            result = MagicMock()
            result.scalar.return_value = lock_acquired
            return result
        return MagicMock()

    mock_db.execute = mock_execute
    mock_db.commit = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_db)
    ctx.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock(return_value=ctx)
    return factory, mock_db


class TestTreasuryIngestionWorker:
    """Test the worker function with mocked DB and API."""

    @pytest.mark.asyncio
    async def test_lock_held_skips(self) -> None:
        """If advisory lock is held, worker returns skipped."""
        factory, _ = _make_mock_session(lock_acquired=False)

        with patch(
            "app.domains.wealth.workers.treasury_ingestion.async_session",
            factory,
        ):
            from app.domains.wealth.workers.treasury_ingestion import run_treasury_ingestion

            result = await run_treasury_ingestion()

        assert result["status"] == "skipped"
        assert result["reason"] == "lock_held"

    @pytest.mark.asyncio
    async def test_successful_ingestion(self) -> None:
        """Worker fetches, converts, and upserts data."""
        factory, mock_db = _make_mock_session(lock_acquired=True)

        mock_rates = [
            TreasuryRate(record_date="2026-03-01", security_desc="Treasury Bills", avg_interest_rate_amt=4.25),
        ]

        with (
            patch(
                "app.domains.wealth.workers.treasury_ingestion.async_session",
                factory,
            ),
            patch(
                "app.domains.wealth.workers.treasury_ingestion.FiscalDataService",
            ) as MockService,
        ):
            svc = AsyncMock()
            svc.fetch_treasury_rates = AsyncMock(return_value=mock_rates)
            svc.fetch_debt_to_penny = AsyncMock(return_value=[])
            svc.fetch_treasury_auctions = AsyncMock(return_value=[])
            svc.fetch_exchange_rates = AsyncMock(return_value=[])
            svc.fetch_interest_expense = AsyncMock(return_value=[])
            MockService.return_value = svc

            from app.domains.wealth.workers.treasury_ingestion import run_treasury_ingestion

            result = await run_treasury_ingestion(lookback_days=30)

        assert result["status"] == "completed"
        assert result["rows"] == 1
        mock_db.commit.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
#  DB reader function tests
# ═══════════════════════════════════════════════════════════════════════════


class TestTreasuryDbReaders:
    """Test DB reader functions with mocked sessions."""

    @pytest.mark.asyncio
    async def test_get_treasury_rates_from_db(self) -> None:
        mock_row = type("Row", (), {
            "obs_date": date(2026, 3, 1),
            "series_id": "RATE_TREASURY_BILLS",
            "value": Decimal("4.25"),
        })()

        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        rows = await get_treasury_rates_from_db(mock_db, lookback_days=30)
        assert len(rows) == 1
        assert rows[0]["series_id"] == "RATE_TREASURY_BILLS"
        assert rows[0]["value"] == 4.25

    @pytest.mark.asyncio
    async def test_get_treasury_debt_from_db(self) -> None:
        mock_row = type("Row", (), {
            "obs_date": date(2026, 3, 15),
            "series_id": "DEBT_TOTAL_PUBLIC",
            "value": Decimal(35000000000000),
        })()

        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        rows = await get_treasury_debt_from_db(mock_db, lookback_days=30)
        assert len(rows) == 1
        assert rows[0]["series_id"] == "DEBT_TOTAL_PUBLIC"

    @pytest.mark.asyncio
    async def test_get_treasury_auctions_from_db(self) -> None:
        mock_row = type("Row", (), {
            "obs_date": date(2026, 3, 10),
            "series_id": "AUCTION_BILL_4_WEEK",
            "value": Decimal("4.15"),
            "metadata_json": {"bid_to_cover": 2.8},
        })()

        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        rows = await get_treasury_auctions_from_db(mock_db, lookback_days=30)
        assert len(rows) == 1
        assert rows[0]["metadata"]["bid_to_cover"] == 2.8
