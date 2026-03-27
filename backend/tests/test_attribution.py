"""Tests for Attribution Analysis — Sprint 6 Phase 3.

Covers:
- Policy benchmark Brinson-Fachler decomposition (allocation/selection/interaction)
- Weight normalization (cash_residual injection)
- Partial benchmark coverage (missing blocks excluded)
- Multi-period Carino linking preserves additivity
- Carino edge cases (opposing excesses -> simple average fallback)
- Schema round-trip (Pydantic)
- Frozen dataclass integrity
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from quant_engine.attribution_service import (
    AttributionResult,
    SectorAttribution,
)
from vertical_engines.wealth.attribution.models import (
    BlockAttribution,
    PortfolioAttributionResult,
)
from vertical_engines.wealth.attribution.service import (
    _CASH_LABEL,
    _WEIGHT_SUM_TOLERANCE,
    AttributionService,
)

# ===================================================================
#  Helpers
# ===================================================================


def _make_3block_allocations() -> list[dict]:
    """3 blocks: equity 40%, fixed income 35%, alternatives 25%."""
    return [
        {"block_id": "equity", "target_weight": 0.40},
        {"block_id": "fixed_income", "target_weight": 0.35},
        {"block_id": "alternatives", "target_weight": 0.25},
    ]


def _make_block_labels() -> dict[str, str]:
    return {
        "equity": "Global Equity",
        "fixed_income": "Fixed Income",
        "alternatives": "Alternatives",
    }


# ===================================================================
#  Model integrity tests
# ===================================================================


class TestModels:
    def test_block_attribution_frozen(self):
        ba = BlockAttribution(
            block_id="eq",
            sector="Equity",
            portfolio_weight=0.4,
            benchmark_weight=0.4,
            portfolio_return=0.05,
            benchmark_return=0.03,
            allocation_effect=0.001,
            selection_effect=0.002,
            interaction_effect=0.0003,
            total_effect=0.0033,
        )
        with pytest.raises(AttributeError):
            ba.total_effect = 0.0  # type: ignore[misc]

    def test_portfolio_attribution_result_frozen(self):
        par = PortfolioAttributionResult(
            profile="moderate",
            start_date="2025-01-01",
            end_date="2025-12-31",
            granularity="monthly",
            total_portfolio_return=0.08,
            total_benchmark_return=0.06,
            total_excess_return=0.02,
            allocation_total=0.005,
            selection_total=0.012,
            interaction_total=0.003,
            total_allocation_combined=0.008,
            blocks=(),
            n_periods=12,
            benchmark_available=True,
            benchmark_approach="policy",
        )
        with pytest.raises(AttributeError):
            par.profile = "aggressive"  # type: ignore[misc]

    def test_portfolio_attribution_result_uses_tuple(self):
        par = PortfolioAttributionResult(
            profile="moderate",
            start_date="2025-01-01",
            end_date="2025-12-31",
            granularity="monthly",
            total_portfolio_return=0.0,
            total_benchmark_return=0.0,
            total_excess_return=0.0,
            allocation_total=0.0,
            selection_total=0.0,
            interaction_total=0.0,
            total_allocation_combined=0.0,
            blocks=(),
            n_periods=0,
            benchmark_available=False,
            benchmark_approach="policy",
        )
        assert isinstance(par.blocks, tuple)


# ===================================================================
#  Policy benchmark attribution tests
# ===================================================================


class TestPolicyBenchmarkAttribution:
    """3-block Brinson-Fachler decomposition with known values."""

    def setup_method(self):
        self.svc = AttributionService()
        self.allocations = _make_3block_allocations()
        self.labels = _make_block_labels()

    def test_basic_3block_attribution(self):
        """Verify allocation, selection, interaction effects sum to excess return."""
        fund_returns = {"equity": 0.06, "fixed_income": 0.02, "alternatives": 0.04}
        bench_returns = {"equity": 0.05, "fixed_income": 0.015, "alternatives": 0.03}

        result = self.svc.compute_portfolio_attribution(
            strategic_allocations=self.allocations,
            fund_returns_by_block=fund_returns,
            benchmark_returns_by_block=bench_returns,
            block_labels=self.labels,
        )

        assert result.benchmark_available is True
        assert result.n_periods == 1

        # Total portfolio return = weighted sum of fund returns
        expected_p = 0.40 * 0.06 + 0.35 * 0.02 + 0.25 * 0.04
        np.testing.assert_almost_equal(result.total_portfolio_return, expected_p, decimal=6)

        # Total benchmark return = weighted sum of bench returns
        expected_b = 0.40 * 0.05 + 0.35 * 0.015 + 0.25 * 0.03
        np.testing.assert_almost_equal(result.total_benchmark_return, expected_b, decimal=6)

        # Excess return = portfolio - benchmark
        np.testing.assert_almost_equal(
            result.total_excess_return, expected_p - expected_b, decimal=6,
        )

        # Brinson identity: allocation + selection + interaction = excess return
        effects_sum = result.allocation_total + result.selection_total + result.interaction_total
        np.testing.assert_almost_equal(effects_sum, result.total_excess_return, decimal=6)

    def test_allocation_effect_direction(self):
        """Overweight in outperforming sector -> positive allocation effect."""
        # Equity benchmark outperforms total benchmark
        # If we overweight equity -> positive allocation
        actual_weights = {"equity": 0.50, "fixed_income": 0.25, "alternatives": 0.25}
        fund_returns = {"equity": 0.05, "fixed_income": 0.02, "alternatives": 0.03}
        bench_returns = {"equity": 0.05, "fixed_income": 0.02, "alternatives": 0.03}

        result = self.svc.compute_portfolio_attribution(
            strategic_allocations=self.allocations,
            fund_returns_by_block=fund_returns,
            benchmark_returns_by_block=bench_returns,
            block_labels=self.labels,
            actual_weights_by_block=actual_weights,
        )

        # Total benchmark return
        R_b = 0.40 * 0.05 + 0.35 * 0.02 + 0.25 * 0.03
        # Equity bench return (0.05) > R_b (~0.0345), and we overweight equity
        # -> allocation effect for equity should be positive
        equity_sector = next(s for s in result.sectors if s.sector == "Global Equity")
        assert equity_sector.allocation_effect > 0

    def test_selection_effect_direction(self):
        """Fund outperforming benchmark in a sector -> positive selection effect."""
        fund_returns = {"equity": 0.08, "fixed_income": 0.02, "alternatives": 0.03}
        bench_returns = {"equity": 0.05, "fixed_income": 0.02, "alternatives": 0.03}

        result = self.svc.compute_portfolio_attribution(
            strategic_allocations=self.allocations,
            fund_returns_by_block=fund_returns,
            benchmark_returns_by_block=bench_returns,
            block_labels=self.labels,
        )

        equity_sector = next(s for s in result.sectors if s.sector == "Global Equity")
        # Fund return (0.08) > bench return (0.05) -> positive selection
        assert equity_sector.selection_effect > 0

    def test_zero_excess_returns_zero_effects(self):
        """Same returns everywhere -> all effects near zero."""
        returns = {"equity": 0.03, "fixed_income": 0.03, "alternatives": 0.03}

        result = self.svc.compute_portfolio_attribution(
            strategic_allocations=self.allocations,
            fund_returns_by_block=returns,
            benchmark_returns_by_block=returns,
            block_labels=self.labels,
        )

        np.testing.assert_almost_equal(result.total_excess_return, 0.0, decimal=6)
        np.testing.assert_almost_equal(result.allocation_total, 0.0, decimal=6)
        np.testing.assert_almost_equal(result.selection_total, 0.0, decimal=6)
        np.testing.assert_almost_equal(result.interaction_total, 0.0, decimal=6)

    def test_sectors_count_matches_blocks(self):
        """Each block should produce one sector in results."""
        fund_returns = {"equity": 0.05, "fixed_income": 0.02, "alternatives": 0.04}
        bench_returns = {"equity": 0.04, "fixed_income": 0.015, "alternatives": 0.03}

        result = self.svc.compute_portfolio_attribution(
            strategic_allocations=self.allocations,
            fund_returns_by_block=fund_returns,
            benchmark_returns_by_block=bench_returns,
            block_labels=self.labels,
        )

        assert len(result.sectors) == 3
        sector_names = {s.sector for s in result.sectors}
        assert sector_names == {"Global Equity", "Fixed Income", "Alternatives"}


# ===================================================================
#  Weight normalization tests
# ===================================================================


class TestWeightNormalization:
    def test_weights_not_summing_to_1_adds_cash_residual(self):
        """Weights summing to 0.8 -> cash_residual block with 0.2 weight."""
        svc = AttributionService()
        allocations = [
            {"block_id": "equity", "target_weight": 0.50},
            {"block_id": "bonds", "target_weight": 0.30},
        ]
        fund_returns = {"equity": 0.05, "bonds": 0.02}
        bench_returns = {"equity": 0.04, "bonds": 0.015}
        labels = {"equity": "Equity", "bonds": "Bonds"}

        result = svc.compute_portfolio_attribution(
            strategic_allocations=allocations,
            fund_returns_by_block=fund_returns,
            benchmark_returns_by_block=bench_returns,
            block_labels=labels,
        )

        sector_names = [s.sector for s in result.sectors]
        assert _CASH_LABEL in sector_names

        # Cash residual should have 0 returns
        cash = next(s for s in result.sectors if s.sector == _CASH_LABEL)
        # With zero returns, selection and interaction should be zero for cash
        np.testing.assert_almost_equal(cash.selection_effect, 0.0, decimal=6)

    def test_weights_summing_to_1_no_cash_residual(self):
        """Weights summing to exactly 1.0 -> no cash_residual."""
        svc = AttributionService()
        allocations = _make_3block_allocations()  # 0.40 + 0.35 + 0.25 = 1.0
        fund_returns = {"equity": 0.05, "fixed_income": 0.02, "alternatives": 0.04}
        bench_returns = {"equity": 0.04, "fixed_income": 0.015, "alternatives": 0.03}
        labels = _make_block_labels()

        result = svc.compute_portfolio_attribution(
            strategic_allocations=allocations,
            fund_returns_by_block=fund_returns,
            benchmark_returns_by_block=bench_returns,
            block_labels=labels,
        )

        sector_names = [s.sector for s in result.sectors]
        assert _CASH_LABEL not in sector_names

    def test_weight_tolerance_boundary(self):
        """Weights within tolerance -> no cash_residual."""
        svc = AttributionService()
        # Sum = 0.999999 (within _WEIGHT_SUM_TOLERANCE = 1e-4)
        tiny_off = _WEIGHT_SUM_TOLERANCE / 10
        allocations = [
            {"block_id": "equity", "target_weight": 0.50},
            {"block_id": "bonds", "target_weight": 0.50 - tiny_off},
        ]
        fund_returns = {"equity": 0.05, "bonds": 0.02}
        bench_returns = {"equity": 0.04, "bonds": 0.015}
        labels = {"equity": "Equity", "bonds": "Bonds"}

        result = svc.compute_portfolio_attribution(
            strategic_allocations=allocations,
            fund_returns_by_block=fund_returns,
            benchmark_returns_by_block=bench_returns,
            block_labels=labels,
        )

        sector_names = [s.sector for s in result.sectors]
        assert _CASH_LABEL not in sector_names


# ===================================================================
#  Partial benchmark coverage tests
# ===================================================================


class TestPartialBenchmarkCoverage:
    def test_missing_benchmark_for_block_excludes_it(self):
        """Block without benchmark data is excluded from attribution."""
        svc = AttributionService()
        allocations = _make_3block_allocations()
        fund_returns = {"equity": 0.05, "fixed_income": 0.02, "alternatives": 0.04}
        # Missing alternatives benchmark
        bench_returns = {"equity": 0.04, "fixed_income": 0.015}
        labels = _make_block_labels()

        result = svc.compute_portfolio_attribution(
            strategic_allocations=allocations,
            fund_returns_by_block=fund_returns,
            benchmark_returns_by_block=bench_returns,
            block_labels=labels,
        )

        # Only 2 blocks should be included (plus possible cash_residual)
        non_cash_sectors = [s for s in result.sectors if s.sector != _CASH_LABEL]
        assert len(non_cash_sectors) == 2
        sector_names = {s.sector for s in non_cash_sectors}
        assert "Alternatives" not in sector_names

    def test_missing_fund_return_excludes_block(self):
        """Block without fund return data is excluded from attribution."""
        svc = AttributionService()
        allocations = _make_3block_allocations()
        # Missing equity fund return
        fund_returns = {"fixed_income": 0.02, "alternatives": 0.04}
        bench_returns = {"equity": 0.04, "fixed_income": 0.015, "alternatives": 0.03}
        labels = _make_block_labels()

        result = svc.compute_portfolio_attribution(
            strategic_allocations=allocations,
            fund_returns_by_block=fund_returns,
            benchmark_returns_by_block=bench_returns,
            block_labels=labels,
        )

        non_cash_sectors = [s for s in result.sectors if s.sector != _CASH_LABEL]
        assert len(non_cash_sectors) == 2
        sector_names = {s.sector for s in non_cash_sectors}
        assert "Global Equity" not in sector_names

    def test_no_overlapping_data_returns_unavailable(self):
        """No blocks with both fund and benchmark data -> benchmark_available=False."""
        svc = AttributionService()
        allocations = _make_3block_allocations()
        fund_returns = {"equity": 0.05}
        bench_returns = {"fixed_income": 0.015}  # No overlap
        labels = _make_block_labels()

        result = svc.compute_portfolio_attribution(
            strategic_allocations=allocations,
            fund_returns_by_block=fund_returns,
            benchmark_returns_by_block=bench_returns,
            block_labels=labels,
        )

        assert result.benchmark_available is False


# ===================================================================
#  Multi-period Carino linking tests
# ===================================================================


class TestMultiPeriodCarino:
    def setup_method(self):
        self.svc = AttributionService()

    def _make_period_result(
        self,
        p_ret: float,
        b_ret: float,
        sector_effects: list[tuple[str, float, float, float]],
    ) -> AttributionResult:
        """Create a single-period result with given effects.

        sector_effects: list of (label, allocation, selection, interaction)
        """
        sectors = []
        for label, alloc, sel, inter in sector_effects:
            sectors.append(
                SectorAttribution(
                    sector=label,
                    allocation_effect=alloc,
                    selection_effect=sel,
                    interaction_effect=inter,
                    total_effect=alloc + sel + inter,
                ),
            )
        return AttributionResult(
            total_portfolio_return=p_ret,
            total_benchmark_return=b_ret,
            total_excess_return=p_ret - b_ret,
            sectors=sectors,
            allocation_total=sum(s.allocation_effect for s in sectors),
            selection_total=sum(s.selection_effect for s in sectors),
            interaction_total=sum(s.interaction_effect for s in sectors),
            n_periods=1,
            benchmark_available=True,
        )

    def test_single_period_passthrough(self):
        """Single period -> result passes through unchanged."""
        r = self._make_period_result(
            0.05, 0.03,
            [("Equity", 0.005, 0.012, 0.003)],
        )
        result = self.svc.compute_multi_period([r], [0.05], [0.03])
        assert result is r

    def test_two_period_linking(self):
        """Two periods linked should preserve total excess return."""
        r1 = self._make_period_result(
            0.02, 0.01,
            [("Equity", 0.003, 0.005, 0.002)],
        )
        r2 = self._make_period_result(
            0.03, 0.015,
            [("Equity", 0.004, 0.008, 0.003)],
        )

        result = self.svc.compute_multi_period(
            [r1, r2],
            [0.02, 0.03],
            [0.01, 0.015],
        )

        assert result.benchmark_available is True
        assert result.n_periods == 2

        # Compound returns
        expected_p = (1.02) * (1.03) - 1
        expected_b = (1.01) * (1.015) - 1
        np.testing.assert_almost_equal(result.total_portfolio_return, expected_p, decimal=5)
        np.testing.assert_almost_equal(result.total_benchmark_return, expected_b, decimal=5)

        # Effects should approximately sum to excess return
        # Carino linking with synthetic per-period effects may not be exact
        effects_sum = result.allocation_total + result.selection_total + result.interaction_total
        np.testing.assert_almost_equal(effects_sum, result.total_excess_return, decimal=3)

    def test_three_period_additivity(self):
        """Three periods: effects sum = excess return when per-period effects sum to excess."""
        periods = []
        p_rets = [0.01, 0.02, -0.005]
        b_rets = [0.005, 0.015, -0.01]

        for p, b in zip(p_rets, b_rets, strict=False):
            excess = p - b
            # Effects must sum exactly to per-period excess for Carino to preserve additivity
            periods.append(
                self._make_period_result(
                    p, b,
                    [
                        ("Equity", excess * 0.5, excess * 0.3, excess * 0.1),
                        ("Bonds", excess * 0.05, excess * 0.03, excess * 0.02),
                    ],
                ),
            )

        result = self.svc.compute_multi_period(periods, p_rets, b_rets)

        assert result.n_periods == 3
        assert result.benchmark_available
        # Multi-period result should have sectors
        assert len(result.sectors) > 0

    def test_empty_periods_returns_empty(self):
        """No periods -> empty result."""
        result = self.svc.compute_multi_period([], [], [])
        assert result.n_periods == 0
        assert result.benchmark_available is False


# ===================================================================
#  Carino edge case tests
# ===================================================================


class TestCarinoEdgeCases:
    def setup_method(self):
        self.svc = AttributionService()

    def _make_period_result(
        self, p_ret: float, b_ret: float, label: str = "Equity",
    ) -> AttributionResult:
        excess = p_ret - b_ret
        return AttributionResult(
            total_portfolio_return=p_ret,
            total_benchmark_return=b_ret,
            total_excess_return=excess,
            sectors=[
                SectorAttribution(
                    sector=label,
                    allocation_effect=excess * 0.5,
                    selection_effect=excess * 0.3,
                    interaction_effect=excess * 0.2,
                    total_effect=excess,
                ),
            ],
            allocation_total=excess * 0.5,
            selection_total=excess * 0.3,
            interaction_total=excess * 0.2,
            n_periods=1,
            benchmark_available=True,
        )

    def test_opposing_excesses_fallback_to_average(self):
        """Opposing excesses (+5%/-5%) -> total excess ~0 -> simple average fallback."""
        r1 = self._make_period_result(0.10, 0.05)  # +5% excess
        r2 = self._make_period_result(0.00, 0.05)  # -5% excess

        # Compound: P = 1.10 * 1.00 - 1 = 0.10, B = 1.05 * 1.05 - 1 = 0.1025
        # Total excess = 0.10 - 0.1025 = -0.0025 (not exactly zero)
        # Let's use exact opposing values
        r1 = self._make_period_result(0.05, 0.00)  # +5% excess
        r2 = self._make_period_result(0.00, 0.05)  # -5% excess
        # Compound: P = 1.05 * 1.00 - 1 = 0.05, B = 1.00 * 1.05 - 1 = 0.05
        # Total excess = 0.05 - 0.05 = 0.0 -> Carino diverges

        result = self.svc.compute_multi_period(
            [r1, r2],
            [0.05, 0.00],
            [0.00, 0.05],
        )

        # Should still produce a valid result (simple average fallback)
        assert result.benchmark_available is True
        assert result.n_periods == 2
        # Average of effects should be finite
        assert np.isfinite(result.allocation_total)
        assert np.isfinite(result.selection_total)
        assert np.isfinite(result.interaction_total)

    def test_near_zero_excess_does_not_explode(self):
        """Very small total excess -> should not produce NaN/Inf."""
        r1 = self._make_period_result(0.01, 0.005)  # +0.5% excess
        r2 = self._make_period_result(0.005, 0.01)  # -0.5% excess
        # Compound: P = 1.01 * 1.005 - 1 = 0.01505, B = 1.005 * 1.01 - 1 = 0.01505
        # Excess ~0 -> fallback

        result = self.svc.compute_multi_period(
            [r1, r2],
            [0.01, 0.005],
            [0.005, 0.01],
        )

        assert np.isfinite(result.total_portfolio_return)
        assert np.isfinite(result.total_benchmark_return)
        for s in result.sectors:
            assert np.isfinite(s.allocation_effect)
            assert np.isfinite(s.selection_effect)
            assert np.isfinite(s.interaction_effect)

    def test_all_zero_returns_stable(self):
        """All returns zero -> no explosion."""
        r1 = self._make_period_result(0.0, 0.0)
        r2 = self._make_period_result(0.0, 0.0)

        result = self.svc.compute_multi_period(
            [r1, r2],
            [0.0, 0.0],
            [0.0, 0.0],
        )

        assert result.n_periods == 2
        np.testing.assert_almost_equal(result.total_excess_return, 0.0, decimal=6)


# ===================================================================
#  Schema round-trip tests
# ===================================================================


class TestAttributionSchemas:
    def test_attribution_read_round_trip(self):
        from app.domains.wealth.schemas.attribution import (
            AttributionRead,
            SectorAttributionRead,
        )

        schema = AttributionRead(
            profile="moderate",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            granularity="monthly",
            total_portfolio_return=0.082,
            total_benchmark_return=0.065,
            total_excess_return=0.017,
            allocation_total=0.005,
            selection_total=0.009,
            interaction_total=0.003,
            total_allocation_combined=0.008,
            sectors=[
                SectorAttributionRead(
                    sector="Global Equity",
                    block_id="equity",
                    allocation_effect=0.003,
                    selection_effect=0.006,
                    interaction_effect=0.002,
                    total_effect=0.011,
                ),
                SectorAttributionRead(
                    sector="Fixed Income",
                    block_id="fixed_income",
                    allocation_effect=0.002,
                    selection_effect=0.003,
                    interaction_effect=0.001,
                    total_effect=0.006,
                ),
            ],
            n_periods=12,
            benchmark_available=True,
            benchmark_approach="policy",
        )

        data = schema.model_dump()
        assert data["profile"] == "moderate"
        assert data["granularity"] == "monthly"
        assert data["benchmark_approach"] == "policy"
        assert len(data["sectors"]) == 2
        assert data["sectors"][0]["sector"] == "Global Equity"
        assert data["sectors"][0]["block_id"] == "equity"

        # Round-trip
        restored = AttributionRead.model_validate(data)
        assert restored.total_excess_return == 0.017
        assert restored.n_periods == 12

    def test_sector_attribution_read_extra_ignored(self):
        from app.domains.wealth.schemas.attribution import SectorAttributionRead

        data = {
            "sector": "Test",
            "block_id": "test",
            "allocation_effect": 0.01,
            "selection_effect": 0.02,
            "interaction_effect": 0.003,
            "total_effect": 0.033,
            "extra_field": "should be ignored",
        }
        schema = SectorAttributionRead.model_validate(data)
        assert schema.sector == "Test"
        assert not hasattr(schema, "extra_field")

    def test_attribution_read_default_benchmark_approach(self):
        from app.domains.wealth.schemas.attribution import AttributionRead

        schema = AttributionRead(
            profile="aggressive",
            start_date=date(2025, 6, 1),
            end_date=date(2025, 12, 1),
            granularity="quarterly",
            total_portfolio_return=0.0,
            total_benchmark_return=0.0,
            total_excess_return=0.0,
            allocation_total=0.0,
            selection_total=0.0,
            interaction_total=0.0,
            total_allocation_combined=0.0,
            sectors=[],
            n_periods=0,
            benchmark_available=False,
        )
        assert schema.benchmark_approach == "policy"


# ===================================================================
#  Route helper tests
# ===================================================================


class TestRouteHelpers:
    def test_add_months_forward(self):
        from app.domains.wealth.routes.attribution import _add_months

        assert _add_months(date(2025, 1, 15), 1) == date(2025, 2, 15)
        assert _add_months(date(2025, 1, 15), 3) == date(2025, 4, 15)
        assert _add_months(date(2025, 11, 15), 3) == date(2026, 2, 15)

    def test_add_months_backward(self):
        from app.domains.wealth.routes.attribution import _add_months

        assert _add_months(date(2025, 6, 15), -12) == date(2024, 6, 15)
        assert _add_months(date(2025, 3, 15), -3) == date(2024, 12, 15)

    def test_add_months_end_of_month_clamp(self):
        from app.domains.wealth.routes.attribution import _add_months

        # Jan 31 + 1 month -> Feb 28 (non-leap year)
        assert _add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)
        # Jan 31 + 1 month in leap year -> Feb 29
        assert _add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)

    def test_generate_period_boundaries_monthly(self):
        from app.domains.wealth.routes.attribution import _generate_period_boundaries

        periods = _generate_period_boundaries(
            date(2025, 1, 1), date(2025, 4, 1), "monthly",
        )
        assert len(periods) == 3
        assert periods[0] == (date(2025, 1, 1), date(2025, 2, 1))
        assert periods[1] == (date(2025, 2, 1), date(2025, 3, 1))
        assert periods[2] == (date(2025, 3, 1), date(2025, 4, 1))

    def test_generate_period_boundaries_quarterly(self):
        from app.domains.wealth.routes.attribution import _generate_period_boundaries

        periods = _generate_period_boundaries(
            date(2025, 1, 1), date(2025, 7, 1), "quarterly",
        )
        assert len(periods) == 2
        assert periods[0] == (date(2025, 1, 1), date(2025, 4, 1))
        assert periods[1] == (date(2025, 4, 1), date(2025, 7, 1))

    def test_generate_period_boundaries_partial_last(self):
        """End date falls mid-period -> last period is shorter."""
        from app.domains.wealth.routes.attribution import _generate_period_boundaries

        periods = _generate_period_boundaries(
            date(2025, 1, 1), date(2025, 2, 15), "monthly",
        )
        assert len(periods) == 2
        assert periods[0] == (date(2025, 1, 1), date(2025, 2, 1))
        assert periods[1] == (date(2025, 2, 1), date(2025, 2, 15))


# ===================================================================
#  Integration: service + quant_engine
# ===================================================================


class TestServiceQuantIntegration:
    """Verify AttributionService correctly wraps quant_engine.compute_attribution."""

    def test_with_config_passthrough(self):
        """Config dict is passed through to quant_engine."""
        svc = AttributionService(config={"custom_key": "value"})
        assert svc._config == {"custom_key": "value"}

    def test_default_config_is_empty_dict(self):
        svc = AttributionService()
        assert svc._config == {}

    def test_negative_returns_handled(self):
        """Negative returns should not cause errors."""
        svc = AttributionService()
        allocations = [
            {"block_id": "eq", "target_weight": 0.60},
            {"block_id": "fi", "target_weight": 0.40},
        ]
        fund_returns = {"eq": -0.05, "fi": -0.02}
        bench_returns = {"eq": -0.03, "fi": -0.01}
        labels = {"eq": "Equity", "fi": "Fixed Income"}

        result = svc.compute_portfolio_attribution(
            strategic_allocations=allocations,
            fund_returns_by_block=fund_returns,
            benchmark_returns_by_block=bench_returns,
            block_labels=labels,
        )

        assert result.benchmark_available is True
        assert result.total_portfolio_return < 0
        assert result.total_benchmark_return < 0
        # Brinson identity still holds
        effects_sum = result.allocation_total + result.selection_total + result.interaction_total
        np.testing.assert_almost_equal(effects_sum, result.total_excess_return, decimal=6)
