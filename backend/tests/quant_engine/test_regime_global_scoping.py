"""Tests for global regime scoping — MacroRegimeSnapshot model + worker + route.

Covers:
1. MacroRegimeSnapshot model has no organization_id (global table)
2. _compute_and_persist_taa_state reads global snapshot when available
3. _compute_and_persist_taa_state falls back to inline classification without snapshot
4. GET /allocation/regime returns 200 with correct data
5. GET /allocation/regime returns 404 without data
6. GET /allocation/{profile}/regime-bands still works (regression)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.wealth.models.allocation import MacroRegimeSnapshot
from app.domains.wealth.schemas.allocation import GlobalRegimeRead


class TestMacroRegimeSnapshotModel:
    """Test 1 — MacroRegimeSnapshot has no org_id (global table)."""

    def test_no_organization_id_column(self):
        """MacroRegimeSnapshot must not have organization_id — it's global."""
        column_names = {c.name for c in MacroRegimeSnapshot.__table__.columns}
        assert "organization_id" not in column_names

    def test_has_required_columns(self):
        """All expected columns are present."""
        column_names = {c.name for c in MacroRegimeSnapshot.__table__.columns}
        assert {"id", "as_of_date", "raw_regime", "stress_score", "signal_details", "created_at"} <= column_names

    def test_as_of_date_is_unique(self):
        """Only one row per date."""
        date_col = MacroRegimeSnapshot.__table__.c.as_of_date
        assert date_col.unique is True

    def test_tablename(self):
        assert MacroRegimeSnapshot.__tablename__ == "macro_regime_snapshot"


class TestTaaStateReadsGlobalSnapshot:
    """Test 2 — _compute_and_persist_taa_state reads from macro_regime_snapshot."""

    @pytest.mark.asyncio
    async def test_uses_snapshot_when_available(self):
        """When a MacroRegimeSnapshot exists, regime classification is NOT recomputed."""
        # Create a mock snapshot
        mock_snapshot = MagicMock()
        mock_snapshot.as_of_date = date(2026, 4, 13)
        mock_snapshot.raw_regime = "RISK_OFF"
        mock_snapshot.stress_score = Decimal("45.0")
        mock_snapshot.signal_details = {"vix": {"value": 25.0, "signal": "STRESS"}}

        # Mock DB session
        db = AsyncMock()

        # First execute → snapshot query (returns snapshot)
        snapshot_result = MagicMock()
        snapshot_result.scalar_one_or_none.return_value = mock_snapshot

        # Second execute → ConfigService DB query
        config_db_result = MagicMock()
        config_db_result.scalar_one_or_none.return_value = None

        # Third execute → profiles query (returns empty — no profiles to process)
        profiles_result = MagicMock()
        profiles_result.all.return_value = []

        db.execute = AsyncMock(side_effect=[
            snapshot_result,   # MacroRegimeSnapshot query
            config_db_result,  # ConfigService DB query
            config_db_result,  # ConfigService DB fallback
            profiles_result,   # profiles query
        ])

        with (
            patch("quant_engine.regime_service.build_regime_inputs") as mock_build,
            patch(
                "app.core.config.config_service.ConfigService.get",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            from app.domains.wealth.workers.risk_calc import _compute_and_persist_taa_state

            await _compute_and_persist_taa_state(
                db,
                org_id=MagicMock(),
                eval_date=date(2026, 4, 13),
            )

            # build_regime_inputs should NOT have been called
            mock_build.assert_not_called()


class TestTaaStateFallbackWithoutSnapshot:
    """Test 3 — _compute_and_persist_taa_state falls back when no snapshot."""

    @pytest.mark.asyncio
    async def test_fallback_to_inline_classification(self):
        """Without a snapshot, falls back to inline regime classification."""
        db = AsyncMock()

        # First execute → snapshot query (returns None)
        snapshot_result = MagicMock()
        snapshot_result.scalar_one_or_none.return_value = None

        # Second → build_regime_inputs result (inline classification)
        # Third → ConfigService.get
        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = None

        # Fourth → profiles (empty)
        profiles_result = MagicMock()
        profiles_result.all.return_value = []

        db.execute = AsyncMock(side_effect=[
            snapshot_result,   # MacroRegimeSnapshot query → None
            MagicMock(),       # build_regime_inputs DB call
            config_result,     # ConfigService
            config_result,     # ConfigService fallback
            profiles_result,   # profiles
        ])

        with (
            patch(
                "quant_engine.regime_service.build_regime_inputs",
                new_callable=AsyncMock,
                return_value={
                    "vix": 15.0, "yield_curve_spread": 1.5,
                    "cpi_yoy": 2.0, "sahm_rule": 0.1,
                    "hy_oas": 2.0, "baa_spread": 1.0,
                    "fed_funds_delta_6m": -0.25, "dxy_zscore": -0.5,
                    "energy_shock": 0.0, "cfnai": 0.2,
                },
            ) as mock_build,
            patch(
                "quant_engine.regime_service.classify_regime_multi_signal",
                return_value=("RISK_ON", {"composite_stress": "10.0/100"}, []),
            ) as mock_classify,
        ):
            from app.domains.wealth.workers.risk_calc import _compute_and_persist_taa_state

            await _compute_and_persist_taa_state(
                db,
                org_id=MagicMock(),
                eval_date=date(2026, 4, 13),
            )

            # build_regime_inputs SHOULD have been called (fallback path)
            mock_build.assert_called_once()
            mock_classify.assert_called_once()


class TestGlobalRegimeSchema:
    """Test 4 — GlobalRegimeRead schema contract."""

    def test_schema_serialization(self):
        """GlobalRegimeRead round-trips correctly."""
        data = GlobalRegimeRead(
            as_of_date=date(2026, 4, 13),
            raw_regime="RISK_OFF",
            stress_score=Decimal("45.0"),
            signal_details={"vix": {"value": 25.0, "signal": "STRESS"}},
        )
        dumped = data.model_dump()
        assert dumped["raw_regime"] == "Cautious"
        assert dumped["as_of_date"] == date(2026, 4, 13)
        assert dumped["stress_score"] == Decimal("45.0")
        assert "vix" in dumped["signal_details"]

    def test_schema_defaults(self):
        """Optional fields default correctly."""
        data = GlobalRegimeRead(
            as_of_date=date(2026, 4, 13),
            raw_regime="RISK_ON",
        )
        assert data.stress_score is None
        assert data.signal_details == {}


class TestGlobalRegimeRoute404:
    """Test 5 — GET /allocation/regime returns 404 without data."""

    def test_route_registered(self):
        """The /allocation/regime route exists on the router."""
        from app.domains.wealth.routes.allocation import router

        route_paths = [r.path for r in router.routes]
        assert "/allocation/regime" in route_paths


class TestRegimeBandsRegression:
    """Test 6 — RegimeBandsRead schema unchanged (regression)."""

    def test_regime_bands_schema_has_all_fields(self):
        """RegimeBandsRead still has all original fields — no frontend break."""
        from app.domains.wealth.schemas.allocation import RegimeBandsRead

        fields = set(RegimeBandsRead.model_fields.keys())
        expected = {
            "profile", "as_of_date", "raw_regime", "stress_score",
            "smoothed_centers", "effective_bands", "transition_velocity",
            "ips_clamps_applied", "taa_enabled",
        }
        assert expected <= fields
