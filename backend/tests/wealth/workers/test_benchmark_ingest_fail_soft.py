"""PR-Q107 — fail-soft tests for benchmark_ingest.

Verifies that both ProviderGateError and non-gate exceptions (KeyError,
JSONDecodeError, etc.) produce the same fail-soft result with skipped_tickers
and blocks_updated == 0, instead of aborting the worker.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.runtime.provider_gate import ProviderGateError


def _make_mock_block(ticker: str, block_id: str) -> MagicMock:
    """Create a mock AllocationBlock with the required attributes."""
    block = MagicMock()
    block.benchmark_ticker = ticker
    block.block_id = block_id
    block.is_active = True
    return block


def _mock_db_with_blocks(blocks: list[MagicMock]) -> AsyncMock:
    """Create a mock async DB session that returns the given blocks on execute."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = blocks
    db.execute = AsyncMock(return_value=result)
    return db


class TestBenchmarkIngestFailSoft:
    """Q107: both gate and non-gate exceptions produce fail-soft result."""

    @pytest.mark.asyncio
    async def test_non_gate_exception_produces_fail_soft_result(self) -> None:
        """KeyError from _fetch_via_tiingo (non-gate) must not abort the worker."""
        from app.domains.wealth.workers.benchmark_ingest import _do_ingest

        blocks = [_make_mock_block("SPY", "blk-001")]
        db = _mock_db_with_blocks(blocks)

        # _tiingo_gate.call re-raises non-timeout exceptions from the coroutine.
        # A KeyError from _fetch_via_tiingo propagates through the gate unwrapped.
        with patch(
            "app.domains.wealth.workers.benchmark_ingest._tiingo_gate",
        ) as mock_gate:
            mock_gate.call = AsyncMock(side_effect=KeyError("malformed payload"))

            result = await _do_ingest(db, lookback_days=30)

        assert result["blocks_updated"] == 0
        assert result["rows_upserted"] == 0
        assert result["skipped_tickers"] == ["SPY"]

    @pytest.mark.asyncio
    async def test_provider_gate_error_produces_fail_soft_result(self) -> None:
        """ProviderGateError (timeout / circuit open) must produce fail-soft result."""
        from app.domains.wealth.workers.benchmark_ingest import _do_ingest

        blocks = [_make_mock_block("AGG", "blk-002")]
        db = _mock_db_with_blocks(blocks)

        with patch(
            "app.domains.wealth.workers.benchmark_ingest._tiingo_gate",
        ) as mock_gate:
            mock_gate.call = AsyncMock(
                side_effect=ProviderGateError("circuit open"),
            )

            result = await _do_ingest(db, lookback_days=30)

        assert result["blocks_updated"] == 0
        assert result["rows_upserted"] == 0
        assert result["skipped_tickers"] == ["AGG"]

    @pytest.mark.asyncio
    async def test_json_decode_error_produces_fail_soft_result(self) -> None:
        """JSONDecodeError (non-gate) must not abort the worker."""
        import json

        from app.domains.wealth.workers.benchmark_ingest import _do_ingest

        blocks = [
            _make_mock_block("SPY", "blk-001"),
            _make_mock_block("AGG", "blk-002"),
        ]
        db = _mock_db_with_blocks(blocks)

        with patch(
            "app.domains.wealth.workers.benchmark_ingest._tiingo_gate",
        ) as mock_gate:
            mock_gate.call = AsyncMock(
                side_effect=json.JSONDecodeError("bad json", "", 0),
            )

            result = await _do_ingest(db, lookback_days=30)

        assert result["blocks_updated"] == 0
        assert result["rows_upserted"] == 0
        # Both tickers should be in skipped list
        assert set(result["skipped_tickers"]) == {"SPY", "AGG"}
