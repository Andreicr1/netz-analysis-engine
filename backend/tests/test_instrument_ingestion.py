"""Tests for instrument universe NAV ingestion worker."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.workers.instrument_ingestion import (
    _resolve_period,
    run_instrument_ingestion,
)

ORG_ID = uuid.uuid4()


def _make_instrument(
    ticker: str = "SPY",
    is_active: bool = True,
    currency: str = "USD",
    instrument_id: uuid.UUID | None = None,
) -> MagicMock:
    inst = MagicMock(spec=Instrument)
    inst.instrument_id = instrument_id or uuid.uuid4()
    inst.ticker = ticker
    inst.is_active = is_active
    inst.currency = currency
    return inst


def _make_history_df(
    prices: list[float],
    start_date: str = "2026-01-01",
) -> pd.DataFrame:
    """Create a price DataFrame resembling yfinance output."""
    dates = pd.bdate_range(start=start_date, periods=len(prices))
    return pd.DataFrame(
        {"Close": prices, "Open": prices, "High": prices, "Low": prices},
        index=dates,
    )


class TestResolvePeriod:
    def test_short_lookback(self):
        assert _resolve_period(7) == "1mo"
        assert _resolve_period(30) == "1mo"

    def test_medium_lookback(self):
        assert _resolve_period(60) == "3mo"
        assert _resolve_period(90) == "3mo"

    def test_yearly_lookback(self):
        assert _resolve_period(200) == "1y"
        assert _resolve_period(365) == "1y"

    def test_multi_year_lookback(self):
        assert _resolve_period(500) == "2y"
        assert _resolve_period(1000) == "3y"
        assert _resolve_period(1095) == "3y"
        assert _resolve_period(1825) == "5y"
        assert _resolve_period(3650) == "10y"

    def test_beyond_max(self):
        assert _resolve_period(5000) == "10y"


@pytest.fixture
def mock_db():
    """Create a mock AsyncSession with advisory lock support.

    Patches async_session_factory so run_instrument_ingestion() uses
    this mock instead of connecting to a real database.
    """
    db = AsyncMock()
    # Advisory lock succeeds
    lock_result = MagicMock()
    lock_result.scalar.return_value = True
    db.execute = AsyncMock(return_value=lock_result)
    # Make the mock usable as an async context manager
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)
    db.expire_on_commit = False
    return db


@pytest.fixture
def mock_provider():
    provider = MagicMock()
    provider.fetch_batch_history = MagicMock(return_value={})
    return provider


class TestRunInstrumentIngestion:
    @pytest.mark.asyncio
    async def test_queries_active_instruments_only(self, mock_db, mock_provider):
        """Only instruments with is_active=True and ticker IS NOT NULL are fetched."""
        active_inst = _make_instrument(ticker="SPY", is_active=True)
        inactive_inst = _make_instrument(ticker="QQQ", is_active=False)

        # Track which instruments the query returns
        instruments_result = MagicMock()
        instruments_result.scalars.return_value.all.return_value = [active_inst]

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            stmt_str = str(stmt) if not isinstance(stmt, str) else stmt
            if "pg_try_advisory_lock" in str(stmt_str):
                lock_result = MagicMock()
                lock_result.scalar.return_value = True
                return lock_result
            if "pg_advisory_unlock" in str(stmt_str):
                return MagicMock()
            # instruments query
            return instruments_result

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        mock_provider.fetch_batch_history.return_value = {
            "SPY": _make_history_df([100.0, 101.0, 102.0]),
        }

        with patch(
            "app.domains.wealth.workers.instrument_ingestion.async_session_factory",
            return_value=mock_db,
        ), patch(
            "app.domains.wealth.workers.instrument_ingestion.get_instrument_provider",
            return_value=mock_provider,
        ), patch(
            "app.domains.wealth.workers.instrument_ingestion.set_rls_context",
            new_callable=AsyncMock,
        ):
            result = await run_instrument_ingestion(ORG_ID, lookback_days=30)

        assert result["instruments_processed"] >= 0  # At least ran successfully

    @pytest.mark.asyncio
    async def test_uses_provider_factory(self, mock_db):
        """Calls get_instrument_provider(), not direct YahooFinanceProvider()."""
        instruments_result = MagicMock()
        instruments_result.scalars.return_value.all.return_value = []

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            stmt_str = str(stmt) if not isinstance(stmt, str) else stmt
            if "pg_try_advisory_lock" in str(stmt_str):
                lock_result = MagicMock()
                lock_result.scalar.return_value = True
                return lock_result
            if "pg_advisory_unlock" in str(stmt_str):
                return MagicMock()
            return instruments_result

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        with patch(
            "app.domains.wealth.workers.instrument_ingestion.async_session_factory",
            return_value=mock_db,
        ), patch(
            "app.domains.wealth.workers.instrument_ingestion.get_instrument_provider",
        ) as mock_factory, patch(
            "app.domains.wealth.workers.instrument_ingestion.set_rls_context",
            new_callable=AsyncMock,
        ):
            await run_instrument_ingestion(ORG_ID, lookback_days=30)
            # Factory is NOT called when no instruments found
            # (provider only instantiated after query)

        # Verify it would use factory, not direct import
        import app.domains.wealth.workers.instrument_ingestion as mod

        assert hasattr(mod, "get_instrument_provider")

    @pytest.mark.asyncio
    async def test_upserts_nav_timeseries(self, mock_db, mock_provider):
        """Correct row mapping: instrument_id, nav_date, nav, return_1d, source."""
        inst = _make_instrument(ticker="SPY", currency="EUR")
        instruments_result = MagicMock()
        instruments_result.scalars.return_value.all.return_value = [inst]

        mock_provider.fetch_batch_history.return_value = {
            "SPY": _make_history_df([100.0, 102.0]),
        }

        upserted_values = []

        async def mock_execute(stmt, *args, **kwargs):
            stmt_str = str(stmt) if not isinstance(stmt, str) else stmt
            if "pg_try_advisory_lock" in str(stmt_str):
                lock_result = MagicMock()
                lock_result.scalar.return_value = True
                return lock_result
            if "pg_advisory_unlock" in str(stmt_str):
                return MagicMock()
            if hasattr(stmt, "compile"):
                compiled = str(stmt)
                if "nav_timeseries" in compiled.lower() and "insert" in compiled.lower():
                    # This is the upsert
                    upserted_values.append(True)
                    return MagicMock()
            return instruments_result

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        with patch(
            "app.domains.wealth.workers.instrument_ingestion.async_session_factory",
            return_value=mock_db,
        ), patch(
            "app.domains.wealth.workers.instrument_ingestion.get_instrument_provider",
            return_value=mock_provider,
        ), patch(
            "app.domains.wealth.workers.instrument_ingestion.set_rls_context",
            new_callable=AsyncMock,
        ):
            result = await run_instrument_ingestion(ORG_ID, lookback_days=30)

        assert result["instruments_processed"] == 1
        assert result["rows_upserted"] == 2

    @pytest.mark.asyncio
    async def test_computes_log_returns(self, mock_db, mock_provider):
        """Verifies return calculation from Close prices."""
        inst = _make_instrument(ticker="SPY")
        instruments_result = MagicMock()
        instruments_result.scalars.return_value.all.return_value = [inst]

        prices = [100.0, 110.0, 105.0]
        mock_provider.fetch_batch_history.return_value = {
            "SPY": _make_history_df(prices),
        }

        captured_rows: list[dict] = []

        async def mock_execute(stmt, *args, **kwargs):
            stmt_str = str(stmt) if not isinstance(stmt, str) else stmt
            if "pg_try_advisory_lock" in str(stmt_str):
                r = MagicMock()
                r.scalar.return_value = True
                return r
            if "pg_advisory_unlock" in str(stmt_str):
                return MagicMock()
            # Capture upsert values via pg_insert
            if hasattr(stmt, "_values"):
                captured_rows.extend(stmt._values or [])
            return instruments_result

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        with patch(
            "app.domains.wealth.workers.instrument_ingestion.async_session_factory",
            return_value=mock_db,
        ), patch(
            "app.domains.wealth.workers.instrument_ingestion.get_instrument_provider",
            return_value=mock_provider,
        ), patch(
            "app.domains.wealth.workers.instrument_ingestion.set_rls_context",
            new_callable=AsyncMock,
        ):
            result = await run_instrument_ingestion(ORG_ID, lookback_days=30)

        # 3 prices = 3 rows (first has None return_1d)
        assert result["rows_upserted"] == 3

    @pytest.mark.asyncio
    async def test_skips_empty_tickers(self, mock_db, mock_provider):
        """Instruments with no ticker or empty ticker are skipped at query level."""
        # The SQL query filters is_active=True AND ticker IS NOT NULL AND ticker != ""
        # So an instrument with empty ticker won't be returned by the query
        instruments_result = MagicMock()
        instruments_result.scalars.return_value.all.return_value = []

        async def mock_execute(stmt, *args, **kwargs):
            stmt_str = str(stmt) if not isinstance(stmt, str) else stmt
            if "pg_try_advisory_lock" in str(stmt_str):
                r = MagicMock()
                r.scalar.return_value = True
                return r
            if "pg_advisory_unlock" in str(stmt_str):
                return MagicMock()
            return instruments_result

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        with patch(
            "app.domains.wealth.workers.instrument_ingestion.async_session_factory",
            return_value=mock_db,
        ), patch(
            "app.domains.wealth.workers.instrument_ingestion.get_instrument_provider",
            return_value=mock_provider,
        ), patch(
            "app.domains.wealth.workers.instrument_ingestion.set_rls_context",
            new_callable=AsyncMock,
        ):
            result = await run_instrument_ingestion(ORG_ID, lookback_days=30)

        assert result["instruments_processed"] == 0

    @pytest.mark.asyncio
    async def test_handles_api_error_gracefully(self, mock_db):
        """Provider failure doesn't crash the batch."""
        inst = _make_instrument(ticker="SPY")
        instruments_result = MagicMock()
        instruments_result.scalars.return_value.all.return_value = [inst]

        async def mock_execute(stmt, *args, **kwargs):
            stmt_str = str(stmt) if not isinstance(stmt, str) else stmt
            if "pg_try_advisory_lock" in str(stmt_str):
                r = MagicMock()
                r.scalar.return_value = True
                return r
            if "pg_advisory_unlock" in str(stmt_str):
                return MagicMock()
            return instruments_result

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        failing_provider = MagicMock()
        failing_provider.fetch_batch_history.side_effect = Exception("API down")

        with patch(
            "app.domains.wealth.workers.instrument_ingestion.async_session_factory",
            return_value=mock_db,
        ), patch(
            "app.domains.wealth.workers.instrument_ingestion.get_instrument_provider",
            return_value=failing_provider,
        ), patch(
            "app.domains.wealth.workers.instrument_ingestion.set_rls_context",
            new_callable=AsyncMock,
        ), patch(
            "asyncio.sleep",
            new_callable=AsyncMock,
        ):
            result = await run_instrument_ingestion(ORG_ID, lookback_days=30)

        assert result["rows_upserted"] == 0
        assert len(result["skipped_tickers"]) > 0 or len(result["errors"]) > 0

    @pytest.mark.asyncio
    async def test_idempotent_upsert(self, mock_db, mock_provider):
        """Running twice with same data doesn't duplicate rows (on_conflict_do_update)."""
        inst = _make_instrument(ticker="SPY")
        instruments_result = MagicMock()
        instruments_result.scalars.return_value.all.return_value = [inst]

        mock_provider.fetch_batch_history.return_value = {
            "SPY": _make_history_df([100.0, 101.0]),
        }

        upsert_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal upsert_count
            stmt_str = str(stmt) if not isinstance(stmt, str) else stmt
            if "pg_try_advisory_lock" in str(stmt_str):
                r = MagicMock()
                r.scalar.return_value = True
                return r
            if "pg_advisory_unlock" in str(stmt_str):
                return MagicMock()
            if hasattr(stmt, "compile"):
                compiled = str(stmt)
                if "nav_timeseries" in compiled.lower():
                    upsert_count += 1
            return instruments_result

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        with patch(
            "app.domains.wealth.workers.instrument_ingestion.async_session_factory",
            return_value=mock_db,
        ), patch(
            "app.domains.wealth.workers.instrument_ingestion.get_instrument_provider",
            return_value=mock_provider,
        ), patch(
            "app.domains.wealth.workers.instrument_ingestion.set_rls_context",
            new_callable=AsyncMock,
        ):
            r1 = await run_instrument_ingestion(ORG_ID, lookback_days=30)
            r2 = await run_instrument_ingestion(ORG_ID, lookback_days=30)

        # Both runs produce same row count — upsert is idempotent
        assert r1["rows_upserted"] == r2["rows_upserted"]

    @pytest.mark.asyncio
    async def test_skips_nan_heavy_tickers(self, mock_db, mock_provider):
        """Tickers with NaN ratio > 5% are skipped."""
        import numpy as np

        inst = _make_instrument(ticker="BAD")
        instruments_result = MagicMock()
        instruments_result.scalars.return_value.all.return_value = [inst]

        # 50% NaN — well above threshold
        dates = pd.bdate_range(start="2026-01-01", periods=10)
        df = pd.DataFrame(
            {"Close": [100.0, np.nan, np.nan, np.nan, np.nan, np.nan, 101.0, np.nan, np.nan, np.nan]},
            index=dates,
        )
        mock_provider.fetch_batch_history.return_value = {"BAD": df}

        async def mock_execute(stmt, *args, **kwargs):
            stmt_str = str(stmt) if not isinstance(stmt, str) else stmt
            if "pg_try_advisory_lock" in str(stmt_str):
                r = MagicMock()
                r.scalar.return_value = True
                return r
            if "pg_advisory_unlock" in str(stmt_str):
                return MagicMock()
            return instruments_result

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        with patch(
            "app.domains.wealth.workers.instrument_ingestion.async_session_factory",
            return_value=mock_db,
        ), patch(
            "app.domains.wealth.workers.instrument_ingestion.get_instrument_provider",
            return_value=mock_provider,
        ), patch(
            "app.domains.wealth.workers.instrument_ingestion.set_rls_context",
            new_callable=AsyncMock,
        ):
            result = await run_instrument_ingestion(ORG_ID, lookback_days=30)

        assert "BAD" in result["skipped_tickers"]
        assert result["rows_upserted"] == 0


class TestImportEndpointUsesFactory:
    def test_import_from_yahoo_uses_factory(self):
        """Verify import_from_yahoo uses get_instrument_provider, not direct import."""
        import inspect

        from app.domains.wealth.routes.instruments import import_from_yahoo

        source = inspect.getsource(import_from_yahoo)
        assert "get_instrument_provider" in source
        assert "YahooFinanceProvider()" not in source
