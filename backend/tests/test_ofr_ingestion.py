"""Tests for ofr_ingestion worker and DB reader functions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from quant_engine.ofr_hedge_fund_service import (
    IndustrySizeSnapshot,
    LeverageSnapshot,
    RepoVolumeSnapshot,
    RiskScenarioSnapshot,
    StrategySnapshot,
    get_ofr_industry_size_from_db,
    get_ofr_leverage_from_db,
    get_ofr_repo_volumes_from_db,
    get_ofr_risk_scenarios_from_db,
)

# ═══════════════════════════════════════════════════════════════════════════
#  Model tests
# ═══════════════════════════════════════════════════════════════════════════


class TestOfrHedgeFundDataModel:
    """Validate ORM model structure."""

    def test_table_name(self) -> None:
        from app.shared.models import OfrHedgeFundData
        assert OfrHedgeFundData.__tablename__ == "ofr_hedge_fund_data"

    def test_primary_key_columns(self) -> None:
        from app.shared.models import OfrHedgeFundData
        pk_cols = [c.name for c in OfrHedgeFundData.__table__.primary_key.columns]
        assert "obs_date" in pk_cols
        assert "series_id" in pk_cols

    def test_source_default(self) -> None:
        from app.shared.models import OfrHedgeFundData
        col = OfrHedgeFundData.__table__.c.source
        assert col.server_default is not None


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


class TestOfrIngestionWorker:
    """Test the OFR worker function with mocked DB and API."""

    @pytest.mark.asyncio
    async def test_lock_held_skips(self) -> None:
        """If advisory lock is held, worker returns skipped."""
        factory, _ = _make_mock_session(lock_acquired=False)

        with patch(
            "app.domains.wealth.workers.ofr_ingestion.async_session",
            factory,
        ):
            from app.domains.wealth.workers.ofr_ingestion import run_ofr_ingestion

            result = await run_ofr_ingestion()

        assert result["status"] == "skipped"
        assert result["reason"] == "lock_held"

    @pytest.mark.asyncio
    async def test_successful_ingestion(self) -> None:
        """Worker fetches, converts, and upserts OFR data."""
        factory, mock_db = _make_mock_session(lock_acquired=True)

        mock_leverage = [
            LeverageSnapshot(date="2026-03-01", gav_weighted_mean=2.5, p5=1.2, p50=1.8, p95=3.5),
        ]
        mock_sizes = [
            IndustrySizeSnapshot(date="2026-03-01", gav_sum=5_000_000.0, nav_sum=3_000_000.0, fund_count=1200.0),
        ]
        mock_repo = [
            RepoVolumeSnapshot(date="2026-03-01", volume=800_000_000.0),
        ]

        with (
            patch(
                "app.domains.wealth.workers.ofr_ingestion.async_session",
                factory,
            ),
            patch(
                "app.domains.wealth.workers.ofr_ingestion.OFRHedgeFundService",
            ) as MockService,
        ):
            svc = AsyncMock()
            svc.fetch_industry_leverage = AsyncMock(return_value=mock_leverage)
            svc.fetch_industry_size = AsyncMock(return_value=mock_sizes)
            svc.fetch_strategy_breakdown = AsyncMock(return_value=[])
            svc.fetch_counterparty_concentration = AsyncMock(return_value=[])
            svc.fetch_repo_volumes = AsyncMock(return_value=mock_repo)
            svc.fetch_risk_scenarios = AsyncMock(return_value=[])
            MockService.return_value = svc

            from app.domains.wealth.workers.ofr_ingestion import run_ofr_ingestion

            result = await run_ofr_ingestion(lookback_years=1)

        assert result["status"] == "completed"
        # 4 leverage fields + 3 industry size fields + 1 repo = 8
        assert result["rows"] == 8
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_partial_failure_continues(self) -> None:
        """Worker continues when some API calls fail."""
        factory, mock_db = _make_mock_session(lock_acquired=True)

        with (
            patch(
                "app.domains.wealth.workers.ofr_ingestion.async_session",
                factory,
            ),
            patch(
                "app.domains.wealth.workers.ofr_ingestion.OFRHedgeFundService",
            ) as MockService,
        ):
            svc = AsyncMock()
            svc.fetch_industry_leverage = AsyncMock(side_effect=Exception("API timeout"))
            svc.fetch_industry_size = AsyncMock(return_value=[])
            svc.fetch_strategy_breakdown = AsyncMock(return_value=[
                StrategySnapshot(date="2026-03-01", strategy="equity", gav_sum=1_000_000.0),
            ])
            svc.fetch_counterparty_concentration = AsyncMock(return_value=[])
            svc.fetch_repo_volumes = AsyncMock(return_value=[])
            svc.fetch_risk_scenarios = AsyncMock(return_value=[
                RiskScenarioSnapshot(date="2026-03-01", scenario="cds_down_250bps_p5", value=-0.15),
            ])
            MockService.return_value = svc

            from app.domains.wealth.workers.ofr_ingestion import run_ofr_ingestion

            result = await run_ofr_ingestion(lookback_years=1)

        assert result["status"] == "completed"
        # 1 strategy + 1 risk scenario = 2 (leverage failed)
        assert result["rows"] == 2


# ═══════════════════════════════════════════════════════════════════════════
#  DB reader function tests
# ═══════════════════════════════════════════════════════════════════════════


class TestOfrDbReaders:
    """Test DB reader functions with mocked sessions."""

    @pytest.mark.asyncio
    async def test_get_ofr_leverage_from_db(self) -> None:
        mock_row = type("Row", (), {
            "obs_date": date(2026, 3, 1),
            "series_id": "OFR_LEVERAGE_WEIGHTED_MEAN",
            "value": Decimal("2.50"),
        })()

        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        rows = await get_ofr_leverage_from_db(mock_db, lookback_days=30)
        assert len(rows) == 1
        assert rows[0]["series_id"] == "OFR_LEVERAGE_WEIGHTED_MEAN"
        assert rows[0]["value"] == 2.50

    @pytest.mark.asyncio
    async def test_get_ofr_industry_size_from_db(self) -> None:
        mock_row = type("Row", (), {
            "obs_date": date(2026, 3, 1),
            "series_id": "OFR_INDUSTRY_GAV",
            "value": Decimal(5000000),
        })()

        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        rows = await get_ofr_industry_size_from_db(mock_db, lookback_days=30)
        assert len(rows) == 1
        assert rows[0]["series_id"] == "OFR_INDUSTRY_GAV"

    @pytest.mark.asyncio
    async def test_get_ofr_repo_volumes_from_db(self) -> None:
        mock_row = type("Row", (), {
            "obs_date": date(2026, 3, 1),
            "value": Decimal(800000000),
        })()

        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        rows = await get_ofr_repo_volumes_from_db(mock_db, lookback_days=30)
        assert len(rows) == 1
        assert rows[0]["value"] == 800000000.0

    @pytest.mark.asyncio
    async def test_get_ofr_risk_scenarios_from_db(self) -> None:
        mock_row = type("Row", (), {
            "obs_date": date(2026, 3, 1),
            "series_id": "OFR_CDS_DOWN_250BPS_P5",
            "value": Decimal("-0.15"),
        })()

        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        rows = await get_ofr_risk_scenarios_from_db(mock_db, lookback_days=30)
        assert len(rows) == 1
        assert rows[0]["series_id"] == "OFR_CDS_DOWN_250BPS_P5"

    @pytest.mark.asyncio
    async def test_none_values_filtered(self) -> None:
        """Rows with None values should be excluded from results."""
        mock_row = type("Row", (), {
            "obs_date": date(2026, 3, 1),
            "series_id": "OFR_LEVERAGE_P50",
            "value": None,
        })()

        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        rows = await get_ofr_leverage_from_db(mock_db, lookback_days=30)
        assert len(rows) == 0
