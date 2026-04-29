"""C-10: benchmark_ingest must use ExternalProviderGate, not manual retry.

Tests that:
- A Tiingo timeout returns a degraded marker (skipped_tickers) instead of raising.
- The gate module-level instance exists and has correct config.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.runtime.provider_gate import ProviderGateError


class TestBenchmarkIngestGate:
    """Verify ExternalProviderGate is wired into benchmark_ingest."""

    def test_gate_exists_with_correct_config(self):
        from app.domains.wealth.workers.benchmark_ingest import _tiingo_gate

        assert _tiingo_gate._cfg.name == "tiingo_benchmark"
        assert _tiingo_gate._cfg.timeout_s == 60.0
        assert _tiingo_gate._cfg.failure_threshold == 3
        assert _tiingo_gate._cfg.recovery_after_s == 300.0

    def test_manual_retry_constants_removed(self):
        """MAX_RETRIES and BACKOFF_BASE should no longer exist."""
        import app.domains.wealth.workers.benchmark_ingest as mod

        assert not hasattr(mod, "MAX_RETRIES")
        assert not hasattr(mod, "BACKOFF_BASE")

    @pytest.mark.asyncio
    async def test_tiingo_timeout_returns_degraded_not_raise(self):
        """When the gate raises ProviderGateError (timeout/circuit open),
        _do_ingest must return a degraded result with skipped_tickers,
        NOT propagate the exception."""
        from app.domains.wealth.workers.benchmark_ingest import _do_ingest

        # Create mock blocks
        block = MagicMock()
        block.block_id = "us_equity"
        block.benchmark_ticker = "SPY"
        block.is_active = True

        mock_db = AsyncMock()
        blocks_result = MagicMock()
        blocks_result.scalars.return_value.all.return_value = [block]
        mock_db.execute.return_value = blocks_result

        # Patch the gate to raise ProviderGateError (simulates timeout)
        with patch(
            "app.domains.wealth.workers.benchmark_ingest._tiingo_gate"
        ) as mock_gate:
            mock_gate.call = AsyncMock(
                side_effect=ProviderGateError("provider 'tiingo_benchmark' timed out after 60.0s"),
            )

            result = await _do_ingest(mock_db, lookback_days=30)

        # Must return degraded result, not raise
        assert result["blocks_updated"] == 0
        assert result["rows_upserted"] == 0
        assert "SPY" in result["skipped_tickers"]
