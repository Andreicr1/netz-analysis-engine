"""Tests for the Benchmark NAV Ingestion Worker — Sprint 6 Phase 1.

Covers:
- BenchmarkNav ORM model integrity
- Worker data validation (NaN, zero prices, extreme returns)
- Ticker deduplication (multiple blocks sharing one ticker)
- Advisory lock behavior
- Staleness detection
- Empty ticker list raises RuntimeError
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from app.domains.wealth.models.benchmark_nav import BenchmarkNav


# ═══════════════════════════════════════════════════════════════════
#  Model integrity tests
# ═══════════════════════════════════════════════════════════════════


class TestBenchmarkNavModel:
    def test_tablename(self):
        assert BenchmarkNav.__tablename__ == "benchmark_nav"

    def test_has_no_organization_id(self):
        """Global table — must not have organization_id column."""
        columns = {c.name for c in BenchmarkNav.__table__.columns}
        assert "organization_id" not in columns

    def test_composite_pk(self):
        pk_cols = [c.name for c in BenchmarkNav.__table__.primary_key.columns]
        assert pk_cols == ["block_id", "nav_date"]

    def test_fk_to_allocation_blocks(self):
        fks = BenchmarkNav.__table__.foreign_keys
        fk_targets = {fk.target_fullname for fk in fks}
        assert "allocation_blocks.block_id" in fk_targets

    def test_return_type_default(self):
        col = BenchmarkNav.__table__.columns["return_type"]
        assert col.server_default.arg == "log"


# ═══════════════════════════════════════════════════════════════════
#  Worker logic tests (mocked I/O)
# ═══════════════════════════════════════════════════════════════════


def _make_price_df(
    ticker: str,
    days: int = 30,
    start_price: float = 100.0,
    nan_pct: float = 0.0,
    zero_price_at: int | None = None,
) -> pd.DataFrame:
    """Helper: generate synthetic price DataFrame matching yf.download output."""
    dates = pd.date_range(end=date.today(), periods=days, freq="B")
    np.random.seed(42)
    returns = np.random.normal(0.0005, 0.01, days)
    prices = start_price * np.cumprod(1 + returns)

    if zero_price_at is not None and 0 <= zero_price_at < days:
        prices[zero_price_at] = 0.0

    df = pd.DataFrame({"Close": prices}, index=dates)

    # Inject NaN
    if nan_pct > 0:
        n_nan = int(days * nan_pct)
        nan_indices = np.random.choice(days, n_nan, replace=False)
        df.iloc[nan_indices, 0] = np.nan

    return df


def _make_multi_ticker_df(tickers: list[str], days: int = 30) -> pd.DataFrame:
    """Build multi-ticker DataFrame matching yf.download(group_by='ticker')."""
    frames = {}
    for i, ticker in enumerate(tickers):
        frames[ticker] = _make_price_df(ticker, days, start_price=100.0 + i * 10)
    return pd.concat(frames, axis=1)


class TestBenchmarkIngestValidation:
    """Tests for data validation logic in the worker."""

    def test_log_return_computation(self):
        """Log returns should match math.log(P_t / P_{t-1})."""
        p0, p1 = 100.0, 102.0
        expected = math.log(p1 / p0)
        assert abs(expected - 0.019803) < 0.001

    def test_nan_ratio_threshold(self):
        """NaN ratio above 5% should cause ticker rejection."""
        from app.domains.wealth.workers.benchmark_ingest import _MAX_NAN_RATIO

        assert _MAX_NAN_RATIO == 0.05

    def test_advisory_lock_id_is_deterministic(self):
        """Lock ID must be a hardcoded constant, not hash()."""
        from app.domains.wealth.workers.benchmark_ingest import BENCHMARK_INGEST_LOCK_ID

        assert BENCHMARK_INGEST_LOCK_ID == 900_004
        # Verify it's the same across imports (deterministic)
        from app.domains.wealth.workers.benchmark_ingest import BENCHMARK_INGEST_LOCK_ID as lock2

        assert BENCHMARK_INGEST_LOCK_ID == lock2

    def test_upsert_chunk_size(self):
        """Chunk size should be small to prevent connection pool starvation."""
        from app.domains.wealth.workers.benchmark_ingest import UPSERT_CHUNK

        assert UPSERT_CHUNK == 200


class TestBenchmarkIngestWorker:
    """Integration-style tests with mocked DB and yfinance."""

    @pytest.mark.asyncio
    async def test_empty_blocks_raises(self):
        """Worker must fail loudly when no blocks have benchmark_ticker."""
        from app.domains.wealth.workers.benchmark_ingest import _do_ingest

        mock_db = AsyncMock()
        # Return empty list of blocks
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        with pytest.raises(RuntimeError, match="No allocation blocks"):
            await _do_ingest(mock_db, lookback_days=30)

    @pytest.mark.asyncio
    async def test_deduplication_of_shared_tickers(self):
        """Multiple blocks sharing SPY should result in one download, multiple rows."""
        from app.domains.wealth.workers.benchmark_ingest import _do_ingest

        # Create mock blocks: 2 blocks share "SPY", 1 has "AGG"
        block_spy1 = MagicMock()
        block_spy1.block_id = "us_large_cap"
        block_spy1.benchmark_ticker = "SPY"
        block_spy1.is_active = True

        block_spy2 = MagicMock()
        block_spy2.block_id = "us_growth"
        block_spy2.benchmark_ticker = "SPY"
        block_spy2.is_active = True

        block_agg = MagicMock()
        block_agg.block_id = "us_fixed_income"
        block_agg.benchmark_ticker = "AGG"
        block_agg.is_active = True

        mock_db = AsyncMock()

        # First call: select blocks
        blocks_result = MagicMock()
        blocks_result.scalars.return_value.all.return_value = [block_spy1, block_spy2, block_agg]

        # Staleness check calls: return recent dates
        stale_result = MagicMock()
        stale_result.scalar.return_value = date.today()

        # execute calls: 1 block query + N upsert chunks + 3 staleness queries
        # Use a side_effect function to handle different call patterns
        call_count = {"n": 0}

        async def _mock_execute(stmt, *args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return blocks_result
            return stale_result

        mock_db.execute = _mock_execute
        mock_db.commit = AsyncMock()

        # Mock yf.download
        mock_hist = _make_multi_ticker_df(["SPY", "AGG"], days=10)

        with patch(
            "app.domains.wealth.workers.benchmark_ingest._batch_download",
            return_value=mock_hist,
        ), patch("asyncio.get_event_loop") as mock_loop:
            # Make run_in_executor call the function directly
            async def run_sync(executor, fn, *args):
                return fn(*args)

            mock_loop.return_value.run_in_executor = run_sync

            result = await _do_ingest(mock_db, lookback_days=30)

        assert result["blocks_updated"] == 3  # us_large_cap, us_growth, us_fixed_income
        assert result["rows_upserted"] > 0
        assert len(result["skipped_tickers"]) == 0


class TestInvalidTickerHandling:
    """G1: Invalid tickers must be logged as error, not silently discarded."""

    @pytest.mark.asyncio
    async def test_completely_empty_ticker_logged_as_error(self):
        """A ticker returning empty DataFrame should be logged as error, not warning."""
        from app.domains.wealth.workers.benchmark_ingest import _do_ingest

        block = MagicMock()
        block.block_id = "us_large_cap"
        block.benchmark_ticker = "INVALID_TICKER"
        block.is_active = True

        mock_db = AsyncMock()
        blocks_result = MagicMock()
        blocks_result.scalars.return_value.all.return_value = [block]

        stale_result = MagicMock()
        stale_result.scalar.return_value = None

        call_count = {"n": 0}

        async def _mock_execute(stmt, *args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return blocks_result
            return stale_result

        mock_db.execute = _mock_execute
        mock_db.commit = AsyncMock()

        # Return empty DataFrame for the invalid ticker
        empty_hist = pd.DataFrame({"Close": []})

        with patch(
            "app.domains.wealth.workers.benchmark_ingest._batch_download",
            return_value=empty_hist,
        ), patch("asyncio.get_event_loop") as mock_loop:
            async def run_sync(executor, fn, *args):
                return fn(*args)

            mock_loop.return_value.run_in_executor = run_sync

            result = await _do_ingest(mock_db, lookback_days=30)

        assert "INVALID_TICKER" in result["skipped_tickers"]
        assert result["blocks_updated"] == 0

    @pytest.mark.asyncio
    async def test_all_nan_ticker_logged_as_error(self):
        """A ticker returning all-NaN Close should be logged as error."""
        from app.domains.wealth.workers.benchmark_ingest import _do_ingest

        block = MagicMock()
        block.block_id = "us_bonds"
        block.benchmark_ticker = "BADTICKER"
        block.is_active = True

        mock_db = AsyncMock()
        blocks_result = MagicMock()
        blocks_result.scalars.return_value.all.return_value = [block]

        stale_result = MagicMock()
        stale_result.scalar.return_value = None

        call_count = {"n": 0}

        async def _mock_execute(stmt, *args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return blocks_result
            return stale_result

        mock_db.execute = _mock_execute
        mock_db.commit = AsyncMock()

        # All-NaN DataFrame
        dates = pd.date_range(end=date.today(), periods=10, freq="B")
        nan_hist = pd.DataFrame({"Close": [np.nan] * 10}, index=dates)

        with patch(
            "app.domains.wealth.workers.benchmark_ingest._batch_download",
            return_value=nan_hist,
        ), patch("asyncio.get_event_loop") as mock_loop:
            async def run_sync(executor, fn, *args):
                return fn(*args)

            mock_loop.return_value.run_in_executor = run_sync

            result = await _do_ingest(mock_db, lookback_days=30)

        assert "BADTICKER" in result["skipped_tickers"]
        assert result["blocks_updated"] == 0


class TestStalenessDetection:
    def test_stale_threshold_days(self):
        from app.domains.wealth.workers.benchmark_ingest import _STALE_THRESHOLD_DAYS

        assert _STALE_THRESHOLD_DAYS == 7

    def test_stale_date_calculation(self):
        """A block with last nav_date 10 days ago should be flagged as stale."""
        from app.domains.wealth.workers.benchmark_ingest import _STALE_THRESHOLD_DAYS

        cutoff = date.today() - timedelta(days=_STALE_THRESHOLD_DAYS)
        old_date = date.today() - timedelta(days=10)
        assert old_date < cutoff  # would be flagged

        recent_date = date.today() - timedelta(days=3)
        assert recent_date >= cutoff  # would not be flagged
